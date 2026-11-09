"""Inspect included source rows and retain positive product-evidence decisions."""
from collections import Counter
import json
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq
from semantic_guard import decide

task=Path('/hackaton/tasks/s3-gold-check-20261109')
config=json.loads((task/'stratified-sources.json').read_text())
current=pq.read_table(task/'raw-audit-inputs.parquet').to_pylist()
current_by_domain={d:{r['silver_id']:r['subset'] for r in current if r['domain']==d} for d in ('food','fragrance')}
reports={}
rejected_current=[]
schema=pa.schema([('silver_id',pa.int64()),('source_id',pa.string()),('decision',pa.string()),
                  ('reason',pa.string()),('evidence',pa.string())])
for domain in ('food','fragrance'):
    path=config['domains'][domain]['silver']
    idcol='observation_key' if domain=='food' else 'source_record_key'
    statuscol,allowed=('food_scope_status','confirmed') if domain=='food' else ('perfume_status','included')
    parquet=pq.ParquetFile(path)
    fields=[idcol,statuscol,'source_id','listing_name','description_text','ingredients_text',
            'product_kind','concentration','review_required','listing_url']
    columns=[c for c in fields if c in parquet.schema_arrow.names]
    decisions=Counter()
    reasons=Counter()
    old_decisions=Counter()
    old_seen=set()
    dest=task/f'{domain}-semantic-eligibility.parquet'
    with pq.ParquetWriter(dest,schema,compression='zstd') as writer:
        for batch in parquet.iter_batches(batch_size=1024,columns=columns,use_threads=False):
            entries=[]
            for row in batch.to_pylist():
                if row[statuscol]!=allowed or row.get('review_required') is True:continue
                decision,reason,evidence=decide(domain,row)
                decisions[decision]+=1
                reasons[reason]+=1
                sid=row[idcol]
                entries.append({'silver_id':sid,'source_id':row['source_id'],'decision':decision,'reason':reason,'evidence':evidence})
                if sid in current_by_domain[domain]:
                    old_seen.add(sid)
                    old_decisions[decision]+=1
                    if decision!='accept':
                        rejected_current.append({'domain':domain,'subset':current_by_domain[domain][sid],
                            'silver_id':str(sid),'source_id':row['source_id'],'listing_name':row['listing_name'],
                            'description_excerpt':(row.get('description_text') or '')[:1800],
                            'listing_url':row.get('listing_url'),'decision':decision,'reason':reason,'evidence':evidence})
            if entries:writer.write_table(pa.Table.from_pylist(entries,schema=schema))
    assert old_seen==set(current_by_domain[domain])
    reports[domain]={'included_source_decisions':dict(decisions),'reasons':dict(reasons),
        'current_subset_decisions':dict(old_decisions),'current_rows_reviewed':len(old_seen)}
    print(domain,json.dumps(reports[domain]),flush=True)
(task/'semantic-source-review.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
(task/'current-content-rejections.json').write_text(json.dumps(rejected_current,indent=2),encoding='utf-8')
print('REJECTED_OR_HELD_CURRENT',len(rejected_current),flush=True)
