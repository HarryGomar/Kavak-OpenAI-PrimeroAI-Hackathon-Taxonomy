"""Stage corrected Food subsets; never write Drive or source candidate files."""
from pathlib import Path
from hashlib import sha256,file_digest
from collections import Counter,defaultdict
import sys,json
import pyarrow as pa
import pyarrow.parquet as pq

HOME=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(HOME/'repo-taxonomy/pipelines/subset'))
from content_audit.rules import decide

TASK=Path(__file__).resolve().parent
RAW=Path('G:/.shortcut-targets-by-id/1lo5XQFqwWZ4oV915bOgMLt9KPW0IeTv4/Hackathon-Kavak-OpenAI-Primero/DATA/Listings/RAW/food')
POOLS=TASK/'replacement-pools'
OUT=TASK/'repaired-food/food'
CHECK_COLUMNS=['observation_key','source_id','listing_name','description_text','ingredients_text','price','currency','regular_price','food_scope_status']

def checksum(p):
    with p.open('rb')as f:return file_digest(f,'sha256').hexdigest()

def writejson(p,value):p.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def policy_hashes():
    base=HOME/'repo-taxonomy/pipelines/subset'
    files=[*(base/'content_audit').glob('*.py'),base/'delivery/s3-gold-check-20261109/semantic_guard.py']
    return {str(p.relative_to(base)).replace('\\','/'):checksum(p)for p in sorted(files)}

def diversity(selection):
    bymodel=defaultdict(list)
    for r in selection:
        if r.get('model_id'):bymodel[r['model_id']].append(r)
    sibling=0
    for group in bymodel.values():
        native=defaultdict(set)
        for r in group:
            try:k=json.loads(r['item_key'])
            except (TypeError,ValueError):continue
            native[(k.get('source'),k.get('market'),k.get('native_id'))].add(k.get('variant'))
        sibling+=any(len(v)>1 for v in native.values())
    return {'brand_labels':len({r['brand']for r in selection if r.get('brand')}),
            'sources':len({r['source_id']for r in selection}), 'models':len(bymodel),
            'models_with_multiple_listings':sum(len(v)>1 for v in bymodel.values()),
            'models_with_multiple_sources':sum(len({r['source_id']for r in v})>1 for v in bymodel.values()),
            'models_with_sibling_variants':sibling}

