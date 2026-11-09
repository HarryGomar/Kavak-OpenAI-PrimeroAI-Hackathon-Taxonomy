"""Select diverse Pedia-linked listings; export unchanged, full-schema Silver rows."""
import argparse
from collections import defaultdict, deque
import hashlib
import json
import re
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

FOCUS_BRANDS = {
    'lattafa', 'armaf', 'afnan', 'rasasi', 'al_haramain', 'ajmal', 'swiss_arabian',
    'maison_alhambra', 'khadlaj', 'al_rehab', 'arabian_oud', 'abdul_samad_al_qurashi',
    'nabeel', 'fragrance_world', 'french_avenue', 'paris_corner', 'orientica', 'zimaya',
    'ahmed_al_maghribi', 'ard_al_zaafaran', 'maison_asrar',
}


def digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def take_balanced(rows, count, seed, brand_limit):
    """Round-robin brands and short model groups, spreading variants and sources."""
    by_brand = defaultdict(lambda: defaultdict(list))
    for row in rows:
        by_brand[row['brand'] or '__unplaced__'][row['model_id'] or row['entity_id']].append(row)
    queues, brand_sources = {}, {}
    for brand, models in by_brand.items():
        packets = []
        brand_sources[brand] = {r['source_id'] for group in models.values() for r in group}
        for model, group in models.items():
            buckets = defaultdict(deque)
            for row in sorted(group, key=lambda r: digest((seed, r['item_key']))):
                buckets[(row['entity_id'], row['source_id'])].append(row)
            keys = sorted(buckets, key=lambda k: digest((seed, model, k)))
            spread = []
            while any(buckets.values()):
                for key in keys:
                    if buckets[key]:
                        spread.append(buckets[key].popleft())
            priority = (len({r['entity_id'] for r in group}) > 1,
                        len({r['source_id'] for r in group}) > 1, len(group) > 1)
            packets.append((priority, digest((seed, model)), spread))
        packets.sort(key=lambda p: (tuple(-int(v) for v in p[0]), p[1]))
        # First retain short related groups, then any remaining listings if needed.
        queues[brand] = deque([p[2][:8] for p in packets] + [p[2][8:] for p in packets if len(p[2]) > 8])
    remaining = set(queues)
    ordered, covered = [], set()
    while remaining:
        brand = min(remaining, key=lambda b: (-len(brand_sources[b] - covered), digest((seed, b))))
        ordered.append(brand)
        covered.update(brand_sources[brand])
        remaining.remove(brand)
        if len(ordered) >= brand_limit:
            break
    capacity = sum(sum(len(p) for p in queues[b]) for b in ordered)
    for brand in sorted(remaining, key=lambda b: digest((seed, b))):
        if capacity >= count:
            break
        ordered.append(brand)
        capacity += sum(len(p) for p in queues[brand])
    picked = []
    while len(picked) < count:
        progressed = False
        for brand in ordered:
            if queues[brand]:
                picked.extend(queues[brand].popleft()[:count - len(picked)])
                progressed = True
            if len(picked) == count:
                break
        if not progressed:
            break
    return picked


def sample(rows, count, seed, brands):
    core = [r for r in rows if r['model_id'] is not None]
    other = [r for r in rows if r['model_id'] is None]
    extras = take_balanced(other, min(round(count * .05), len(other)), seed, brands)
    return extras + take_balanced(core, count - len(extras), seed, brands)


def include_required_groups(rows, picked, groups, seed):
    required, counts, used = [], {}, set()
    for group in groups:
        eligible = [r for r in rows if r['item_key'] not in used
                    and r['brand'] in group['pedia_brands']
                    and re.search(group['title_regex'], r['listing_name'] or '', re.I)
                    and not re.search(group.get('exclude_title_regex', r'(?!)'), r['listing_name'] or '', re.I)]
        chosen = take_balanced(eligible, group['count'], seed, 10)
        if len(chosen) != group['count']:
            raise ValueError(f"Required group {group['name']}: only {len(chosen)} eligible listings")
        required.extend(chosen)
        used.update(r['item_key'] for r in chosen)
        counts[group['name']] = len(chosen)
    existing = {r['item_key'] for r in picked}
    additions = [r for r in required if r['item_key'] not in existing]
    # Preserve the previous seeded sample except for the slots needed by new rows.
    keep = list(picked)
    remaining = len(additions)
    for position in range(len(keep)-1, -1, -1):
        if remaining == 0:
            break
        if keep[position]['item_key'] not in used:
            keep.pop(position)
            remaining -= 1
    if remaining:
        raise ValueError('Required listing groups exceed the requested sample size')
    return keep + additions, counts


