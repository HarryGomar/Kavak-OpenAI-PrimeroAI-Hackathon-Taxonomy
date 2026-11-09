"""Verify complete listing coverage, original Gold values, and exact join keys."""
import argparse
import json
from pathlib import Path

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq


def verify(config_path, output):
    config = json.loads(Path(config_path).read_text('utf-8-sig'))
    output = Path(output)
    report = {'format': 'gold_batch_verification/v1', 'domains': {}}
    with duckdb.connect(config={'threads': 2, 'memory_limit': '2GB'}) as con:
        for domain, entry in config['domains'].items():
            root = output / domain
            if not root.exists():
                continue
            run = json.loads((root / 'report.json').read_text())
            con.execute('CREATE OR REPLACE TEMP TABLE exported AS SELECT * FROM read_parquet(?)',
                        [str(root / 'batch-*' / 'listing_gold_links.parquet')])
            con.execute('CREATE OR REPLACE TEMP TABLE roster AS SELECT * FROM read_parquet(?)',
                        [str(root / 'listing_index.parquet')])
            counts = con.sql('SELECT count(*),count(DISTINCT silver_id) FROM roster').fetchall()[0]
            if counts[0] != counts[1] or counts[0] != run['listings']:
                raise ValueError(f'{domain}: repeated or missing listings in index')
            missing = con.sql('''SELECT count(*) FROM exported e ANTI JOIN roster r
                ON e.silver_id=r.silver_id AND e.batch=r.batch''').fetchall()[0][0]
            duplicates = con.sql('''SELECT count(*) FROM (
                SELECT silver_id FROM exported GROUP BY 1 HAVING count(DISTINCT batch)>1)''').fetchall()[0][0]
            if missing or duplicates:
                raise ValueError(f'{domain}: batches are not disjoint or indexed correctly')
            idcol = 'observation_key' if domain == 'food' else 'source_record_key'
            con.execute(f'CREATE OR REPLACE TEMP TABLE silver AS SELECT {idcol} AS silver_id,source_id FROM read_parquet(?)', [entry['silver']])
            con.execute('CREATE OR REPLACE TEMP TABLE historical(silver_id BIGINT,source_id VARCHAR)')
            for history in entry.get('historical_sources', []):
                con.execute(f'INSERT INTO historical SELECT DISTINCT {idcol},source_id FROM read_parquet(?)', [history['path']])
            flags = con.sql('''SELECT count(*) FROM roster r WHERE
                r.in_current_silver IS DISTINCT FROM EXISTS(SELECT 1 FROM silver s WHERE s.silver_id=r.silver_id AND s.source_id=r.source_id)
                OR r.in_historical_silver IS DISTINCT FROM EXISTS(SELECT 1 FROM historical h WHERE h.silver_id=r.silver_id AND h.source_id=r.source_id)''').fetchall()[0][0]
            if flags:
                raise ValueError(f'{domain}: Silver join coverage is incorrect')
            labels_by_view = {}
            checks = []
            for view_name, view in entry['views'].items():
                labels = pq.read_table(view['labels'])
                labels_by_view[view_name] = labels
                con.register('labels', labels)
                con.execute('CREATE OR REPLACE TEMP TABLE assignments AS SELECT * FROM read_parquet(?)', [view['assignments']])
                if view_name == 'listing':
                    membership = '''SELECT a.id AS silver_id,NULL::BIGINT AS product_key,
                        a.hierarchy_id,a.cluster_id,a.level FROM assignments a'''
                else:
                    con.execute('CREATE OR REPLACE TEMP TABLE members AS SELECT * FROM read_parquet(?)', [view['members']])
                    con.execute('CREATE OR REPLACE TEMP TABLE products AS SELECT * FROM read_parquet(?)', [view['products']])
                    membership = '''SELECT m.silver_id,p.product_key,a.hierarchy_id,a.cluster_id,a.level
                        FROM members m JOIN products p USING(product_id) JOIN assignments a USING(product_key)'''
                # All original levels are retained; no deepest-only or review-state filter.
                con.execute(f'''CREATE OR REPLACE TEMP TABLE expected AS SELECT DISTINCT m.*
                    FROM ({membership}) m JOIN labels l USING(hierarchy_id,cluster_id)''')
                if run.get('smoke_limit'):
                    con.execute('DELETE FROM expected WHERE silver_id NOT IN (SELECT silver_id FROM roster)')
                con.execute('''CREATE OR REPLACE TEMP TABLE actual AS SELECT silver_id,product_key,
                    hierarchy_id,cluster_id,level FROM exported WHERE view=?''', [view_name])
                differences = con.sql('''SELECT count(*) FROM (
                    (SELECT * FROM expected EXCEPT ALL SELECT * FROM actual)
                    UNION ALL (SELECT * FROM actual EXCEPT ALL SELECT * FROM expected))''').fetchall()[0][0]
                if differences:
                    raise ValueError(f'{domain}/{view_name}: {differences} original listing/Gold links differ')
                checks.append({'view': view_name, 'all_original_links_preserved': True,
                               'links': con.sql('SELECT count(*) FROM actual').fetchall()[0][0]})
                con.unregister('labels')
            batches = sorted(root.glob('batch-*'))
            for position, batch in enumerate(batches):
                links = pq.read_table(batch / 'listing_gold_links.parquet')
                ids = set(links['silver_id'].to_pylist())
                expected_size = min(run['batch_size'], run['listings'] - position * run['batch_size'])
                if len(ids) != expected_size:
                    raise ValueError(f'{batch}: expected {expected_size} listings, found {len(ids)}')
                pairs = set(zip(links['view'].to_pylist(), links['hierarchy_id'].to_pylist(), links['cluster_id'].to_pylist()))
                for view_name, labels in labels_by_view.items():
                    keys = zip(labels['hierarchy_id'].to_pylist(), labels['cluster_id'].to_pylist())
                    positions = [i for i, (h, c) in enumerate(keys) if (view_name, h, c) in pairs]
                    path = batch / 'gold' / f'{view_name}_labels.parquet'
                    if not positions:
                        if path.exists():
                            raise ValueError(f'{path}: unexpected Gold rows')
                        continue
                    expected = labels.take(pa.array(positions, type=pa.int64()))
                    actual = pq.read_table(path)
                    if not expected.equals(actual, check_metadata=True):
                        raise ValueError(f'{path}: original Gold rows, columns, types or values changed')
            report['domains'][domain] = {'listings': counts[0], 'batches': len(batches),
                'complete_original_membership': not bool(run.get('smoke_limit')),
                'disjoint_batches': True, 'original_gold_rows_and_schema': True, 'views': checks}
    report['status'] = 'PASS'
    (output / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--run', action='store_true', help='Explicitly request the optional full readback check')
    args = parser.parse_args()
    if args.run:
        verify(args.sources, args.out)
    else:
        print('Verification skipped; the optional readback requires --run.', flush=True)