def main():
    if OUT.exists():raise FileExistsError(OUT)
    frozen=policy_hashes()
    original={};used_ids=set();used_items=set();source_hashes={}
    for number in (1,2,3):
        src=RAW/f'subset-{number}'
        table=pq.read_table(src/'food_listings.parquet')
        selection=pq.read_table(src/'selection.parquet')
        meta=selection.to_pylist()
        byid={r['silver_id']:r for r in meta}
        assert len(byid)==table.num_rows==5000
        thin=table.select(CHECK_COLUMNS).to_pylist()
        assert {r['observation_key']for r in thin}==set(byid)
        decisions=[decide('food',r)for r in thin]
        original[number]=(table,selection,meta,byid,thin,decisions)
        used_ids.update(byid);used_items.update(r['item_key']for r in meta)
        source_hashes[str(src/'food_listings.parquet')]=checksum(src/'food_listings.parquet')
        source_hashes[str(src/'selection.parquet')]=checksum(src/'selection.parquet')
    pools={};pool_status={}
    for stratum in ('in_pedia','outside_pedia'):
        path=POOLS/f'food-{stratum}-rows.parquet'
        table=pq.read_table(path)
        meta={r['silver_id']:r for r in pq.read_table(POOLS/f'food-{stratum}-selection.parquet').to_pylist()}
        thin=table.select(CHECK_COLUMNS+['brand_name']).to_pylist()
        valid=[];counts=Counter()
        for i,row in enumerate(thin):
            result=decide('food',row);counts[result['decision']]+=1
            if result['decision']=='accept':valid.append((i,row,meta[row['observation_key']],result))
        pools[stratum]=(table,valid);pool_status[stratum]=dict(counts)
    OUT.mkdir(parents=True)
    removals=[];replacements=[];summaries={};final_ids=set();final_items=set()
    for number,(table,old_selection,metadata,byid,thin,decisions)in original.items():
        retained_indices=[];retained_selection=[];needs=Counter()
        for i,(row,result)in enumerate(zip(thin,decisions)):
            select=byid[row['observation_key']]
            if result['decision']=='accept':
                retained_indices.append(i);retained_selection.append(select)
            else:
                needs[select['stratum']]+=1
                removals.append({'subset':number,'silver_id':row['observation_key'],'item_key':select['item_key'],
                                 'stratum':select['stratum'],'listing_name':row['listing_name'],**result})
        blocks=[table.take(retained_indices)];new_selection=list(retained_selection);selected_additions=[]
        for stratum in ('in_pedia','outside_pedia'):
            pool,valid=pools[stratum];chosen=[]
            for position,row,metadata_row,result in valid:
                if len(chosen)==needs[stratum]:break
                sid=row['observation_key'];item=metadata_row['item_key']
                if sid in used_ids or item in used_items:continue
                selected={name:metadata_row.get(name)for name in old_selection.column_names}
                selected.update({'stratum':stratum,'in_pedia':stratum=='in_pedia','subset':number,
                                 'semantic_reason':result['reason'],'semantic_evidence':result['evidence']})
                if stratum=='outside_pedia':selected['brand']=row['brand_name']
                used_ids.add(sid);used_items.add(item);chosen.append(position);new_selection.append(selected)
                evidence={'subset':number,'silver_id':sid,'item_key':item,'stratum':stratum,
                          'listing_name':row['listing_name'],'pool_file':f'food-{stratum}-rows.parquet',
                          'pool_row':position,**result}
                replacements.append(evidence);selected_additions.append(evidence)
            assert len(chosen)==needs[stratum],(number,stratum,needs[stratum],len(chosen))
            if chosen:blocks.append(pool.take(chosen).cast(table.schema))
        final=pa.concat_tables(blocks)
        selection=pa.Table.from_pylist(new_selection,schema=old_selection.schema)
        assert final.num_rows==selection.num_rows==5000
        assert Counter(selection.column('stratum').to_pylist())=={'in_pedia':4500,'outside_pedia':500}
        ids=set(final.column('observation_key').to_pylist());items=set(selection.column('item_key').to_pylist())
        assert len(ids)==len(items)==5000 and not(ids&final_ids)and not(items&final_items)
        final_ids.update(ids);final_items.update(items)
        assert ids==set(selection.column('silver_id').to_pylist())
        assert all(decide('food',r)['decision']=='accept'for r in final.select(CHECK_COLUMNS).to_pylist())
        assert final.slice(0,len(retained_indices)).equals(table.take(retained_indices),check_metadata=True)
        target=OUT/f'subset-{number}';target.mkdir()
        pq.write_table(final,target/'food_listings.parquet',compression='zstd')
        pq.write_table(selection,target/'selection.parquet',compression='zstd')
        saved=pq.read_table(target/'food_listings.parquet');saved_sel=pq.read_table(target/'selection.parquet')
        assert saved.schema.equals(table.schema,check_metadata=True)and saved.equals(final,check_metadata=True)
        assert saved_sel.equals(selection,check_metadata=True)
        manifest=json.loads((RAW/f'subset-{number}'/'manifest.json').read_text())
        manifest['previous_content_repair_counts']=manifest.get('replacement_counts')
        manifest.update(diversity(new_selection))
        manifest.update({'format':'pedia_stratified_silver_subset/v4','rows':5000,
            'replacement_counts':dict(needs),'retained_rows':len(retained_indices),
            'parquet_sha256':checksum(target/'food_listings.parquet'),'selection_sha256':checksum(target/'selection.parquet'),
            'parquet_bytes':(target/'food_listings.parquet').stat().st_size,'column_count':97,
            'all_silver_columns_preserved':True,'verified_rows':5000,'verified_schema':True,'verified_ids':True,
            'semantic_rules_sha256':frozen['content_audit/rules.py'],'content_audit_rule_hashes':frozen,
            'content_checked':True,'verified_semantic_rows':5000,'verified_semantic_nonaccept_rows':0,
            'semantic_acceptance_counts':dict(Counter(decide('food',r)['reason']for r in final.select(CHECK_COLUMNS).to_pylist())),
            'source_previous_subset':str(RAW/f'subset-{number}'),
            'source_previous_parquet_sha256':source_hashes[str(RAW/f'subset-{number}'/'food_listings.parquet')],
            'content_audit_evidence':'content-repair-evidence.json','gold_pairing_requires_refresh':True})
        manifest['strata']={stratum:{'rows':quota,**{k:v for k,v in diversity([r for r in new_selection if r['stratum']==stratum]).items()if k in('brand_labels','sources')}}for stratum,quota in[('in_pedia',4500),('outside_pedia',500)]}
        writejson(target/'manifest.json',manifest)
        writejson(target/'content-repair-evidence.json',{'removed':[r for r in removals if r['subset']==number],'added':selected_additions,'policy_hashes':frozen})
        summaries[f'subset-{number}']={'rows':5000,'retained':len(retained_indices),'replaced':sum(needs.values()),'replacement_counts':dict(needs),'strata':{'in_pedia':4500,'outside_pedia':500},'sha256':manifest['parquet_sha256'],'all_rows_accept':True,'source_values_preserved':True,'schema_columns':97}
    assert len(final_ids)==len(final_items)==15000
    assert policy_hashes()==frozen,'Policy changed during repair; rerun against frozen rules.'
    assert all(checksum(Path(path))==value for path,value in source_hashes.items())
    report={'status':'PASS','stage_root':str(OUT),'rows':15000,'globally_unique_ids':15000,'globally_unique_native_items':15000,
            'subsets':summaries,'pool_status':pool_status,'removal_count':len(removals),'replacement_count':len(replacements),
            'policy_hashes':frozen,'inputs_unchanged':True,'drive_modified':False,'gold_pairing_requires_refresh':True}
    writejson(OUT.parent/'repair-report.json',report)
    writejson(OUT.parent/'removed-rows.json',removals)
    writejson(OUT.parent/'added-rows.json',replacements)
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
