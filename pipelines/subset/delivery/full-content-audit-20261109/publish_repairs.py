"""Publish checked Food/other repairs, leaving every Fragrance file untouched."""
from pathlib import Path
from datetime import datetime, timezone
from hashlib import file_digest
import collections
import itertools
import json
import shutil
import sys
import pyarrow.parquet as pq

HOME = Path(__file__).resolve().parents[2]
TASK = Path(__file__).resolve().parent
LISTINGS = Path('G:/.shortcut-targets-by-id/1lo5XQFqwWZ4oV915bOgMLt9KPW0IeTv4/Hackathon-Kavak-OpenAI-Primero/DATA/Listings')
RAW, LABELED = LISTINGS/'RAW', LISTINGS/'Labeled'
sys.path.insert(0,str(HOME/'repo-taxonomy/pipelines/subset'))
from content_audit.rules import decide


def sha(path):
    with path.open('rb') as handle:return file_digest(handle,'sha256').hexdigest()


def load(path):return json.loads(path.read_text(encoding='utf-8-sig'))


def save(path,value):
    pending=path.with_suffix(path.suffix+'.pending')
    pending.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    pending.replace(path)


def within(path,parent):
    path=path.resolve()
    assert path!=parent.resolve() and path.is_relative_to(parent.resolve())
    return path


def inspect(path,domain):
    key='source_record_key' if domain=='fragrance' else 'observation_key'
    table=pq.read_table(path)
    ids=set(table.column(key).to_pylist())
    assert len(ids)==table.num_rows and None not in ids
    selection=pq.read_table(path.parent/'selection.parquet')
    assert ids==set(selection.column('silver_id').to_pylist())
    if domain!='fragrance':
        fields=[n for n in ('listing_name','description_text','ingredients_text','price','regular_price','currency','amazon_category_rank_text') if n in table.column_names]
        if domain=='food':
            rows=table.select(fields).to_pylist()
        else:
            source=pq.read_table(path.parent/'source_rows.parquet')
            source_rows={r['asin']:r for r in source.select(['asin','title','description','aplus_content','categories','best_seller_ranks']).to_pylist()}
            saved=table.select(['source_listing_id',*fields]).to_pylist()
            rows=[{**source_rows[r['source_listing_id']],**r} for r in saved]
        assert all(decide(domain,r)['decision']=='accept' for r in rows),(domain,'nonaccepted content')
    if domain=='food':
        assert table.num_rows==5000
        assert collections.Counter(selection.column('stratum').to_pylist())=={'in_pedia':4500,'outside_pedia':500}
    return table,ids


