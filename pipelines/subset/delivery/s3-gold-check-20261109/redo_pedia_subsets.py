"""Rebuild all six Silver subsets: 4500 placed and 500 absent, without Gold inputs."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import duckdb
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq
from make_stratified_subsets import prepare_candidates, choose, sha, q, records

ROOT=Path('/hackaton')
TASK=ROOT/'tasks/s3-gold-check-20261109'
DEST=ROOT/'data/subsets/pedia-4500-outside-500-v2'
SEEDS=[42,73,97]
QUOTAS={'in_pedia':4500,'outside_pedia':500}

def build(domain,config,release,plan_only):
    idcol='observation_key' if domain=='food' else 'source_record_key'
    statuscol,allowed=('food_scope_status','confirmed') if domain=='food' else ('perfume_status','included')
    prepared=[]
    with duckdb.connect(config={'threads':2,'memory_limit':'2GB','preserve_insertion_order':False}) as con:
        conflicts=prepare_candidates(con,domain,config,release)
        review_filtered=0
        if domain=='fragrance':
            con.execute('CREATE TEMP TABLE review_ids AS SELECT source_record_key AS id FROM read_parquet(?) WHERE review_required IS TRUE',[config['silver']])
            review_filtered=con.execute('SELECT count(*) FROM silver JOIN review_ids USING(id)').fetchall()[0][0]
            con.execute('DELETE FROM silver WHERE id IN (SELECT id FROM review_ids)')
            con.execute('DELETE FROM candidates WHERE silver_id NOT IN (SELECT id FROM silver)')
        con.execute("CREATE TEMP TABLE all_p AS SELECT *,try_cast(substr(mention_id,5) AS BIGINT) AS observation_id FROM graph.placement")
        con.execute('''CREATE TEMP TABLE all_links AS
            SELECT p.mention_id,s.id AS silver_id FROM all_p p JOIN silver s ON p.observation_id=s.id AND p.source_id=s.source_id
            UNION SELECT p.mention_id,s.id FROM all_p p JOIN legacy m ON m.mention_id=p.observation_id
            JOIN silver s ON s.id=m.silver_id AND s.source_id=m.source_id AND s.listing_key=m.listing_key''')
        con.execute('CREATE TEMP TABLE pedia_items AS SELECT DISTINCT n.item_key FROM all_links p JOIN native n ON p.silver_id=n.id')
        con.execute(f'''CREATE TEMP TABLE outside AS SELECT n.item_key,s.id AS silver_id,s.source_id,s.market,s.listing_name,
            lower(trim(b.brand_name)) AS brand,NULL::VARCHAR AS model_id,NULL::VARCHAR AS entity_id,
            NULL::VARCHAR AS entity_type,NULL::VARCHAR AS mention_id,NULL::VARCHAR AS level,NULL::VARCHAR AS outcome,
            'absent_from_pinned_release'::VARCHAR AS join_method
            FROM silver s JOIN native n ON n.id=s.id AND n.source_id=s.source_id AND n.assembly=s.assembly
            JOIN read_parquet({q(config['silver'])}) b ON b.{idcol}=s.id
            WHERE n.item_key NOT IN (SELECT item_key FROM pedia_items)
            QUALIFY row_number() OVER(PARTITION BY n.item_key ORDER BY s.observed_at DESC NULLS LAST,s.id)=1''')
        pools={'in_pedia':records(con,'SELECT * FROM candidates ORDER BY item_key'),
               'outside_pedia':records(con,'SELECT * FROM outside ORDER BY item_key')}
        used_ids=set()
        used_items=set()
        for number,seed in enumerate(SEEDS,1):
            picked=[]
            strata={}
            for stratum,count in QUOTAS.items():
                eligible=[r.copy() for r in pools[stratum] if r['silver_id'] not in used_ids and r['item_key'] not in used_items]
                assert len(eligible)>=count,(domain,number,stratum,len(eligible))
                if stratum=='outside_pedia':
                    for row in eligible:row['entity_id']=row['item_key']
                rows=choose(eligible,count,domain,seed)
                assert len(rows)==count
                for row in rows:
                    row.update(stratum=stratum,in_pedia=stratum=='in_pedia',subset=number)
                    if stratum=='outside_pedia':row['entity_id']=None
                strata[stratum]={'rows':len(rows),'eligible':len(eligible),
                    'brand_labels':len({r['brand'] for r in rows if r['brand']}),
                    'sources':len({r['source_id'] for r in rows})}
                picked.extend(rows)
            ids={r['silver_id'] for r in picked}
            items={r['item_key'] for r in picked}
            assert len(ids)==len(items)==5000
            assert not ids&used_ids and not items&used_items
            used_ids.update(ids)
            used_items.update(items)
            selected=pa.Table.from_pylist(picked)
            con.register('selected',selected)
            assert con.execute("SELECT count(*) FROM selected JOIN pedia_items USING(item_key) WHERE NOT in_pedia").fetchall()[0][0]==0
            con.unregister('selected')
            models=defaultdict(list)
            for row in picked:
                if row['model_id']:models[row['model_id']].append(row)
            summary={'format':'pedia_stratified_silver_subset/v2','domain':domain,'subset':number,
                'rows':5000,'seed':seed,'gold_inputs_used':False,'strata':strata,
                'classification_column':statuscol,'allowed_classification':allowed,
                'review_required_true_excluded':domain=='fragrance','review_required_rows_filtered_from_pool':review_filtered,
                'silver_source':config['original_silver'],'silver_snapshot':config['silver_snapshot'],
                'pedia_release':release['id'],'pedia_release_sha256':release['sha256'],
                'pedia_graph_manifest_sha256':release['layers']['graph']['manifest_sha256'],
                'outside_definition':'No exact or verified bridge placement, including unplaced outcomes, for the native listing in the pinned Pedia graph. Brand or model can already exist.',
                'brand_labels':len({r['brand'] for r in picked if r['brand']}),
                'sources':len({r['source_id'] for r in picked}),
                'models':len(models),
                'models_with_multiple_listings':sum(len(rows)>1 for rows in models.values()),
                'models_with_multiple_sources':sum(len({r['source_id'] for r in rows})>1 for rows in models.values()),
                'models_with_sibling_variants':sum(len({r['entity_id'] for r in rows if r['entity_type']=='ProductVariant'})>1 for rows in models.values()),
                'pedia_identity_conflicts_excluded':conflicts,'all_silver_columns_preserved':True,
                'selection_sha256':hashlib.sha256(json.dumps(sorted((r['silver_id'],r['stratum']) for r in picked)).encode()).hexdigest()}
            print(json.dumps(summary),flush=True)
            prepared.append((selected,summary,ids))
        assert len(used_ids)==15000
    if plan_only:return [summary for _,summary,_ in prepared]
    source=pq.ParquetFile(config['silver'])
    writers=[]
    paths=[]
    for selected,summary,ids in prepared:
        folder=DEST/domain/f"subset-{summary['subset']}"
        folder.mkdir(parents=True,exist_ok=False)
        pq.write_table(selected,folder/'selection.parquet',compression='zstd')
        path=folder/f'{domain}_listings.parquet'
        paths.append(path)
        writers.append(pq.ParquetWriter(path,source.schema_arrow,compression='zstd'))
    wanted=[pa.array(sorted(ids),type=pa.int64()) for _,_,ids in prepared]
    pending=[[],[],[]]
    pending_rows=[0,0,0]
    written=[0,0,0]
    try:
        for batch in source.iter_batches(batch_size=128,use_threads=False):
            for i in range(3):
                kept=batch.filter(pc.is_in(batch.column(idcol),value_set=wanted[i]))
                if kept.num_rows:
                    pending[i].append(pa.Table.from_batches([kept]))
                    pending_rows[i]+=kept.num_rows
                if pending_rows[i]>=512:
                    writers[i].write_table(pa.concat_tables(pending[i]))
                    written[i]+=pending_rows[i]
                    pending[i]=[]
                    pending_rows[i]=0
        for i in range(3):
            if pending_rows[i]:
                writers[i].write_table(pa.concat_tables(pending[i]))
                written[i]+=pending_rows[i]
    finally:
        for writer in writers:writer.close()
    for i,(_,summary,expected_ids) in enumerate(prepared):
        path=paths[i]
        saved=pq.ParquetFile(path)
        assert written[i]==saved.metadata.num_rows==5000
        assert saved.schema_arrow.equals(source.schema_arrow)
        cols=[idcol,statuscol]+(['review_required'] if domain=='fragrance' else [])
        rows=saved.read(columns=cols).to_pylist()
        assert {r[idcol] for r in rows}==expected_ids
        assert Counter(r[statuscol] for r in rows)=={allowed:5000}
        if domain=='fragrance':assert all(r['review_required'] is not True for r in rows)
        summary.update(parquet_sha256=sha(path),parquet_bytes=path.stat().st_size,
            verified_rows=5000,verified_schema=True,verified_ids=True,
            classification_counts={allowed:5000},column_count=len(source.schema_arrow))
        (path.parent/'manifest.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print('SAVED',path,flush=True)
    return [summary for _,summary,_ in prepared]

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-only',action='store_true')
    args=parser.parse_args()
    if not args.plan_only and DEST.exists():raise SystemExit('Output exists; preserve prior output.')
    config=json.loads((TASK/'stratified-sources.json').read_text())
    releases=json.loads((ROOT/'data/pedia/CURRENT.json').read_text())['releases']
    summary={d:build(d,config['domains'][d],releases[d],args.plan_only) for d in ('food','fragrance')}
    path=TASK/'redo-4500-500-plan.json' if args.plan_only else DEST/'summary.json'
    path.write_text(json.dumps(summary,indent=2),encoding='utf-8')
