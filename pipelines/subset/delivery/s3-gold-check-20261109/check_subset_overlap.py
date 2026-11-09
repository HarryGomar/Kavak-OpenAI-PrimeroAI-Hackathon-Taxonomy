"""Measure exact Silver-ID overlap with the hydrated Gold label hierarchies."""
import hashlib
import json
from pathlib import Path
import duckdb

root = Path('/hackaton')
config = json.loads((root / 'tasks/s3-gold-check-20261109/overlap-inputs.json').read_text())
out = root / 'data/gold/subset-overlap'
out.mkdir(exist_ok=True)
def local(value):
    return Path(value.replace('\\', '/').replace('C:/Users/eduar/Desktop/M4M/04_Retail/M4R_REAL/', '/m4r/').replace('/work/', '/m4r/'))
def quote(value):
    return "'" + str(value).replace("'", "''") + "'"
report = {'match_method': 'Exact signed 64-bit Silver ID; original matching hierarchy_id and cluster_id; deepest available labeled cluster per Silver ID, view and product.', 'domains': {}}
with duckdb.connect(config={'threads': 2, 'memory_limit': '1GB'}) as con:
    for domain, views in config.items():
        source = root / f'data/subsets/silver-n5000-seed42/{domain}/{domain}_listings.parquet'
        idcol = 'observation_key' if domain == 'food' else 'source_record_key'
        con.execute(f'CREATE OR REPLACE TEMP VIEW subset AS SELECT {idcol} AS silver_id, source_id, listing_name FROM read_parquet({quote(source)})')
        subset_rows, subset_ids = con.execute('SELECT count(*), count(distinct silver_id) FROM subset').fetchall()[0]
        assert subset_rows == subset_ids == 5000
        selections = []
        counts = []
        for view, stages in views.items():
            labels = root / f'data/gold/{domain}/{view}_labels.parquet'
            assignments = local(stages.get('mantis') or stages['binary']) / 'tables/assignments.parquet'
            con.execute(f'CREATE OR REPLACE TEMP VIEW labels AS SELECT * FROM read_parquet({quote(labels)})')
            con.execute(f'CREATE OR REPLACE TEMP VIEW assignments AS SELECT * FROM read_parquet({quote(assignments)})')
            labeled_hierarchies = {r[0] for r in con.execute('SELECT distinct hierarchy_id FROM labels').fetchall()}
            assignment_hierarchies = {r[0] for r in con.execute('SELECT distinct hierarchy_id FROM assignments').fetchall()}
            assert labeled_hierarchies == assignment_hierarchies, (domain, view, 'wrong hierarchy')
            if view == 'listing':
                membership = 'SELECT s.*, NULL::BIGINT AS product_key, a.hierarchy_id, a.cluster_id, a.level FROM subset s JOIN assignments a ON a.id=s.silver_id'
            else:
                catalog = local(stages['catalog']) / 'tables'
                membership = f'''SELECT s.*, p.product_key, a.hierarchy_id, a.cluster_id, a.level
                    FROM subset s JOIN read_parquet({quote(catalog / 'members.parquet')}) m
                    ON s.silver_id=m.silver_id AND s.source_id=m.source_id
                    JOIN read_parquet({quote(catalog / 'products.parquet')}) p USING(product_id)
                    JOIN assignments a ON a.product_key=p.product_key'''
            matches = f'''SELECT {quote(view)} AS view, m.*, l.label, l.description, l.review_disposition
                FROM ({membership}) m JOIN labels l USING(hierarchy_id,cluster_id)
                QUALIFY m.level=max(m.level) OVER(PARTITION BY m.silver_id,m.product_key)'''
            con.execute('CREATE OR REPLACE TEMP TABLE current_matches AS ' + matches)
            rows, ids, clusters = con.execute('SELECT count(*),count(distinct silver_id),count(distinct cluster_id) FROM current_matches').fetchall()[0]
            counts.append({'view': view, 'matched_silver_ids': ids, 'percent': round(ids / subset_ids * 100, 2), 'matched_clusters': clusters, 'match_rows': rows})
            selections.append(con.sql('SELECT * FROM current_matches').to_arrow_table())
            print(domain, view, ids, 'of', subset_ids, flush=True)
        import pyarrow as pa
        con.register('all_matches', pa.concat_tables(selections))
        dest = out / f'{domain}_matches.parquet'
        con.execute(f'COPY all_matches TO {quote(dest)} (FORMAT PARQUET, COMPRESSION ZSTD)')
        matched = con.execute('SELECT count(distinct silver_id) FROM all_matches').fetchall()[0][0]
        examples = con.sql('SELECT silver_id::VARCHAR AS silver_id, listing_name, view, level, cluster_id, label FROM all_matches ORDER BY silver_id, view LIMIT 10').to_arrow_table().to_pylist()
        unmatched = con.sql('SELECT silver_id::VARCHAR AS silver_id, source_id, listing_name FROM subset ANTI JOIN all_matches USING(silver_id) ORDER BY silver_id').to_arrow_table().to_pylist()
        report['domains'][domain] = {'subset_file': str(source), 'subset_sha256': hashlib.file_digest(source.open('rb'), 'sha256').hexdigest(), 'silver_id_column': idcol, 'subset_ids': subset_ids, 'any_gold_label_ids': matched, 'percent': round(matched / subset_ids * 100, 2), 'unmatched_ids': subset_ids - matched, 'by_view': counts, 'examples': examples, 'unmatched_listings': unmatched, 'matches_file': dest.name}
        con.unregister('all_matches')
        print('TOTAL', domain, matched, 'of', subset_ids, flush=True)
(out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
