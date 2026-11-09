"""Inspect the actual Drive subsets and stage their IDs and outside-Pedia evidence."""
from pathlib import Path
import hashlib
import json
import pyarrow as pa
import pyarrow.parquet as pq

root=Path('C:/Users/eduar/Desktop/HACKATON')
task=root/'tasks/s3-gold-check-20261109'
report=json.loads((task/'drive-uniqueness-report.json').read_text())
requests=[]
outside=[]
fields=['source_id','listing_name','listing_url','brand_name','description_text','market',
        'source_listing_id','source_variant_id','listing_key','source_product_id','package_text',
        'volume_ml','concentration','gender','product_form','product_kind','bundle_kind',
        'ingredients_text','flavor_text','food_form_text','net_quantity','net_quantity_unit',
        'pack_count','identifiers_json','issues_json','field_evidence_json','category_text',
        'category_path_json','categories_json']
for domain,ds in report['domains'].items():
    for n,s in enumerate(ds['subsets'],1):
        path=Path(s['path'])
        with path.open('rb') as stream:
            assert hashlib.file_digest(stream,'sha256').hexdigest()==s['sha256']
        parquet=pq.ParquetFile(path)
        idx='observation_key' if domain=='food' else 'source_record_key'
        columns=[idx]+[k for k in fields if k in parquet.schema_arrow.names]
        rows=parquet.read(columns=columns).to_pylist()
        selection=path.parent/'selection.parquet'
        strata={r['silver_id']:r['stratum'] for r in pq.read_table(selection).to_pylist()} if selection.exists() else {}
        for row in rows:
            requests.append({'domain':domain,'subset':n,'silver_id':row[idx],'source_id':row['source_id']})
            if strata.get(row[idx])!='outside_pedia':
                continue
            record={k:row.get(k) for k in fields if k in row}
            record.update(domain=domain,subset=n,silver_id=str(row[idx]))
            outside.append(record)
        print(domain,n,len(rows),'outside',sum(strata.get(r[idx])=='outside_pedia' for r in rows))
pq.write_table(pa.Table.from_pylist(requests),task/'distribution-inputs.parquet')
(task/'outside-pedia-cases.json').write_text(json.dumps(outside,indent=2,default=str),encoding='utf-8')
for domain in ('food','fragrance'):
    print('CASES',domain)
    for row in [r for r in outside if r['domain']==domain][:40]:
        print(json.dumps({k:row[k] for k in ['subset','silver_id','source_id','brand_name','listing_name']},ensure_ascii=True))
