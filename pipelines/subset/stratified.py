"""Extract two additional local Silver subsets with exact Gold/Pedia quotas."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from subset import take_balanced, FOCUS_BRANDS

QUOTAS = {'gold': 2000, 'pedia_without_gold': 2900, 'outside_pedia': 100}
def q(value):
    return "'" + str(value).replace("'", "''") + "'"
def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
def records(con, sql):
    return con.sql(sql).to_arrow_table().to_pylist()

def prepare_candidates(con, domain, config, release, pedia):
    """Snapshot of the existing extractor's narrow identity selection, outside its export."""
    graph = pedia / release['layers']['graph']['path'] / 'construct/built.duckdb'
    con.execute('ATTACH ? AS graph (READ_ONLY)', [str(graph)])
    idcol = 'observation_key' if domain == 'food' else 'source_record_key'
    statuscol, allowed = ('food_scope_status','confirmed') if domain == 'food' else ('perfume_status','included')
    con.execute(f'CREATE TEMP TABLE silver AS SELECT {idcol} AS id,source_id,_scope AS assembly,listing_key,market,observed_at,listing_name FROM read_parquet(?) WHERE {statuscol}=?', [config['silver'], allowed])
    con.execute("CREATE TEMP TABLE p AS SELECT *,try_cast(substr(mention_id,5) AS BIGINT) AS observation_id FROM graph.placement WHERE outcome IS DISTINCT FROM 'unplaced'")
    con.execute("CREATE TEMP TABLE links AS SELECT p.mention_id,s.id AS silver_id,'observation_id' AS join_method FROM p JOIN silver s ON s.id=p.observation_id AND s.source_id=p.source_id")
    assert sha(config['legacy_bridge']) == config['legacy_bridge_sha256']
    con.execute('CREATE TEMP TABLE legacy AS SELECT * FROM read_parquet(?)', [config['legacy_bridge']])
    con.execute("INSERT INTO links SELECT p.mention_id,s.id,'verified_identity_bridge' FROM p JOIN legacy m ON m.mention_id=p.observation_id JOIN silver s ON s.id=m.silver_id AND s.source_id=m.source_id AND s.listing_key=m.listing_key WHERE NOT EXISTS(SELECT 1 FROM links l WHERE l.mention_id=p.mention_id)")
    con.execute('CREATE TEMP TABLE native AS SELECT DISTINCT id,assembly,source_id,item_key FROM read_parquet(?)', [config['native_bridge']])
    con.execute("CREATE TEMP TABLE model_candidates AS SELECT p.mention_id,e.entity_id AS model_id,0 AS depth FROM p JOIN graph.entity e ON e.entity_id=p.entity_id AND e.brand=p.brand WHERE e.type='ProductModel' AND e.deprecated_to IS NULL UNION ALL SELECT p.mention_id,m.entity_id,a.depth FROM p JOIN graph.entity e ON e.entity_id=p.entity_id AND e.brand=p.brand JOIN graph.ancestor a ON a.entity_id=e.entity_id JOIN graph.entity m ON m.entity_id=a.ancestor_id AND m.brand=p.brand WHERE e.type='ProductVariant' AND m.type='ProductModel' AND e.deprecated_to IS NULL AND m.deprecated_to IS NULL")
    con.execute('CREATE TEMP TABLE nearest AS SELECT DISTINCT mention_id,model_id FROM model_candidates QUALIFY depth=min(depth) OVER(PARTITION BY mention_id)')
    con.execute('CREATE TEMP TABLE models AS SELECT mention_id,min(model_id) AS model_id FROM nearest GROUP BY 1 HAVING count(*)=1')
    con.execute("CREATE TEMP TABLE joined AS SELECT b.item_key,l.silver_id,p.mention_id,p.entity_id,p.brand,p.level,p.outcome,e.type AS entity_type,m.model_id,s.source_id,s.market,s.observed_at,s.listing_name,l.join_method FROM links l JOIN p USING(mention_id) JOIN silver s ON s.id=l.silver_id JOIN native b ON b.id=s.id AND b.assembly=s.assembly AND b.source_id=s.source_id JOIN graph.entity e ON e.entity_id=p.entity_id AND e.brand=p.brand LEFT JOIN models m USING(mention_id) WHERE b.item_key IS NOT NULL AND e.deprecated_to IS NULL")
    conflicts = con.execute('SELECT count(*) FROM (SELECT item_key FROM joined GROUP BY 1 HAVING count(DISTINCT entity_id)>1)').fetchall()[0][0]
    con.execute('CREATE TEMP TABLE candidates AS SELECT * EXCLUDE(observed_at) FROM joined WHERE item_key NOT IN (SELECT item_key FROM joined GROUP BY 1 HAVING count(DISTINCT entity_id)>1) QUALIFY row_number() OVER(PARTITION BY item_key ORDER BY observed_at DESC NULLS LAST,silver_id,mention_id)=1')
    return conflicts

