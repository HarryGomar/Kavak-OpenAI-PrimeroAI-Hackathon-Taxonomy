"""Inspect all actual subset files and record exact internal/pairwise ID counts."""
import hashlib
import itertools
import json
from pathlib import Path
import pyarrow.parquet as pq

ROOT = Path('/hackaton')
HOST = 'C:/Users/eduar/Desktop/HACKATON'
out = ROOT / 'data/subsets'
def host(path):
    return str(path).replace('/hackaton', HOST)
def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()
report = {'format': 'silver_subset_uniqueness/v1', 'expected_subsets_per_domain': 3,
    'expected_rows_per_subset': 5000, 'domains': {}, 'all_file_pair_intersections': []}
populations = []
for domain, idcol in [('food','observation_key'),('fragrance','source_record_key')]:
    paths = sorted(out.rglob(f'{domain}_listings.parquet'))
    inventory, sets = [], []
    assert len(paths) == 3, (domain, 'Expected three actual subset files', [host(p) for p in paths])
    for path in paths:
        parquet = pq.ParquetFile(path)
        ids = parquet.read(columns=[idcol]).column(0).to_pylist()
        values = set(ids)
        assert len(ids) == len(values) == 5000
        assert None not in values
        entry = {'name': path.parent.parent.name, 'path': host(path), 'rows': len(ids),
            'listing_id_column': idcol, 'distinct_listing_ids': len(values),
            'null_listing_ids': 0, 'sha256': sha(path)}
        if path.parent.parent.name.startswith('silver-gold-pedia-'):
            manifest = json.loads((path.parent / 'manifest.json').read_text())
            assert entry['sha256'] == manifest['parquet_sha256']
            selection = pq.read_table(path.parent / 'selection.parquet').to_pylist()
            selected = {r['silver_id'] for r in selection}
            assert selected == values and len(selection) == 5000
            quotas = {name:sum(r['stratum']==name for r in selection) for name in ('gold','pedia_without_gold','outside_pedia')}
            assert quotas == {'gold':2000,'pedia_without_gold':2900,'outside_pedia':100}
            labels = pq.read_table(path.parent / 'gold_labels.parquet', columns=['silver_id']).column(0).to_pylist()
            assert set(labels) == {r['silver_id'] for r in selection if r['stratum']=='gold'}
            for excluded in manifest['excluded_subsets']:
                assert sha(excluded['path']) == excluded['sha256'], ('Excluded subset changed',excluded['path'])
            statuscol, allowed = ('food_scope_status','confirmed') if domain=='food' else ('perfume_status','included')
            assert set(parquet.read(columns=[statuscol]).column(0).to_pylist()) == {allowed}
            entry.update(strata=quotas, diversity=manifest['strata'], total_sources=manifest['sources'],
                total_brand_labels=manifest['brands'], relationships=manifest['relationships'],
                column_count=len(parquet.schema_arrow), original_schema_preserved=manifest['verified_saved_schema'],
                gold_labeled_distinct_ids=len(set(labels)))
        inventory.append(entry)
        sets.append(values)
        populations.append((entry, values))
    intersections=[]
    for (left,left_ids),(right,right_ids) in itertools.combinations(zip(inventory,sets),2):
        n=len(left_ids & right_ids)
        intersections.append({'left_path':left['path'],'right_path':right['path'],'intersection_count':n})
        assert n==0
    union=set().union(*sets)
    assert len(union)==15000
    report['domains'][domain]={'subsets':inventory,'pairwise_intersections':intersections,
        'total_rows':15000,'total_distinct_listing_ids':len(union),'all_internal_unique':True,'all_pairs_disjoint':True}
for (left,left_ids),(right,right_ids) in itertools.combinations(populations,2):
    report['all_file_pair_intersections'].append({'left_path':left['path'],'right_path':right['path'],
        'intersection_count':len(left_ids & right_ids)})
report['all_six_files_globally_disjoint']=all(p['intersection_count']==0 for p in report['all_file_pair_intersections'])
report['status']='PASS'
(out / 'uniqueness-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
for domain, data in report['domains'].items():
    print(domain, 'files',len(data['subsets']),'rows',data['total_rows'],'distinct',data['total_distinct_listing_ids'],
        'intersections',[p['intersection_count'] for p in data['pairwise_intersections']])
print('all_six_files_globally_disjoint',report['all_six_files_globally_disjoint'])
print('PASS',host(out / 'uniqueness-report.json'))
