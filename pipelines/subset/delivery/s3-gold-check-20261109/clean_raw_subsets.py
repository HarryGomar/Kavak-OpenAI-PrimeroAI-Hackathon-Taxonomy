"""Preserve valid RAW rows and replace domain-invalid/unsupported rows, without Gold."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from make_stratified_subsets import prepare_candidates,choose,sha,q,records
from semantic_guard import decide

ROOT=Path('/hackaton')
TASK=ROOT/'tasks/s3-gold-check-20261109'
OLD=ROOT/'data/subsets/pedia-4500-outside-500-v2'
DEST=ROOT/'data/subsets/pedia-4500-outside-500-v3-content-checked'
QUOTAS={'in_pedia':4500,'outside_pedia':500}

def build(domain,config,release):
    idcol='observation_key' if domain=='food' else 'source_record_key'
    statuscol,allowed=('food_scope_status','confirmed') if domain=='food' else ('perfume_status','included')
    prepared=[]
    with duckdb.connect(config={'threads':2,'memory_limit':'2GB','preserve_insertion_order':False}) as con:
        prepare_candidates(con,domain,config,release)
        con.execute('CREATE TEMP TABLE approved AS SELECT DISTINCT silver_id,source_id,reason,evidence FROM read_parquet(?) WHERE decision=\'accept\'',
            [str(TASK/f'{domain}-semantic-eligibility.parquet')])
        con.execute('''CREATE TEMP TABLE pool_inside AS SELECT c.*,a.reason AS semantic_reason,a.evidence AS semantic_evidence
            FROM candidates c JOIN approved a USING(silver_id,source_id)''')
        con.execute("CREATE TEMP TABLE all_p AS SELECT *,try_cast(substr(mention_id,5) AS BIGINT) AS observation_id FROM graph.placement")
        con.execute('''CREATE TEMP TABLE pedia_items AS SELECT DISTINCT n.item_key FROM all_p p JOIN silver s
            ON p.observation_id=s.id AND p.source_id=s.source_id JOIN native n ON n.id=s.id
            UNION SELECT DISTINCT n.item_key FROM all_p p JOIN legacy m ON m.mention_id=p.observation_id
            JOIN silver s ON s.id=m.silver_id AND s.source_id=m.source_id AND s.listing_key=m.listing_key JOIN native n ON n.id=s.id''')
        con.execute('''CREATE TEMP TABLE pool_outside AS SELECT n.item_key,s.id AS silver_id,s.source_id,s.market,s.listing_name,
            NULL::VARCHAR AS model_id,NULL::VARCHAR AS entity_id,NULL::VARCHAR AS entity_type,
            NULL::VARCHAR AS mention_id,NULL::VARCHAR AS level,NULL::VARCHAR AS outcome,
            'absent_from_pinned_release'::VARCHAR AS join_method,a.reason AS semantic_reason,a.evidence AS semantic_evidence
            FROM silver s JOIN approved a ON a.silver_id=s.id AND a.source_id=s.source_id
            JOIN native n ON n.id=s.id AND n.source_id=s.source_id AND n.assembly=s.assembly
            WHERE n.item_key NOT IN (SELECT item_key FROM pedia_items)
            QUALIFY row_number() OVER(PARTITION BY n.item_key ORDER BY s.observed_at DESC NULLS LAST,s.id)=1''')
        con.execute(f'''CREATE TEMP TABLE outside_brands AS SELECT source_record_key AS silver_id,lower(trim(brand_name)) AS brand
            FROM read_parquet({q(config['silver'])})''' if domain=='fragrance' else f'''CREATE TEMP TABLE outside_brands AS SELECT observation_key AS silver_id,lower(trim(brand_name)) AS brand FROM read_parquet({q(config['silver'])})''')
        pools={'in_pedia':records(con,'SELECT * FROM pool_inside ORDER BY item_key'),
            'outside_pedia':records(con,'SELECT o.*,b.brand FROM pool_outside o JOIN outside_brands b USING(silver_id) ORDER BY item_key')}
        approved={(r['silver_id'],r['source_id']):(r['reason'],r['evidence']) for r in records(con,'SELECT * FROM approved')}
        originals={number:pq.read_table(OLD/domain/f'subset-{number}/selection.parquet').to_pylist() for number in (1,2,3)}
        used_ids={r['silver_id'] for rows in originals.values() for r in rows}
        used_items={r['item_key'] for rows in originals.values() for r in rows}
        for number in (1,2,3):
            selected=[]
            added_counts={}
            for group,count in QUOTAS.items():
                kept=[r.copy() for r in originals[number] if r['stratum']==group and (r['silver_id'],r['source_id']) in approved]
                for row in kept:row['semantic_reason'],row['semantic_evidence']=approved[(row['silver_id'],row['source_id'])]
                need=count-len(kept)
                eligible=[r.copy() for r in pools[group] if r['silver_id'] not in used_ids and r['item_key'] not in used_items]
                assert len(eligible)>=need
                if group=='outside_pedia':
                    for row in eligible:row['entity_id']=row['item_key']
                replacements=choose(eligible,need,domain,1000+number)
                assert len(replacements)==need
                for row in replacements:
                    row.update(stratum=group,in_pedia=group=='in_pedia',subset=number)
                    if group=='outside_pedia':row['entity_id']=None
                    used_ids.add(row['silver_id']);used_items.add(row['item_key'])
                selected.extend(kept+replacements)
                added_counts[group]=need
            assert len({r['silver_id'] for r in selected})==len({r['item_key'] for r in selected})==5000
            models=defaultdict(list)
            for r in selected:
                if r['model_id']:models[r['model_id']].append(r)
            summary=json.loads((OLD/domain/f'subset-{number}/manifest.json').read_text())
            summary.update(format='pedia_stratified_silver_subset/v3',content_checked=True,
                selection_sha256=hashlib.sha256(json.dumps(sorted((r['silver_id'],r['stratum']) for r in selected)).encode()).hexdigest(),
                semantic_rules_sha256=sha(TASK/'semantic_guard.py'),replacement_counts=added_counts,
                retained_rows=5000-sum(added_counts.values()),source_previous_subset=str(OLD/domain/f'subset-{number}'),
                brand_labels=len({r['brand'] for r in selected if r['brand']}),
                sources=len({r['source_id'] for r in selected}),models=len(models),
                models_with_multiple_listings=sum(len(v)>1 for v in models.values()),
                models_with_multiple_sources=sum(len({r['source_id'] for r in v})>1 for v in models.values()),
                models_with_sibling_variants=sum(len({r['entity_id'] for r in v if r['entity_type']=='ProductVariant'})>1 for v in models.values()),
                semantic_acceptance_counts=dict(Counter(r['semantic_reason'] for r in selected)))
            for group in QUOTAS:
                rows=[r for r in selected if r['stratum']==group]
                summary['strata'][group]={'rows':len(rows),'brand_labels':len({r['brand'] for r in rows if r['brand']}),
                    'sources':len({r['source_id'] for r in rows})}
            print('SELECTED',domain,number,'replacements',added_counts,flush=True)
            prepared.append((pa.Table.from_pylist(selected),summary,{r['silver_id'] for r in selected}))
    all_ids=set()
    all_items=set()
    for selected,_,ids in prepared:
        items=set(selected['item_key'].to_pylist())
        assert not all_ids&ids and not all_items&items
        all_ids.update(ids);all_items.update(items)
    source=pq.ParquetFile(config['silver'])
    writers=[];paths=[]
    for selected,summary,_ in prepared:
        directory=DEST/domain/f"subset-{summary['subset']}"
        directory.mkdir(parents=True,exist_ok=False)
        pq.write_table(selected,directory/'selection.parquet',compression='zstd')
        path=directory/f'{domain}_listings.parquet'
        paths.append(path);writers.append(pq.ParquetWriter(path,source.schema_arrow,compression='zstd'))
    wanted=[pa.array(sorted(ids),type=pa.int64()) for _,_,ids in prepared]
    pending=[[],[],[]];sizes=[0,0,0];written=[0,0,0]
    try:
        for batch in source.iter_batches(batch_size=128,use_threads=False):
            for i in range(3):
                kept=batch.filter(pc.is_in(batch.column(idcol),value_set=wanted[i]))
                if kept.num_rows:pending[i].append(pa.Table.from_batches([kept]));sizes[i]+=kept.num_rows
                if sizes[i]>=512:
                    writers[i].write_table(pa.concat_tables(pending[i]));written[i]+=sizes[i]
                    pending[i]=[];sizes[i]=0
        for i in range(3):
            if sizes[i]:writers[i].write_table(pa.concat_tables(pending[i]));written[i]+=sizes[i]
    finally:
        for writer in writers:writer.close()
    for i,(_,summary,ids) in enumerate(prepared):
        path=paths[i];saved=pq.ParquetFile(path)
        assert written[i]==saved.metadata.num_rows==5000
        assert saved.schema_arrow.equals(source.schema_arrow)
        fields=[idcol,statuscol,'listing_name','description_text','ingredients_text','product_kind','concentration','review_required']
        columns=[c for c in fields if c in saved.schema_arrow.names]
        rows=saved.read(columns=columns).to_pylist()
        assert {r[idcol] for r in rows}==ids
        assert all(r[statuscol]==allowed and r.get('review_required') is not True and decide(domain,r)[0]=='accept' for r in rows)
        summary.update(parquet_sha256=sha(path),parquet_bytes=path.stat().st_size,
            verified_semantic_nonaccept_rows=0,verified_semantic_rows=5000,verified_rows=5000,
            verified_ids=True,verified_schema=True)
        (path.parent/'manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print('SAVED',path,flush=True)
    return [summary for _,summary,_ in prepared]

if __name__=='__main__':
    if DEST.exists():raise SystemExit('Output exists; preserve existing output.')
    config=json.loads((TASK/'stratified-sources.json').read_text())
    releases=json.loads((ROOT/'data/pedia/CURRENT.json').read_text())['releases']
    results={d:build(d,config['domains'][d],releases[d]) for d in ('food','fragrance')}
    (DEST/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