def gold_memberships(con, domain, entry):
    """Return exact source Silver IDs and original product/hierarchy membership."""
    queries = []
    for view, paths in entry['views'].items():
        label_path = Path(paths['labels'])
        labels = f'read_parquet({q(label_path)})'
        assert sha(label_path) == paths['labels_sha256']
        assign_path = Path(paths['assignments'])
        assigns = f'read_parquet({q(assign_path)})'
        lhs = set(con.execute(f'SELECT distinct hierarchy_id FROM {labels}').fetchall())
        rhs = set(con.execute(f'SELECT distinct hierarchy_id FROM {assigns}').fetchall())
        assert lhs == rhs, (domain, view, 'hierarchy differs')
        if view == 'listing':
            base = f'SELECT s.id AS silver_id,s.source_id,NULL::BIGINT AS product_key,a.hierarchy_id,a.cluster_id,a.level FROM silver s JOIN {assigns} a ON s.id=a.id'
        else:
            base = f'''SELECT s.id AS silver_id,s.source_id,p.product_key,a.hierarchy_id,a.cluster_id,a.level
                FROM silver s JOIN read_parquet({q(paths['members'])}) m
                ON s.id=m.silver_id AND s.source_id=m.source_id
                JOIN read_parquet({q(paths['products'])}) p USING(product_id)
                JOIN {assigns} a ON a.product_key=p.product_key'''
        queries.append(f'''SELECT {q(view)} AS view,m.*,l.label,l.description,l.review_disposition
            FROM ({base}) m JOIN {labels} l USING(hierarchy_id,cluster_id)
            QUALIFY m.level=max(m.level) OVER(PARTITION BY m.silver_id,m.source_id,m.product_key)''')
    con.execute('CREATE TEMP TABLE gold_labels AS ' + ' UNION ALL '.join('(' + x + ')' for x in queries))
    con.execute('CREATE TEMP TABLE gold_ids AS SELECT distinct silver_id,source_id FROM gold_labels')

def choose(rows, count, domain, seed):
    if domain == 'fragrance':
        focus = [r for r in rows if r['brand'] in FOCUS_BRANDS]
        rest = [r for r in rows if r['brand'] not in FOCUS_BRANDS]
        n = min(round(count * .2), len(focus))
        n = max(n, count - len(rest))
        return take_balanced(focus, n, seed, max(10, round(n / 20))) + take_balanced(rest, count-n, seed, 100)
    return take_balanced(rows, count, seed, 100)

