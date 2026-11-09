"""Copy new subsets to the requested mounted Drive folder and inspect actual saved files."""
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import pyarrow.parquet as pq

local = Path('C:/Users/eduar/Desktop/HACKATON')
drive = Path('G:/.shortcut-targets-by-id/1lo5XQFqwWZ4oV915bOgMLt9KPW0IeTv4/Hackathon-Kavak-OpenAI-Primero/DATA/Listings/Non-labeled yet')
def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
copied = []
for domain in ('food','fragrance'):
    existing = drive / domain / f'{domain}_listings.parquet'
    original = local / f'data/subsets/silver-n5000-seed42/{domain}/{domain}_listings.parquet'
    assert digest(existing) == digest(original)
    for number, seed in ((2,73),(3,97)):
        source = local / f'data/subsets/silver-gold-pedia-n5000-seed{seed}/{domain}'
        target = drive / domain / f'subset-{number}'
        assert target.resolve().is_relative_to(drive.resolve())
        target.mkdir(exist_ok=False)
        for path in sorted(source.iterdir()):
            if not path.is_file(): continue
            destination = target / path.name
            shutil.copyfile(path,destination)
            checksum=digest(path)
            assert checksum == digest(destination)
            copied.append({'source':path.as_posix(),'destination':destination.as_posix(),'sha256':checksum})
        print('SAVED',target,flush=True)
report={'format':'silver_subset_uniqueness/v1','location':drive.as_posix(),
        'expected_subsets_per_domain':3,'expected_rows_per_subset':5000,'domains':{},
        'copied_files':copied,'all_file_pair_intersections':[]}
all_sets=[]
for domain, idcol in (('food','observation_key'),('fragrance','source_record_key')):
    paths=sorted((drive/domain).rglob(f'{domain}_listings.parquet'))
    assert len(paths)==3
    inventory=[]
    populations=[]
    for path in paths:
        data=pq.ParquetFile(path)
        ids=data.read(columns=[idcol]).column(0).to_pylist()
        values=set(ids)
        assert len(ids)==len(values)==5000 and None not in values
        entry={'name': 'subset-1 (existing)' if path.parent.name==domain else path.parent.name,
               'path':path.as_posix(),'rows':len(ids),'distinct_listing_ids':len(values),
               'listing_id_column':idcol,'sha256':digest(path)}
        if path.parent.name!=domain:
            selection=pq.ParquetFile(path.parent/'selection.parquet').read().to_pylist()
            quotas={group:sum(r['stratum']==group for r in selection)
                    for group in ('gold','pedia_without_gold','outside_pedia')}
            assert quotas=={'gold':2000,'pedia_without_gold':2900,'outside_pedia':100}
            assert {r['silver_id'] for r in selection}==values
            entry['strata']=quotas
            manifest=json.loads((path.parent/'manifest.json').read_text())
            entry['diversity']={key:manifest[key] for key in ('brands','sources','relationships','fragrance_focus_listings')}
        inventory.append(entry)
        populations.append((entry,values))
        all_sets.append((entry,values))
    pairs=[]
    for (left,a),(right,b) in itertools.combinations(populations,2):
        intersection=len(a&b)
        assert intersection==0
        pairs.append({'left_path':left['path'],'right_path':right['path'],'intersection_count':intersection})
    total=len(set().union(*(values for _,values in populations)))
    assert total==15000
    report['domains'][domain]={'subsets':inventory,'pairwise_intersections':pairs,
        'total_rows':15000,'total_distinct_listing_ids':total,
        'all_internal_unique':True,'all_pairs_disjoint':True}
    print('VERIFIED',domain,3,'subsets',total,'distinct IDs; pairwise',[p['intersection_count'] for p in pairs],flush=True)
for (left,a),(right,b) in itertools.combinations(all_sets,2):
    report['all_file_pair_intersections'].append({'left_path':left['path'],'right_path':right['path'],'intersection_count':len(a&b)})
report['all_six_files_globally_disjoint']=all(p['intersection_count']==0 for p in report['all_file_pair_intersections'])
report['status']='PASS'
payload=json.dumps(report,indent=2)
(drive/'uniqueness-report.json').write_text(payload,encoding='utf-8')
(local/'tasks/s3-gold-check-20261109/drive-uniqueness-report.json').write_text(payload,encoding='utf-8')
assert (drive/'uniqueness-report.json').read_text(encoding='utf-8')==payload
print('PASS',drive/'uniqueness-report.json')
