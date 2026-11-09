"""Write parallel Gold sidecars: exact Silver ID plus current Pedia identity values."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


PATH_TYPE = pa.list_(pa.struct([('label', pa.string()), ('level', pa.string()), ('node_id', pa.string())]))
ENTITY_TYPE = pa.list_(pa.struct([('entity_id', pa.string()), ('label', pa.string()),
    ('level', pa.string()), ('type', pa.string()), ('node_id', pa.string()), ('depth', pa.int64())]))
FIELDS = [
    *[(n, pa.string()) for n in ('pedia_label_source', 'pedia_release', 'pedia_release_sha256',
       'pedia_graph_manifest_sha256', 'pedia_mention_id', 'pedia_entity_id', 'pedia_node_id',
       'pedia_name', 'pedia_entity_type', 'pedia_entity_status', 'pedia_brand_key',
       'pedia_brand', 'pedia_brand_id', 'pedia_model', 'pedia_model_id', 'pedia_variant',
       'pedia_variant_id', 'pedia_placement_level', 'pedia_placement_outcome', 'pedia_join_method',
       'pedia_path_json', 'pedia_confidence_band', 'pedia_conflict_id')],
    *[(n, pa.list_(pa.string())) for n in ('pedia_sub_brand_path', 'pedia_family_path',
       'pedia_model_path', 'pedia_variant_path', 'pedia_matched_mention_ids', 'pedia_flags', 'pedia_rule_ids')],
    ('pedia_full_path', PATH_TYPE), ('pedia_entity_hierarchy', ENTITY_TYPE),
    ('pedia_confidence', pa.float64()),
]


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def match(con, raw, idcol, selection):
    con.register('raw_keys', raw.select([idcol, 'source_id', 'listing_key']))
    con.execute(f'CREATE OR REPLACE TEMP TABLE s AS SELECT {idcol} AS silver_id,source_id,listing_key FROM raw_keys')
    con.execute('''CREATE OR REPLACE TEMP TABLE links AS SELECT s.silver_id,p.mention_id,
        'observation_id' AS join_method FROM s JOIN graph.placement p
        ON try_cast(substr(p.mention_id,5) AS BIGINT)=s.silver_id AND p.source_id=s.source_id''')
    con.execute('''INSERT INTO links SELECT DISTINCT s.silver_id,p.mention_id,'verified_identity_bridge'
        FROM graph.placement p JOIN legacy m ON m.mention_id=try_cast(substr(p.mention_id,5) AS BIGINT)
        JOIN s ON s.silver_id=m.silver_id AND s.source_id=m.source_id AND s.listing_key=m.listing_key
        WHERE p.source_id=s.source_id AND NOT EXISTS(SELECT 1 FROM links l WHERE l.mention_id=p.mention_id)''')
    con.execute('''CREATE OR REPLACE TEMP TABLE matched AS SELECT DISTINCT l.*,p.entity_id,p.brand,
        p.node_id,p.level,p.outcome,p.path,p.flags,p.rule_ids,p.confidence,p.confidence_band,p.conflict_id,
        e.type AS entity_type,e.label AS entity_label,e.status AS entity_status
        FROM links l JOIN graph.placement p USING(mention_id)
        JOIN graph.entity e ON e.entity_id=p.entity_id AND e.brand=p.brand
        WHERE p.outcome IS DISTINCT FROM 'unplaced' AND e.deprecated_to IS NULL''')
    con.execute('''CREATE OR REPLACE TEMP TABLE ambiguous AS SELECT silver_id FROM matched
        GROUP BY 1 HAVING count(DISTINCT entity_id)>1''')
    # Reuse the raw sample's original representative when the same entity has several mentions.
    if selection is not None:
        preferred = selection.select(['silver_id', 'mention_id'])
    else:
        preferred = pa.table({'silver_id': pa.array([], type=pa.int64()), 'mention_id': pa.array([], type=pa.string())})
    con.register('preferred', preferred)
    con.execute('''CREATE OR REPLACE TEMP TABLE chosen AS SELECT m.* FROM matched m
        LEFT JOIN preferred p ON p.silver_id=m.silver_id AND p.mention_id=m.mention_id
        WHERE m.silver_id NOT IN (SELECT silver_id FROM ambiguous)
        QUALIFY row_number() OVER(PARTITION BY m.silver_id ORDER BY
            (p.silver_id IS NOT NULL) DESC,(m.join_method='observation_id') DESC,m.mention_id)=1''')
    chosen = con.sql('SELECT * FROM chosen ORDER BY silver_id').to_arrow_table().to_pylist()
    ancestors = con.sql('''SELECT DISTINCT c.silver_id,e.entity_id,e.label,e.level,e.type,e.node_id,a.depth
        FROM chosen c JOIN graph.ancestor a ON a.entity_id=c.entity_id
        JOIN graph.entity e ON e.entity_id=a.ancestor_id AND e.brand=c.brand
        WHERE e.deprecated_to IS NULL
        UNION SELECT c.silver_id,c.entity_id,c.entity_label,c.level,c.entity_type,c.node_id,0 FROM chosen c
        ORDER BY silver_id,depth DESC,entity_id''').to_arrow_table().to_pylist()
    hierarchy = defaultdict(list)
    for record in ancestors:
        hierarchy[record.pop('silver_id')].append(record)
    mentions = defaultdict(set)
    for record in con.sql('SELECT DISTINCT silver_id,mention_id FROM matched').to_arrow_table().to_pylist():
        mentions[record['silver_id']].add(record['mention_id'])
    exclusions = con.sql('''SELECT s.silver_id,s.source_id,CASE
        WHEN s.silver_id IN (SELECT silver_id FROM ambiguous) THEN 'ambiguous_entity'
        WHEN s.silver_id IN (SELECT silver_id FROM links) THEN 'no_active_placement'
        ELSE 'no_pedia_placement' END AS reason
        FROM s ANTI JOIN chosen USING(silver_id) ORDER BY silver_id''').to_arrow_table()
    con.unregister('raw_keys')
    con.unregister('preferred')
    return chosen, hierarchy, mentions, exclusions


def annotation(record, hierarchy, mentions, release):
    path = json.loads(record['path']) if record['path'] else []
    path = [{'label': step[0], 'level': step[1], 'node_id': step[2] if len(step)>2 else None} for step in path]
    def names(*levels):
        return [step['label'] for step in path if step['level'] in levels]
    def nearest(*levels):
        candidates = [e for e in hierarchy if e['level'] in levels]
        if not candidates:
            return None
        depth = min(e['depth'] for e in candidates)
        nearest = [e for e in candidates if e['depth'] == depth]
        return nearest[0] if len(nearest) == 1 else None
    brand, model, variant = nearest('brand'), nearest('model','product'), nearest('variant')
    return {
        'pedia_label_source': 'pedia', 'pedia_release': release['id'],
        'pedia_release_sha256': release['sha256'],
        'pedia_graph_manifest_sha256': release['layers']['graph']['manifest_sha256'],
        'pedia_mention_id': record['mention_id'], 'pedia_entity_id': record['entity_id'],
        'pedia_node_id': record['node_id'], 'pedia_name': record['entity_label'],
        'pedia_entity_type': record['entity_type'], 'pedia_entity_status': record['entity_status'],
        'pedia_brand_key': record['brand'],
        'pedia_brand': brand['label'] if brand else next(iter(names('brand')), None),
        'pedia_brand_id': brand['entity_id'] if brand else None,
        'pedia_model': model['label'] if model else None, 'pedia_model_id': model['entity_id'] if model else None,
        'pedia_variant': variant['label'] if variant else None, 'pedia_variant_id': variant['entity_id'] if variant else None,
        'pedia_sub_brand_path': names('sub_brand'), 'pedia_family_path': names('family'),
        'pedia_model_path': names('model','product'), 'pedia_variant_path': names('variant'),
        'pedia_full_path': path, 'pedia_path_json': record['path'], 'pedia_entity_hierarchy': hierarchy,
        'pedia_placement_level': record['level'], 'pedia_placement_outcome': record['outcome'],
        'pedia_join_method': record['join_method'], 'pedia_matched_mention_ids': sorted(mentions),
        'pedia_flags': record['flags'], 'pedia_rule_ids': record['rule_ids'],
        'pedia_confidence': record['confidence'], 'pedia_confidence_band': record['confidence_band'],
        'pedia_conflict_id': record['conflict_id'],
    }


def extract(domain, entry, release, pedia, sources, root, output):
    idcol = 'observation_key' if domain == 'food' else 'source_record_key'
    if sha(entry['legacy_bridge']) != entry['legacy_bridge_sha256']:
        raise ValueError('Historical identity bridge checksum differs')
    reports, seen_ids = [], set()
    with duckdb.connect(config={'threads': 2, 'memory_limit': '1GB'}) as con:
        graph = pedia / release['layers']['graph']['path'] / 'construct/built.duckdb'
        con.execute('ATTACH ? AS graph (READ_ONLY)', [str(graph)])
        con.execute('CREATE TEMP TABLE legacy AS SELECT * FROM read_parquet(?)', [entry['legacy_bridge']])
        for source in sources:
            raw = pq.read_table(source, columns=[idcol, 'source_id', 'listing_key'])
            ids = raw[idcol].to_pylist()
            if len(ids) != len(set(ids)) or None in ids:
                raise ValueError(f'{source}: Silver IDs are null or repeated')
            if seen_ids.intersection(ids):
                raise ValueError(f'{source}: raw subsets overlap in Silver IDs')
            seen_ids.update(ids)
            selection_path = source.parent / 'selection.parquet'
            selection = pq.read_table(selection_path) if selection_path.exists() else None
            chosen, hierarchy, mentions, exclusions = match(con, raw, idcol, selection)
            by_id = {r['silver_id']: annotation(r, hierarchy[r['silver_id']], mentions[r['silver_id']], release) for r in chosen}
            mask = pc.is_in(raw[idcol], value_set=pa.array(sorted(by_id), type=pa.int64()))
            matched_ids = raw[idcol].filter(mask)
            labeled = pa.table({'silver_id': matched_ids})
            annotations = [by_id[i] for i in matched_ids.to_pylist()]
            for name, dtype in FIELDS:
                labeled = labeled.append_column(name, pa.array([r[name] for r in annotations], type=dtype))
            destination = output / source.parent.relative_to(root)
            destination.mkdir(parents=True)
            full = destination / 'gold.parquet'
            pq.write_table(labeled, full, compression='zstd')
            report = {
                'format': 'pedia_gold_sidecar/v1', 'domain': domain,
                'input': str(source.relative_to(root)), 'input_sha256': sha(source),
                'input_rows': raw.num_rows, 'labeled_rows': labeled.num_rows,
                'unlabeled_rows': exclusions.num_rows, 'unlabeled_reasons': dict(Counter(exclusions['reason'].to_pylist())),
                'silver_id_column': idcol, 'gold_id_column': 'silver_id',
                'input_distinct_ids': len(ids), 'overlap_with_previous_raw_subsets': 0,
                'gold_columns': labeled.column_names,
                'label_columns': [n for n,t in FIELDS], 'pedia_release': release['id'],
                'pedia_release_sha256': release['sha256'],
                'pedia_graph_manifest_sha256': release['layers']['graph']['manifest_sha256'],
                'legacy_bridge_sha256': entry['legacy_bridge_sha256'],
                'selection_sha256': sha(selection_path) if selection is not None else None,
                'label_source': 'pedia', 'gold_assumption': 'Pedia current identity assignments are the project reference labels.',
                'placement_level_counts': dict(Counter(labeled['pedia_placement_level'].to_pylist())),
                'join_method_counts': dict(Counter(labeled['pedia_join_method'].to_pylist())),
                'output': full.name, 'output_sha256': sha(full),
            }
            (destination / 'manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            reports.append(report)
            print(json.dumps({k:report[k] for k in ('domain','input','input_rows','labeled_rows','unlabeled_rows')}), flush=True)
    return reports


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--subsets', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--domain', choices=['food','fragrance','both'], default='both')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Choose a new output directory')
    config = json.loads(args.sources.read_text('utf-8-sig'))
    pedia = Path(config['pedia_root'])
    releases = json.loads((pedia / 'CURRENT.json').read_text())['releases']
    reports = {}
    for domain in (('food','fragrance') if args.domain == 'both' else (args.domain,)):
        sources = sorted(args.subsets.rglob(f'{domain}_listings.parquet'))
        if not sources:
            raise FileNotFoundError(f'No raw {domain} subsets found under {args.subsets}')
        reports[domain] = extract(domain, config['domains'][domain], releases[domain], pedia,
                                  sources, args.subsets, args.out)
    (args.out / 'report.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