def build(domain, config, release, gold_entry, pedia, destination, prior_paths, seed, plan_only):
    idcol = 'observation_key' if domain == 'food' else 'source_record_key'
    statuscol, allowed = ('food_scope_status', 'confirmed') if domain == 'food' else ('perfume_status', 'included')
    with duckdb.connect(config={'threads': 2, 'memory_limit': '2GB', 'preserve_insertion_order': False}) as con:
        conflicts = prepare_candidates(con, domain, config, release, pedia)
        prior_queries = [f'SELECT {idcol} AS id FROM read_parquet({q(path)})' for path in prior_paths]
        con.execute('CREATE TEMP TABLE old_ids AS ' + (' UNION '.join(prior_queries) or 'SELECT NULL::BIGINT AS id WHERE false'))
        con.execute('CREATE TEMP TABLE old_items AS SELECT DISTINCT item_key FROM native JOIN old_ids USING(id)')
        # Include unplaced outcomes in the absence check. A known but unplaced listing is not outside Pedia.
        con.execute("CREATE TEMP TABLE all_placements AS SELECT *,try_cast(substr(mention_id,5) AS BIGINT) AS observation_id FROM graph.placement")
        con.execute('''CREATE TEMP TABLE all_links AS
            SELECT p.mention_id,s.id AS silver_id FROM all_placements p JOIN silver s ON p.observation_id=s.id AND p.source_id=s.source_id
            UNION SELECT p.mention_id,s.id FROM all_placements p JOIN legacy m ON m.mention_id=p.observation_id
            JOIN silver s ON s.id=m.silver_id AND s.source_id=m.source_id AND s.listing_key=m.listing_key''')
        con.execute('CREATE TEMP TABLE pedia_items AS SELECT DISTINCT n.item_key FROM all_links p JOIN native n ON p.silver_id=n.id')
        gold_memberships(con, domain, gold_entry)
        con.execute('''CREATE TEMP TABLE inside AS SELECT c.*,g.silver_id IS NOT NULL AS gold_covered
            FROM candidates c LEFT JOIN gold_ids g ON c.silver_id=g.silver_id AND c.source_id=g.source_id
            WHERE c.silver_id NOT IN (SELECT id FROM old_ids) AND c.item_key NOT IN (SELECT item_key FROM old_items)''')
        # Source brand is used only to spread outside examples; no Pedia entity is invented.
        con.execute(f'''CREATE TEMP TABLE outside AS SELECT n.item_key,s.id AS silver_id,s.source_id,s.market,s.listing_name,
            lower(trim(b.brand_name)) AS brand,NULL::VARCHAR AS model_id,NULL::VARCHAR AS entity_id,
            NULL::VARCHAR AS entity_type,NULL::VARCHAR AS mention_id,NULL::VARCHAR AS level,NULL::VARCHAR AS outcome,
            'absent_from_pinned_release'::VARCHAR AS join_method
            FROM silver s JOIN native n ON n.id=s.id AND n.source_id=s.source_id AND n.assembly=s.assembly
            JOIN read_parquet({q(config['silver'])}) b ON b.{idcol}=s.id
            WHERE s.id NOT IN (SELECT id FROM old_ids) AND n.item_key NOT IN (SELECT item_key FROM old_items)
              AND n.item_key NOT IN (SELECT item_key FROM pedia_items)
              AND NOT EXISTS(SELECT 1 FROM gold_ids g WHERE g.silver_id=s.id AND g.source_id=s.source_id)
            QUALIFY row_number() OVER(PARTITION BY n.item_key ORDER BY s.observed_at DESC NULLS LAST,s.id)=1''')
        pools = {
            'gold': records(con, 'SELECT * EXCLUDE(gold_covered) FROM inside WHERE gold_covered ORDER BY item_key'),
            'pedia_without_gold': records(con, 'SELECT * EXCLUDE(gold_covered) FROM inside WHERE NOT gold_covered ORDER BY item_key'),
            'outside_pedia': records(con, 'SELECT * FROM outside ORDER BY item_key'),
        }
        selected = []
        for group, count in QUOTAS.items():
            if len(pools[group]) < count:
                raise ValueError(f'{domain}/{group}: {len(pools[group])} eligible; need {count}')
            # Outside entities are separate native listings, grouped by their source brand.
            if group == 'outside_pedia':
                for row in pools[group]:
                    row['entity_id'] = row['item_key']
            picked = choose(pools[group], count, domain, seed)
            assert len(picked) == count
            for row in picked:
                row.update(stratum=group, in_pedia=group != 'outside_pedia', gold_covered=group == 'gold')
                if group == 'outside_pedia': row['entity_id'] = None
            selected.extend(picked)
        assert len({r['silver_id'] for r in selected}) == 5000
        assert len({r['item_key'] for r in selected}) == 5000
        picked_table = pa.Table.from_pylist(selected)
        con.register('picked', picked_table)
        assert con.execute('SELECT count(*) FROM picked JOIN old_ids ON silver_id=id').fetchall()[0][0] == 0
        assert con.execute("SELECT count(*) FROM picked p JOIN gold_ids g USING(silver_id,source_id) WHERE p.stratum <> 'gold'").fetchall()[0][0] == 0
        assert con.execute("SELECT count(*) FROM picked JOIN pedia_items USING(item_key) WHERE stratum='outside_pedia'").fetchall()[0][0] == 0
        groups = {}
        for group in QUOTAS:
            rows = [r for r in selected if r['stratum'] == group]
            groups[group] = {'rows': len(rows), 'eligible': len(pools[group]), 'brands': len({r['brand'] for r in rows if r['brand']}), 'sources': len({r['source_id'] for r in rows})}
        summary = {'domain': domain, 'seed': seed, 'rows': 5000, 'strata': groups,
            'silver_snapshot': config['silver_snapshot'], 'silver_source': config.get('original_silver', config['silver']),
            'silver_id_column': idcol, 'classification_column': statuscol, 'allowed_classification': allowed,
            'pedia_release': release['id'], 'pedia_release_sha256': release['sha256'],
            'pedia_graph_manifest_sha256': release['layers']['graph']['manifest_sha256'],
            'gold_release': gold_entry['gold_release'], 'old_silver_id_overlap': 0,
            'excluded_subsets': [{'path':str(path),'sha256':sha(path)} for path in prior_paths],
            'old_native_listing_overlap': 0, 'pedia_identity_conflicts_excluded': conflicts,
            'brands': len({r['brand'] for r in selected if r['brand']}), 'sources': len({r['source_id'] for r in selected}),
            'fragrance_focus_listings': sum(r['brand'] in FOCUS_BRANDS for r in selected) if domain == 'fragrance' else 0,
            'outside_definition': 'No exact or verified historical-bridge placement, including unplaced outcomes, for this native listing in the pinned Pedia graph; also no Gold label.',
            'all_silver_columns_preserved': True, 'selection_sha256': hashlib.sha256(json.dumps(sorted((r['silver_id'],r['stratum']) for r in selected)).encode()).hexdigest()}
        models = defaultdict(list)
        for row in selected:
            if row['model_id']: models[row['model_id']].append(row)
        summary['relationships'] = {
            'models': len(models),
            'models_with_multiple_listings': sum(len(rows)>1 for rows in models.values()),
            'models_with_multiple_sources': sum(len({r['source_id'] for r in rows})>1 for rows in models.values()),
            'models_with_sibling_variants': sum(len({r['entity_id'] for r in rows if r['entity_type']=='ProductVariant'})>1 for rows in models.values())}
        print(json.dumps(summary), flush=True)
        if plan_only: return summary
        destination.mkdir(parents=True, exist_ok=False)
        pq.write_table(picked_table, destination / 'selection.parquet', compression='zstd')
        gold = con.sql('SELECT g.* FROM gold_labels g JOIN picked p USING(silver_id,source_id)').to_arrow_table()
        assert len(set(gold['silver_id'].to_pylist())) == QUOTAS['gold']
        pq.write_table(gold, destination / 'gold_labels.parquet', compression='zstd')
    # Filter the source batches by exact ID; every Silver field and value is copied unchanged.
    source = pq.ParquetFile(config['silver'])
    wanted = pa.array([r['silver_id'] for r in selected], type=pa.int64())
    target = destination / f'{domain}_listings.parquet'
    written, pending_rows, pending = 0, 0, []
    with pq.ParquetWriter(target, source.schema_arrow, compression='zstd') as writer:
        for batch in source.iter_batches(batch_size=128, use_threads=False):
            keep = batch.filter(pc.is_in(batch.column(idcol), value_set=wanted))
            if keep.num_rows:
                pending.append(pa.Table.from_batches([keep])); pending_rows += keep.num_rows
            if pending_rows >= 512:
                writer.write_table(pa.concat_tables(pending)); written += pending_rows
                pending, pending_rows = [], 0
        if pending_rows:
            writer.write_table(pa.concat_tables(pending)); written += pending_rows
    assert written == 5000
    saved = pq.ParquetFile(target)
    assert saved.schema_arrow.equals(source.schema_arrow)
    ids = saved.read(columns=[idcol, statuscol]).to_pylist()
    assert {r[idcol] for r in ids} == set(wanted.to_pylist())
    assert all(r[statuscol] == allowed for r in ids)
    summary.update(parquet_sha256=sha(target), parquet_bytes=target.stat().st_size,
        verified_saved_rows=written, verified_saved_schema=True, verified_saved_ids=True,
        gold_label_rows=gold.num_rows, source_column_count=len(source.schema_arrow))
    (destination / 'manifest.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print('SAVED', domain, str(target), flush=True)
    return summary

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--gold-sources', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--exclude-root', action='append', default=[], type=Path)
    parser.add_argument('--seeds', nargs='+', type=int, default=[73, 97])
    parser.add_argument('--domain', choices=['food', 'fragrance', 'both'], default='both')
    parser.add_argument('--plan-only', action='store_true')
    args = parser.parse_args()
    if args.out.exists():
        parser.error('Output exists; preserve it and choose a new directory')
    if len(set(args.seeds)) != len(args.seeds):
        parser.error('Seeds must be distinct')
    for root in args.exclude_root:
        if not root.is_dir():
            parser.error(f'Exclusion directory does not exist: {root}')
    config = json.loads(args.sources.read_text('utf-8-sig'))
    gold_config = json.loads(args.gold_sources.read_text('utf-8-sig'))
    pedia = Path(config['pedia_root'])
    releases = json.loads((pedia / 'CURRENT.json').read_text('utf-8-sig'))['releases']
    domains = ('food', 'fragrance') if args.domain == 'both' else (args.domain,)
    prior = {domain: sorted({p.resolve() for root in args.exclude_root
                             for p in root.rglob(f'{domain}_listings.parquet')})
             for domain in domains}
    for seed in args.seeds:
        destination = args.out / f'silver-gold-pedia-n5000-seed{seed}'
        summaries = [build(domain, config['domains'][domain], releases[domain],
                           gold_config['domains'][domain], pedia, destination / domain,
                           prior[domain], seed, args.plan_only)
                     for domain in domains]
        if args.plan_only:
            continue
        (destination / 'summary.json').write_text(
            json.dumps({'quotas': QUOTAS, 'domains': summaries}, indent=2), encoding='utf-8')
        for domain in domains:
            prior[domain].append(destination / domain / f'{domain}_listings.parquet')
    # Plans evaluate each seed against the existing inputs; they do not reserve IDs.


if __name__ == '__main__':
    main()