def main():
    protected=load(TASK/'fragrance-protected-hashes.json')
    assert all(sha(LISTINGS/name)==value for name,value in protected.items())
    assert load(TASK/'repaired-food/repair-report.json')['status']=='PASS'
    assert load(TASK/'repaired-other/ready-report.json')['status']=='PASS'
    assert load(TASK/'repaired-food-gold/pairing-verification.json')['status']=='PASS'
    replacements=[]
    for number in (1,2,3):
        replacements.append((TASK/'repaired-food/food'/f'subset-{number}',RAW/'food'/f'subset-{number}','food'))
        replacements.append((TASK/'repaired-food-gold/food'/f'subset-{number}',LABELED/'food'/f'subset-{number}','gold'))
    for domain in ('clothing','footwear','games'):
        replacements.append((TASK/'repaired-other'/domain/'subset-1',RAW/domain/'subset-1',domain))
    food_schema=pq.read_schema(RAW/'food/subset-1/food_listings.parquet')
    for source,dest,domain in replacements:
        assert source.is_dir() and dest.is_dir()
        if domain!='gold':
            table,ids=inspect(source/f'{domain}_listings.parquet',domain)
            assert table.schema.equals(food_schema,check_metadata=True)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    archive=within(LISTINGS/'_archive'/f'before-full-content-audit-{stamp}',LISTINGS)
    staging=within(LISTINGS/f'_staging-full-content-audit-{stamp}',LISTINGS)
    assert not archive.exists() and not staging.exists()
    staging.mkdir()
    for source,dest,domain in replacements:
        staged=within(staging/dest.relative_to(LISTINGS),staging)
        shutil.copytree(source,staged)
        assert all(sha(p)==sha(staged/p.relative_to(source)) for p in source.rglob('*') if p.is_file())
    archive.mkdir(parents=True)
    for parent,names in ((RAW,('dataset-index.json','verification-report.json')),
                         (LABELED,('report.json','pairing-report.json','upload-receipt.json'))):
        for name in names:
            dest=archive/parent.name/name;dest.parent.mkdir(exist_ok=True)
            shutil.copy2(parent/name,dest)
    for source,dest,domain in replacements:
        dest=within(dest,LISTINGS)
        archived=within(archive/dest.relative_to(LISTINGS),archive)
        archived.parent.mkdir(parents=True,exist_ok=True)
        staged=within(staging/dest.relative_to(LISTINGS),staging)
        dest.rename(archived)
        staged.rename(dest)
    report=load(RAW/'verification-report.json')
    index=load(RAW/'dataset-index.json')
    old_fragrance=report['domains']['fragrance']
    roster=[]
    final={}
    for domain in ('food','fragrance','clothing','footwear','games'):
        entries=[]
        for path in sorted((RAW/domain).glob('subset-*/*_listings.parquet')):
            table,ids=inspect(path,domain)
            number=int(path.parent.name.split('-')[1])
            manifest=load(path.parent/'manifest.json')
            assert sha(path)==manifest.get('parquet_sha256',manifest.get('output_sha256'))
            entry={'name':f'subset-{number}','dataset_id':f'{domain}/subset-{number}','path':path.as_posix(),
                   'rows':table.num_rows,'distinct_listing_ids':len(ids),'listing_id_column':'source_record_key'if domain=='fragrance'else'observation_key',
                   'sha256':sha(path),'column_count':len(table.schema)}
            if domain=='food':entry.update(in_pedia=4500,outside_pedia=500,classification_counts={'confirmed':5000},content_audit_passed=True)
            elif domain!='fragrance':entry.update(in_pedia=None,outside_pedia=None,pedia_status='not_evaluated',content_audit_passed=True)
            entries.append(entry);roster.append((path,ids))
        if domain!='fragrance':
            report['domains'][domain]={'subsets':entries,'total_rows':sum(e['rows']for e in entries),
                                       'total_distinct_listing_ids':sum(e['rows']for e in entries),'pairwise_intersections':[]}
            final[domain]={'rows':sum(e['rows']for e in entries),'subsets':entries}
    assert report['domains']['fragrance']==old_fragrance
    intersections=[{'left_path':a.as_posix(),'right_path':b.as_posix(),'listing_id_intersection':len(ai&bi)}
                   for (a,ai),(b,bi)in itertools.combinations(roster,2)]
    assert len(roster)==9 and all(x['listing_id_intersection']==0 for x in intersections)
    report.update(all_file_pair_intersections=intersections,all_files_globally_disjoint=True,subset_count=9,
        content_repair_scope=['food','clothing','footwear','games'],fragrance_modified=False,
        content_audit_report='inspection/full-content-audit-report.json')
    index['rows_per_subset'].update(clothing=5000,footwear=2948,games=4338)
    index['inclusion_rules']['games']='Actual human toys/games or video-game accessories, specific source category plus independent content screening; no party supplies, pet products, utility products or held ambiguity. 4338 rows retained.'
    index['content_audit_scope']={'repaired':['food','clothing','footwear','games'],'fragrance':'unchanged by explicit owner instruction','report':'inspection/full-content-audit-report.json'}
    index['datasets']=[{'domain':d,'subset':int(e['name'].split('-')[1]),'dataset_id':e.get('dataset_id',f"{d}/{e['name']}"),
                        'rows':e['rows'],'listing_file':Path(e['path']).relative_to(RAW).as_posix()}
                       for d,info in report['domains'].items()for e in info['subsets']]
    index['content_acceptance'].update(food='Positive edible-product evidence, excluding supplements/pet products/equipment/planting material; source-quality contradictions held.',
        clothing='Actual garments; accessories excluded and UI-contaminated descriptions held.',
        footwear='Actual footwear, no standalone accessories; UI-contaminated descriptions held.',
        games='Actual human toys/games and video-game hardware/accessories; party/utility/pet/grooming products rejected and ambiguity held.')
    new_gold=load(TASK/'repaired-food-gold/report.json')
    gold_report=load(LABELED/'report.json');gold_report['food']=new_gold['food']
    pairs=load(LABELED/'pairing-report.json')
    receipt=load(LABELED/'upload-receipt.json')
    for number in (1,2,3):
        raw_path=RAW/'food'/f'subset-{number}'/'food_listings.parquet'
        gold_path=LABELED/'food'/f'subset-{number}'/'gold.parquet'
        selected=pq.read_table(raw_path.parent/'selection.parquet',columns=['silver_id','in_pedia']).to_pylist()
        wanted={r['silver_id']for r in selected if r['in_pedia']}
        actual=set(pq.read_table(gold_path,columns=['silver_id']).column('silver_id').to_pylist())
        assert len(actual)==4500 and actual==wanted
        for entry in receipt['pairs']:
            if entry['domain']=='food'and int(entry['subset'])==number:
                entry.update(raw_sha256=sha(raw_path),gold_sha256=sha(gold_path),raw_rows=5000,gold_rows=4500)
    receipt['food_content_repair_utc']=datetime.now(timezone.utc).isoformat()
    assert all(sha(LISTINGS/name)==value for name,value in protected.items())
    summary={'status':'PASS','audited_input_rows':43168,'repaired_domains':final,
             'food_repair':load(TASK/'repaired-food/repair-report.json'),
             'other_domain_repair':load(TASK/'repaired-other/ready-report.json'),
             'food_gold_exact_pairing':True,'fragrance_files_modified':0,'fragrance_files_checksum_unchanged':len(protected),
             'all9_subsets_have_disjoint_observation_ids':True,'archive':archive.as_posix(),
             'method':'All-row deterministic scope/quality screening plus independent agent review of suspicious source evidence; not manual ground truth for every row.'}
    inspection=RAW/'inspection'
    save(inspection/'full-content-audit-report.json',summary)
    shutil.copy2(TASK/'repaired-food/removed-rows.json',inspection/'food-content-audit-quarantined.json')
    shutil.copy2(TASK/'repaired-other/quarantine-previous-records.json',inspection/'other-domains-content-audit-quarantined.json')
    save(RAW/'verification-report.json',report);save(RAW/'dataset-index.json',index)
    save(LABELED/'report.json',gold_report);save(LABELED/'pairing-report.json',pairs);save(LABELED/'upload-receipt.json',receipt)
    # Refresh canonical local mirrors; preserve older snapshots in their versioned folders.
    for domain in ('clothing','footwear','games'):
        local=HOME/'data/different_lines/silver'/domain
        backup=TASK/'local-before-full-content-audit'/domain
        shutil.copytree(local,backup)
        for p in (RAW/domain/'subset-1').iterdir():
            if p.is_file():shutil.copy2(p,local/p.name)
    local_report=load(HOME/'data/different_lines/silver/verification.json')
    new_report=load(TASK/'new-domain-silver/verification.json')
    local_report['domains']=new_report['domains'];local_report['config']=new_report['config']
    save(HOME/'data/different_lines/silver/verification.json',local_report)
    for number in (1,2,3):
        local=HOME/'data/subsets/pedia-4500-outside-500-v3-content-checked/food'/f'subset-{number}'
        backup=TASK/'local-before-full-content-audit/food'/f'subset-{number}'
        shutil.copytree(local,backup)
        for p in (RAW/'food'/f'subset-{number}').iterdir():
            if p.is_file():shutil.copy2(p,local/p.name)
        gold_local=HOME/'data/subsets/pedia-gold-from-silver-v1/food'/f'subset-{number}'
        shutil.copytree(gold_local,TASK/'local-before-full-content-audit/food-gold'/f'subset-{number}')
        for p in (LABELED/'food'/f'subset-{number}').iterdir():
            if p.is_file():shutil.copy2(p,gold_local/p.name)
    assert all(sha(LISTINGS/name)==value for name,value in protected.items())
    save(TASK/'delivery-report.json',summary)
    print(json.dumps({'status':'PASS','food_replacements':138,'clothing_rows':5000,'footwear_rows':2948,'games_rows':4338,
                      'food_gold_pairing':'PASS','fragrance_unchanged_files':len(protected),'archive':str(archive)},indent=2))


if __name__=='__main__':main()
