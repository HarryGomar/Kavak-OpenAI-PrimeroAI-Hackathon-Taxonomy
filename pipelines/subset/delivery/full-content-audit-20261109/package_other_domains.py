"""Package and verify repaired category domains; no Drive writes."""
from pathlib import Path
from hashlib import file_digest
from datetime import datetime,timezone
import sys,json,shutil,collections,itertools
import pyarrow as pa
import pyarrow.parquet as pq
HOME=Path.cwd();sys.path.insert(0,str(HOME/'repo-taxonomy/pipelines/subset'))
from content_audit.rules import decide
SOURCE=HOME/'tasks/raw-content-audit/new-domain-silver'
INPUTS=HOME/'tasks/raw-content-audit/new-domain-inputs'
OUT=HOME/'tasks/raw-content-audit/repaired-other'
DRIVE=Path('G:/.shortcut-targets-by-id/1lo5XQFqwWZ4oV915bOgMLt9KPW0IeTv4/Hackathon-Kavak-OpenAI-Primero/DATA/Listings/RAW')

def checksum(p):
 with p.open('rb') as f:return file_digest(f,'sha256').hexdigest()

def save(p,v):p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
 if OUT.exists():raise FileExistsError(OUT)
 template=pq.read_schema(DRIVE/'food/subset-1/food_listings.parquet')
 report={'status':'PASS','ready_for_drive_replacement':False,'drive_mutated':False,'domains':{},'domain_pairs':[]}
 allkeys={};allasins={};quarantine=[]
 rulesdir=HOME/'repo-taxonomy/pipelines/subset/content_audit'
 rulehashes={p.name:checksum(p) for p in rulesdir.glob('*.py')}
 OUT.mkdir()
 for domain in ['clothing','footwear','games']:
  src=SOURCE/domain;destination=OUT/domain/'subset-1';destination.mkdir(parents=True)
  silver=pq.read_table(src/f'{domain}_listings.parquet');side=pq.read_table(src/'source_rows.parquet');raw=pq.read_table(INPUTS/domain/f'{domain}_listings.parquet')
  assert silver.schema.equals(template,check_metadata=True)
  assert side.select(raw.column_names).equals(raw,check_metadata=False)
  sourcerows={r['asin']:r for r in side.to_pylist()};records=silver.to_pylist()
  failures=[]
  for row in records:
   verdict=decide(domain,{**sourcerows[row['source_listing_id']],**row})
   if verdict['decision']!='accept':failures.append({'observation_key':row['observation_key'],'asin':row['source_listing_id'],**verdict})
  if failures:
   save(destination/'FAILED-content-check.json',failures)
   raise AssertionError((domain,len(failures),failures[:3]))
  keys=set(silver.column('observation_key').to_pylist());asins=set(silver.column('source_listing_id').to_pylist())
  assert len(keys)==len(asins)==silver.num_rows
  assert set(side.column('observation_key').to_pylist())==keys
  allkeys[domain]=keys;allasins[domain]=asins
  for name in [f'{domain}_listings.parquet','source_rows.parquet']:
   shutil.copy2(src/name,destination/name);assert checksum(src/name)==checksum(destination/name)
  shutil.copy2(src/'manifest.json',destination/'parsing-manifest.json')
  selection=pa.table({'silver_id':silver.column('observation_key'),'listing_key':silver.column('listing_key'),'source_id':silver.column('source_id'),'source_listing_id':silver.column('source_listing_id'),'domain':pa.array([domain]*silver.num_rows),'subset':pa.array([1]*silver.num_rows,pa.int64()),'dataset_id':pa.array([f'{domain}/subset-1']*silver.num_rows),'in_pedia':pa.nulls(silver.num_rows,pa.bool_()),'stratum':pa.array(['not_evaluated']*silver.num_rows)})
  pq.write_table(selection,destination/'selection.parquet',compression='zstd');assert pq.read_table(destination/'selection.parquet').equals(selection)
  oldpath=DRIVE/domain/'subset-1'/f'{domain}_listings.parquet';old=pq.read_table(oldpath);oldasins=set(old.column('source_listing_id').to_pylist());oldkeys=set(old.column('observation_key').to_pylist())
  oldsource={r['asin']:r for r in pq.read_table(oldpath.parent/'source_rows.parquet').to_pylist()}
  removed=oldasins-asins;added=asins-oldasins
  for row in old.to_pylist():
   if row['source_listing_id'] in removed:
    merged={**oldsource[row['source_listing_id']],**row};verdict=decide(domain,merged)
    quarantine.append({'domain':domain,'subset':1,'observation_key':row['observation_key'],'asin':row['source_listing_id'],'listing_name':row['listing_name'],'description_excerpt':(row['description_text']or'')[:1200],**verdict})
  manifest=json.load(open(src/'manifest.json'))
  assert manifest['output_sha256']==checksum(destination/f'{domain}_listings.parquet')
  manifest.update({'format':'content_audited_category_silver_raw_subset/v3','domain':domain,'subset':1,'dataset_id':f'{domain}/subset-1','rows':silver.num_rows,'gold_inputs_used':False,'in_pedia':None,'outside_pedia':None,'pedia_status':'not_evaluated','parquet_sha256':checksum(destination/f'{domain}_listings.parquet'),'selection_sha256':checksum(destination/'selection.parquet'),'source_rows_sha256':checksum(destination/'source_rows.parquet'),'column_count':97,'all_silver_columns_preserved':True,'verified_rows':silver.num_rows,'verified_schema':True,'verified_ids':True,'parsing_manifest':'parsing-manifest.json','content_audit':{'all_rows_scope_and_quality_accepted':True,'accepted_rows':silver.num_rows,'rejected_rows':0,'held_rows':0,'rules_sha256':rulehashes,'policy':'Source-grounded content screen and conservative source-quality holds; no manual truth guarantee.'},'replacement':{'previous_rows':old.num_rows,'retained_rows':len(asins&oldasins),'removed_rows':len(removed),'added_rows':len(added),'previous_drive_parquet_sha256':checksum(oldpath)}})
  save(destination/'manifest.json',manifest)
  reread=pq.read_table(destination/f'{domain}_listings.parquet');assert reread.equals(silver,check_metadata=True)
  report['domains'][domain]={'path':str(destination),'rows':silver.num_rows,'columns':97,'exact_schema':True,'all_source_values_preserved':True,'all_rows_scope_quality_accepted':True,'unique_observation_ids':len(keys),'unique_asins':len(asins),'parquet_sha256':manifest['parquet_sha256'],'selection_sha256':manifest['selection_sha256'],'source_rows_sha256':manifest['source_rows_sha256'],**manifest['replacement']}
 for a,b in itertools.combinations(allkeys,2):
  assert not allkeys[a]&allkeys[b] and not allasins[a]&allasins[b]
  report['domain_pairs'].append({'left':a,'right':b,'observation_overlap':0,'asin_overlap':0})
 report['ready_for_drive_replacement']=True
 report['quarantined_previous_records']=len(quarantine)
 save(OUT/'quarantine-previous-records.json',quarantine);save(OUT/'ready-report.json',report)
 print(json.dumps(report,indent=2))
if __name__=='__main__':main()
