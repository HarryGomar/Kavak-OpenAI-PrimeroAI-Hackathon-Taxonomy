"""Freeze a larger source-only Food sample with verified gold joins from the same subset."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path

from domains.food.adapter import load_listings
from domains.food.evaluate_gold import index, parquet_rows
from domains.food.place_paths import dump_rows, read
from taxo.codex_cli import fingerprint, write


def prepare(reference, output, labeled, size, seed=None, exclude_reference=False):
    if size < 1:
        raise ValueError('Sample size must be positive')
    output.mkdir(parents=True, exist_ok=False)
    old = read(reference/'protocol.json')
    source = Path(old['source']['path'])
    first = json.loads(source.read_text(encoding='utf-8').splitlines()[0])
    original = {json.loads(line)['id'] for line in source.read_text(encoding='utf-8').splitlines()}
    raw_path = Path(first['fields']['source_path'])
    os.environ['TAXO_FOOD_LISTINGS'] = str(raw_path)
    observations = [r.model_dump(mode='json') for r in load_listings()]
    manifest = read(labeled/'manifest.json')
    gold_path = labeled/manifest['output']
    selection_path = raw_path.with_name('selection.parquet')
    if manifest['domain'] != 'food' or any((
        fingerprint(raw_path)['sha256'] != manifest['input_sha256'],
        fingerprint(selection_path)['sha256'] != manifest['selection_sha256'],
        fingerprint(gold_path)['sha256'] != manifest['output_sha256'])):
        raise ValueError('Food gold/source/selection hash mismatch')
    gold = index(parquet_rows(gold_path), 'silver_id')
    selection = index(parquet_rows(selection_path), 'silver_id')
    valid, excluded = [], []
    for row in observations:
        lid = row['id']
        gs, ss = gold.get(lid, []), selection.get(lid, [])
        reasons = []
        if len(gs) != 1 or len(ss) != 1:
            reasons.append('missing_or_duplicate_gold_or_selection')
        else:
            g, s = gs[0], ss[0]
            raw = row['fields']['raw_source']
            if any((str(g['silver_id']) != lid, g['pedia_mention_id'] != f'm4r:{lid}',
                    g['pedia_mention_id'] != s['mention_id'], g['pedia_entity_id'] != s['entity_id'],
                    g['pedia_brand_key'] != s['brand'], g['pedia_join_method'] != 'observation_id',
                    s['join_method'] != 'observation_id', s['source_id'] != row['source'],
                    s['listing_name'] != row['title'], s['market'] != raw.get('market'),
                    bool(g['pedia_conflict_id']), g['pedia_placement_outcome'] == 'unplaced')):
                reasons.append('identity_or_gold_conflict')
            path = g['pedia_full_path'] or []
            hierarchy = g['pedia_entity_hierarchy'] or []
            if not path or path[0]['level'] != 'brand' or path[0]['label'] != g['pedia_brand']:
                reasons.append('inconsistent_brand_path')
            if any(not any(all(step[k] == e[k] for k in ('label', 'level', 'node_id'))
                           for e in hierarchy) for step in path[1:]):
                reasons.append('inconsistent_entity_hierarchy')
            if not any(e['entity_id'] == g['pedia_entity_id'] and e['depth'] == 0 for e in hierarchy):
                reasons.append('missing_leaf_entity')
            native = json.loads(s['item_key'])
            if native.get('basis') == 'native_id' and native.get('native_id') != raw.get('source_listing_id'):
                reasons.append('native_identity_mismatch')
        if reasons:
            excluded.append({'id': lid, 'reasons': reasons})
        else:
            valid.append((row, gs[0]))
    # Uniform, repeatable rank over gold-eligible observations; selection uses no label values.
    if exclude_reference:
        valid = [pair for pair in valid if pair[0]['id'] not in original]
    salt = 'food-scale-v1|' if seed is None else f'food-random-v1|{seed}|'
    valid.sort(key=lambda pair: hashlib.sha256((salt+pair[0]['id']).encode()).hexdigest())
    if len(valid) < size:
        raise ValueError(f'Only {len(valid)} verified gold rows available for requested {size}')
    chosen = valid[:size]
    dump_rows(output/'source-snapshot.jsonl', [r for r, _ in chosen])
    write(output/'gold-rulings.json', [{'observation_id': r['id'], 'gold_original': [g], 'systems': {}}
                                         for r, g in chosen])
    for name in ('frozen_scorer.py', 'frozen-aliases.tsv', 'frozen-brands.parquet', 'scorer-reference-inputs.json'):
        shutil.copyfile(reference/name, output/name)
    ids = [r['id'] for r, _ in chosen]
    feedback_n = min(20 if size <= 100 else 100, size)
    old.update(source=fingerprint(output/'source-snapshot.jsonl'),
               gold_rulings=fingerprint(output/'gold-rulings.json'), primary_denominator=size,
               partition={'feedback_ids': ids[:feedback_n], 'withheld_feedback_ids': ids[feedback_n:],
                          'method': f'fixed hash rank; first{feedback_n} feedback',
                          'caveat': 'Development sample, not brand-sealed gold; overlap recorded'},
               parallel_batches=5, calls_per_cycle_max=(size+9)//10,
               selection=f'sha256({salt}id) rank among verified gold observations',
               deadline_utc=None, stop_policy='one expanded-sample reference run, then reassess')
    write(output/'protocol.json', old)
    write(output/'selection.json', {'size': size, 'eligible': len(valid), 'excluded': len(excluded),
        'seed': seed, 'exclude_reference': exclude_reference,
        'overlap_original50': [lid for lid in ids if lid in original], 'source': fingerprint(raw_path),
        'gold': fingerprint(gold_path), 'selection': fingerprint(selection_path),
        'owner_authority': old['owner_authority'], 'sealed': False})
    write(output/'join-exclusions.json', excluded)
    return output


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--labeled', type=Path, required=True)
    ap.add_argument('--size', type=int, default=500)
    ap.add_argument('--seed', type=int)
    ap.add_argument('--exclude-reference', action='store_true')
    a = ap.parse_args()
    prepare(a.reference, a.output, a.labeled, a.size, a.seed, a.exclude_reference)