def extract(domain, config, release, pedia, destination, size, seed, brands, focus_fraction):
    con = duckdb.connect(config={'threads': 2, 'memory_limit': '2GB'})
    graph = pedia / release['layers']['graph']['path'] / 'construct/built.duckdb'
    con.execute('ATTACH ? AS graph (READ_ONLY)', [str(graph)])
    idcol = 'observation_key' if domain == 'food' else 'source_record_key'
    statuscol, allowed_status = ('food_scope_status', 'confirmed') if domain == 'food' else ('perfume_status', 'included')
    con.execute(f'CREATE TEMP TABLE silver AS SELECT {idcol} AS id,source_id,_scope AS assembly,listing_key,market,observed_at,listing_name FROM read_parquet(?) WHERE {statuscol}=?', [config['silver'], allowed_status])
    con.execute("CREATE TEMP TABLE p AS SELECT *,try_cast(substr(mention_id,5) AS BIGINT) AS observation_id FROM graph.placement WHERE outcome IS DISTINCT FROM 'unplaced'")
    con.execute("CREATE TEMP TABLE links AS SELECT p.mention_id,s.id AS silver_id,'observation_id' AS join_method FROM p JOIN silver s ON s.id=p.observation_id AND s.source_id=p.source_id")
    bridge = Path(config['legacy_bridge'])
    if hashlib.sha256(bridge.read_bytes()).hexdigest() != config['legacy_bridge_sha256']:
        raise ValueError('Historical identity bridge checksum differs')
    con.execute('CREATE TEMP TABLE legacy AS SELECT * FROM read_parquet(?)', [str(bridge)])
    con.execute("INSERT INTO links SELECT p.mention_id,s.id,'verified_identity_bridge' FROM p JOIN legacy m ON m.mention_id=p.observation_id JOIN silver s ON s.id=m.silver_id AND s.source_id=m.source_id AND s.listing_key=m.listing_key WHERE NOT EXISTS(SELECT 1 FROM links l WHERE l.mention_id=p.mention_id)")
    con.execute('CREATE TEMP TABLE native AS SELECT DISTINCT id,assembly,source_id,item_key FROM read_parquet(?)', [config['native_bridge']])
    con.execute("CREATE TEMP TABLE model_candidates AS SELECT p.mention_id,e.entity_id AS model_id,0 AS depth FROM p JOIN graph.entity e ON e.entity_id=p.entity_id AND e.brand=p.brand WHERE e.type='ProductModel' AND e.deprecated_to IS NULL UNION ALL SELECT p.mention_id,m.entity_id,a.depth FROM p JOIN graph.entity e ON e.entity_id=p.entity_id AND e.brand=p.brand JOIN graph.ancestor a ON a.entity_id=e.entity_id JOIN graph.entity m ON m.entity_id=a.ancestor_id AND m.brand=p.brand WHERE e.type='ProductVariant' AND m.type='ProductModel' AND e.deprecated_to IS NULL AND m.deprecated_to IS NULL")
    con.execute('CREATE TEMP TABLE nearest AS SELECT DISTINCT mention_id,model_id FROM model_candidates QUALIFY depth=min(depth) OVER(PARTITION BY mention_id)')
    con.execute('CREATE TEMP TABLE models AS SELECT mention_id,min(model_id) AS model_id FROM nearest GROUP BY 1 HAVING count(*)=1')
    con.execute("CREATE TEMP TABLE joined AS SELECT b.item_key,l.silver_id,p.mention_id,p.entity_id,p.brand,p.level,p.outcome,e.type AS entity_type,m.model_id,s.source_id,s.market,s.observed_at,s.listing_name,l.join_method FROM links l JOIN p USING(mention_id) JOIN silver s ON s.id=l.silver_id JOIN native b ON b.id=s.id AND b.assembly=s.assembly AND b.source_id=s.source_id JOIN graph.entity e ON e.entity_id=p.entity_id AND e.brand=p.brand LEFT JOIN models m USING(mention_id) WHERE b.item_key IS NOT NULL AND e.deprecated_to IS NULL")
    conflicts = con.execute('SELECT count(*) FROM (SELECT item_key FROM joined GROUP BY 1 HAVING count(DISTINCT entity_id)>1)').fetchone()[0]
    con.execute('CREATE TEMP TABLE candidates AS SELECT * EXCLUDE(observed_at) FROM joined WHERE item_key NOT IN (SELECT item_key FROM joined GROUP BY 1 HAVING count(DISTINCT entity_id)>1) QUALIFY row_number() OVER(PARTITION BY item_key ORDER BY observed_at DESC NULLS LAST,silver_id,mention_id)=1')
    cur = con.execute('SELECT * FROM candidates ORDER BY item_key')
    columns = [c[0] for c in cur.description]
    rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    if len(rows) < size:
        raise ValueError(f'{domain}: only {len(rows)} eligible unique listings, requested {size}')
    if domain == 'fragrance':
        focus = [r for r in rows if r['brand'] in FOCUS_BRANDS]
        rest = [r for r in rows if r['brand'] not in FOCUS_BRANDS]
        focus_count = round(size * focus_fraction)
        if len(focus) < focus_count or len(rest) < size - focus_count:
            raise ValueError('Insufficient listings for requested fragrance focus fraction')
        picked = sample(focus, focus_count, seed, max(10, round(brands * focus_fraction)))
        picked += sample(rest, size - focus_count, seed, max(10, round(brands * (1-focus_fraction))))
    else:
        picked = sample(rows, size, seed, brands)
    picked, required_counts = include_required_groups(rows, picked, config.get('required_groups', []), seed)
    if len(picked) != size:
        raise ValueError(f'{domain}: sampling could only fill {len(picked)} rows')
    matched = con.execute('SELECT count(DISTINCT mention_id) FROM links').fetchone()[0]
    total = con.execute('SELECT count(*) FROM p').fetchone()[0]
    con.close()
    destination.mkdir(parents=True, exist_ok=False)
    parquet = destination/f'{domain}_listings.parquet'
    # Stream wide evidence: joining/sorting every Silver column can decode gigabytes.
    source = pq.ParquetFile(config['silver'])
    wanted = pa.array([r['silver_id'] for r in picked], type=pa.int64())
    pending, pending_rows, written = [], 0, 0
    with pq.ParquetWriter(parquet, source.schema_arrow, compression='zstd') as writer:
        for batch in source.iter_batches(batch_size=128, use_threads=False):
            mask = pc.is_in(batch.column(batch.schema.get_field_index(idcol)), value_set=wanted)
            kept = batch.filter(mask)
            if kept.num_rows:
                pending.append(pa.Table.from_batches([kept]))
                pending_rows += kept.num_rows
            if pending_rows >= 512:
                writer.write_table(pa.concat_tables(pending))
                written += pending_rows
                pending, pending_rows = [], 0
        if pending_rows:
            writer.write_table(pa.concat_tables(pending))
            written += pending_rows
    if written != size:
        raise ValueError(f'Exported {written} Silver rows, expected {size}')
    model_groups, brand_models = defaultdict(list), defaultdict(set)
    for row in picked:
        if row['model_id'] is not None:
            model_groups[row['model_id']].append(row)
            brand_models[row['brand']].add(row['model_id'])
    summary = {
        'format': 'pedia_guided_silver_subset/v1', 'domain': domain, 'rows': size,
        'all_silver_columns_preserved': True, 'seed': seed, 'requested_brands': brands,
        'classification_column': statuscol, 'allowed_classifications': [allowed_status],
        'required_listing_groups': required_counts,
        'selected_pedia_linked_listings': len(picked), 'unplaced_pedia_outcomes_allowed': False,
        'pedia_release': release['id'], 'pedia_release_sha256': release['sha256'],
        'graph_manifest_sha256': release['layers']['graph']['manifest_sha256'],
        'silver_source': config.get('original_silver', config['silver']), 'silver_snapshot': config.get('silver_snapshot'),
        'eligible_native_listings': len(rows), 'matched_pedia_mentions': matched,
        'unmatched_pedia_mentions': total-matched, 'conflicting_native_listings_excluded': conflicts,
        'brands': len({r['brand'] for r in picked if r['brand']}),
        'sources': len({r['source_id'] for r in picked}),
        'models': len(model_groups), 'other_identity_outcomes': sum(r['model_id'] is None for r in picked),
        'focus_listings': sum(r['brand'] in FOCUS_BRANDS for r in picked) if domain == 'fragrance' else 0,
        'focus_brands': len({r['brand'] for r in picked if r['brand'] in FOCUS_BRANDS}) if domain == 'fragrance' else 0,
        'focus_brand_allowlist': sorted(FOCUS_BRANDS) if domain == 'fragrance' else [],
        'relationships': {
            'models_with_multiple_listings': sum(len(g)>1 for g in model_groups.values()),
            'models_with_multiple_sources': sum(len({r['source_id'] for r in g})>1 for g in model_groups.values()),
            'models_with_sibling_variants': sum(len({r['entity_id'] for r in g if r['entity_type']=='ProductVariant'})>1 for g in model_groups.values()),
            'brands_with_multiple_models': sum(len(g)>1 for g in brand_models.values()),
        },
        'selection_sha256': digest(json.dumps(sorted((r['item_key'],r['silver_id'],r['entity_id']) for r in picked))),
        'annotations': 'Pedia placements are source annotations, not independently established ground truth.',
    }
    (destination/'manifest.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--size', type=int, default=5000, help='Unique native source listings per domain')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument('--brands', type=int, default=80)
    parser.add_argument('--focus-fraction', type=float, default=.2, help='Fragrance share from explicit focus brands')
    parser.add_argument('--domain', choices=['food', 'fragrance', 'both'], default='both')
    args = parser.parse_args()
    if args.size <= 0 or args.brands <= 0 or not 0 < args.focus_fraction < 1:
        parser.error('size and brands must be positive; focus-fraction must be between 0 and 1')
    if args.out.exists():
        parser.error('Output exists; choose a new directory to preserve earlier samples')
    config = json.loads(args.sources.read_text('utf-8-sig'))
    pedia = Path(config['pedia_root'])
    releases = json.loads((pedia/'CURRENT.json').read_text())['releases']
    for domain in (('food', 'fragrance') if args.domain == 'both' else (args.domain,)):
        extract(domain, config['domains'][domain], releases[domain], pedia,
                args.out/domain, args.size, args.seed, args.brands, args.focus_fraction)


if __name__ == '__main__':
    main()
