"""Stage, verify, and organize the rebuilt datasets in the mounted shared Drive."""
from collections import Counter
import argparse
from datetime import datetime
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import pyarrow.parquet as pq
from semantic_guard import decide

LOCAL=Path('C:/Users/eduar/Desktop/HACKATON')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source',type=Path,default=LOCAL/'data/subsets/pedia-4500-outside-500-v2')
parser.add_argument('--semantic',action='store_true')
options=parser.parse_args()
SOURCE=options.source
LISTINGS=Path('G:/.shortcut-targets-by-id/1lo5XQFqwWZ4oV915bOgMLt9KPW0IeTv4/Hackathon-Kavak-OpenAI-Primero/DATA/Listings')
RAW=LISTINGS/'RAW'
OLD=LISTINGS/'Non-labeled yet'
stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
STAGING=LISTINGS/f'_staging-raw-4500-500-{stamp}'
ARCHIVE=LISTINGS/'_archive'/f"{'before-content-check' if options.semantic else 'before-4500-500'}-{stamp}"
def checksum(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()
def within(path,parent):
    resolved=path.resolve()
    assert resolved.is_relative_to(parent.resolve()) and resolved!=parent.resolve(),(resolved,parent)
    return resolved

def inspect(root):
    report={'format':'silver_subset_verification/v2','status':'PASS','root':root.as_posix(),
        'gold_inputs_used':False,'domains':{},'all_file_pair_intersections':[]}
    all_sets=[]
    for domain,idcol,statuscol,allowed in [('food','observation_key','food_scope_status','confirmed'),
                                         ('fragrance','source_record_key','perfume_status','included')]:
        files=sorted((root/domain).rglob(f'{domain}_listings.parquet'))
        assert len(files)==3,(domain,len(files))
        inventory=[]
        sets=[]
        for number,path in enumerate(files,1):
            parquet=pq.ParquetFile(path)
            cols=[idcol,statuscol]+(['review_required'] if domain=='fragrance' else [])
            if options.semantic:
                cols+=[c for c in ['listing_name','description_text','ingredients_text','product_kind','concentration'] if c in parquet.schema_arrow.names]
            rows=parquet.read(columns=cols).to_pylist()
            ids={r[idcol] for r in rows}
            assert len(rows)==len(ids)==5000 and None not in ids
            assert Counter(r[statuscol] for r in rows)=={allowed:5000}
            if domain=='fragrance':assert all(r['review_required'] is not True for r in rows)
            if options.semantic:
                assert all(decide(domain,r)[0]=='accept' for r in rows)
            manifest=json.loads((path.parent/'manifest.json').read_text())
            assert manifest['gold_inputs_used'] is False
            assert checksum(path)==manifest['parquet_sha256']
            source_schema=pq.ParquetFile(manifest['silver_source']).schema_arrow
            assert source_schema.equals(parquet.schema_arrow)
            selection=pq.read_table(path.parent/'selection.parquet').to_pylist()
            assert len(selection)==5000 and {r['silver_id'] for r in selection}==ids
            assert Counter(r['stratum'] for r in selection)=={'in_pedia':4500,'outside_pedia':500}
            assert sum(r['in_pedia'] for r in selection)==4500
            assert len({r['item_key'] for r in selection})==5000
            expected=SOURCE/domain/f'subset-{number}'/f'{domain}_listings.parquet'
            assert checksum(path)==checksum(expected)
            entry={'name':f'subset-{number}','path':path.as_posix(),'rows':5000,'distinct_listing_ids':5000,
                'listing_id_column':idcol,'in_pedia':4500,'outside_pedia':500,
                'classification_counts':{allowed:5000},'uncertain_or_excluded_rows':0,
                'review_required_true_rows':sum(r.get('review_required') is True for r in rows),
                'all_original_silver_columns_preserved':True,'sha256':manifest['parquet_sha256'],
                'diversity':{k:manifest[k] for k in ['brand_labels','sources','models',
                    'models_with_multiple_listings','models_with_multiple_sources','models_with_sibling_variants']},
                'pedia_release':manifest['pedia_release']}
            if options.semantic:
                entry.update(content_check_nonaccept_rows=0,content_check_pass_rows=5000,
                    content_rule_sha256=checksum(LOCAL/'tasks/s3-gold-check-20261109/semantic_guard.py'),
                    replacement_counts=manifest['replacement_counts'],retained_rows=manifest['retained_rows'])
            inventory.append(entry)
            sets.append((entry,ids,{r['item_key'] for r in selection}))
            all_sets.append((entry,ids))
        pairs=[]
        for (left,a,ai),(right,b,bi) in itertools.combinations(sets,2):
            assert not a&b and not ai&bi
            pairs.append({'left_path':left['path'],'right_path':right['path'],
                'listing_id_intersection':0,'native_listing_intersection':0})
        union=set().union(*(ids for _,ids,_ in sets))
        assert len(union)==15000
        report['domains'][domain]={'subsets':inventory,'total_rows':15000,
            'total_distinct_listing_ids':15000,'pairwise_intersections':pairs}
    for (left,a),(right,b) in itertools.combinations(all_sets,2):
        report['all_file_pair_intersections'].append({'left_path':left['path'],'right_path':right['path'],
            'listing_id_intersection':len(a&b)})
    report['all_six_files_globally_disjoint']=all(r['listing_id_intersection']==0 for r in report['all_file_pair_intersections'])
    assert not list(root.rglob('*gold*.parquet'))
    return report

assert SOURCE.is_dir()
assert not (OLD.exists() and RAW.exists()),'Both old and RAW folders exist; inspect before merging.'
within(STAGING,LISTINGS)
within(ARCHIVE,LISTINGS)
STAGING.mkdir(exist_ok=False)
for domain in ('food','fragrance'):
    for number in (1,2,3):
        src=SOURCE/domain/f'subset-{number}'
        target=STAGING/domain/f'subset-{number}'
        target.mkdir(parents=True,exist_ok=False)
        for name in (f'{domain}_listings.parquet','selection.parquet','manifest.json'):
            shutil.copyfile(src/name,target/name)
            assert checksum(src/name)==checksum(target/name)
staged_report=inspect(STAGING)
print('STAGING VERIFIED: six files, 4500/500 each, inclusion filters and unique IDs.',flush=True)
ARCHIVE.mkdir(parents=True,exist_ok=False)
if OLD.exists():
    within(OLD,LISTINGS)
    within(RAW,LISTINGS)
    OLD.rename(RAW)
else:
    RAW.mkdir(exist_ok=True)
for child in list(RAW.iterdir()):
    src=within(child,RAW)
    dst=within(ARCHIVE/child.name,ARCHIVE)
    assert not dst.exists()
    shutil.move(str(src),str(dst))
for child in list(STAGING.iterdir()):
    src=within(child,STAGING)
    dst=within(RAW/child.name,RAW)
    assert not dst.exists()
    shutil.move(str(src),str(dst))
STAGING.rmdir()
report=inspect(RAW)
report['previous_version_archive']=ARCHIVE.as_posix()
(RAW/'verification-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
index={'name':'RAW listing datasets','format':'raw_listing_dataset_index/v2',
    'layout':'{food,fragrance}/subset-{1,2,3}/',
    'subsets_per_domain':3,'rows_per_subset':5000,'in_pedia_per_subset':4500,
    'outside_pedia_per_subset':500,'gold_used_for_selection':False,
    'inclusion_rules':{'food':"food_scope_status = 'confirmed'",
        'fragrance':"perfume_status = 'included' AND review_required IS NOT TRUE"},
    'files':{'food_listings.parquet or fragrance_listings.parquet':'Original full-schema Silver rows.',
        'selection.parquet':'Exact Silver IDs, Pedia group, and sampling provenance.',
        'manifest.json':'Pinned sources, filters, counts, diversity and checksums.'},
    'verification_report':'verification-report.json','previous_version_archive':ARCHIVE.as_posix(),
    'outside_definition':'No matching placement in the pinned Pedia release; a corresponding brand or model may already exist.'}
if options.semantic:
    index['format']='raw_listing_dataset_index/v3'
    index['content_acceptance']={'food':'Positive ingredient, food-title, or product-description evidence; reject props, empty packaging, planting stock, equipment and personal/home-care products; hold insufficient evidence.',
        'fragrance':'Personal perfume, cologne, perfume oil, body/hair mist, or a set explicitly containing personal fragrance; omit stand-alone body care, home scents and empty containers.'}
    index['content_review_report']='inspection/content-review-report.json'
(RAW/'dataset-index.json').write_text(json.dumps(index,indent=2),encoding='utf-8')
(LOCAL/'tasks/s3-gold-check-20261109/raw-drive-verification-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
for domain,data in report['domains'].items():
    print('VERIFIED',domain,'3 x 5000; 15000 distinct IDs; all pairs disjoint; all rows included.',flush=True)
print('ACTIVE',RAW,flush=True)
print('ARCHIVE',ARCHIVE,flush=True)
