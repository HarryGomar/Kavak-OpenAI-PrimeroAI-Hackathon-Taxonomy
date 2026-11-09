"""Read the six actual RAW files, recompute diversity, and retain every outside case."""
from collections import Counter,defaultdict
import hashlib
import itertools
import json
from pathlib import Path
import unicodedata
import pyarrow as pa
import pyarrow.parquet as pq

TASK=Path('C:/Users/eduar/Desktop/HACKATON/tasks/s3-gold-check-20261109')
DRIVE=Path('G:/.shortcut-targets-by-id/1lo5XQFqwWZ4oV915bOgMLt9KPW0IeTv4/Hackathon-Kavak-OpenAI-Primero/DATA/Listings/RAW')
report=json.loads((DRIVE/'verification-report.json').read_text())
fields=['source_id','brand_name','listing_name','listing_url','description_text','market','listing_key',
        'source_product_id','product_kind','bundle_kind','concentration','gender','volume_ml',
        'package_text','pack_count','net_quantity','net_quantity_unit','food_form_text','flavor_text',
        'ingredients_text','identifiers_json','issues_json','category_text','categories_json']
def brand_key(value):
    return unicodedata.normalize('NFKC',value or '').strip().casefold()
audit={'domains':{},'gold_consulted':False,'all_file_pair_intersections':[]}
outside=[]
inputs=[]
all_sets=[]
for domain in ('food','fragrance'):
    idcol='observation_key' if domain=='food' else 'source_record_key'
    statuscol,allowed=('food_scope_status','confirmed') if domain=='food' else ('perfume_status','included')
    summaries=[]
    for entry in report['domains'][domain]['subsets']:
        path=Path(entry['path'])
        with path.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==entry['sha256']
        parquet=pq.ParquetFile(path)
        cols=[idcol,statuscol]+[k for k in fields if k in parquet.schema_arrow.names]
        if domain=='fragrance':cols+=['review_required']
        rows=parquet.read(columns=cols).to_pylist()
        ids={r[idcol] for r in rows}
        assert len(rows)==len(ids)==5000
        assert Counter(r[statuscol] for r in rows)=={allowed:5000}
        if domain=='fragrance':assert all(r['review_required'] is not True for r in rows)
        selected=pq.read_table(path.parent/'selection.parquet').to_pylist()
        selected_by_id={r['silver_id']:r for r in selected}
        assert set(selected_by_id)==ids
        models=defaultdict(list)
        for r in selected:
            if r['model_id']:models[r['model_id']].append(r)
        number=int(path.parent.name.split('-')[-1])
        summary={'subset':number,'path':path.as_posix(),'rows':5000,
            'in_pedia':sum(r['in_pedia'] for r in selected),'outside_pedia':sum(not r['in_pedia'] for r in selected),
            'source_brand_names':len({brand_key(r['brand_name']) for r in rows if brand_key(r['brand_name'])}),
            'missing_source_brand_rows':sum(not brand_key(r['brand_name']) for r in rows),
            'canonical_pedia_brands':len({r['brand'] for r in selected if r['in_pedia']}),
            'sources':len({r['source_id'] for r in rows}),
            'pedia_models':len(models),
            'pedia_variant_entities':len({r['entity_id'] for r in selected if r['entity_type']=='ProductVariant'}),
            'models_with_multiple_listings':sum(len(v)>1 for v in models.values()),
            'models_with_multiple_sources':sum(len({r['source_id'] for r in v})>1 for v in models.values()),
            'models_with_sibling_variants':sum(len({r['entity_id'] for r in v if r['entity_type']=='ProductVariant'})>1 for v in models.values()),
            'classification_counts':{allowed:5000},'null_listing_ids':0,'duplicates':0}
        assert summary['in_pedia']==4500 and summary['outside_pedia']==500
        summaries.append(summary)
        print(domain,json.dumps(summary))
        for row in rows:
            s=selected_by_id[row[idcol]]
            inputs.append({'domain':domain,'subset':number,'silver_id':row[idcol],'source_id':row['source_id'],
                'item_key':s['item_key'],'claimed_in_pedia':s['in_pedia']})
            if not s['in_pedia']:
                record={k:row.get(k) for k in fields if k in row}
                record.update(domain=domain,subset=number,silver_id=str(row[idcol]))
                outside.append(record)
        all_sets.append((domain,number,ids))
    audit['domains'][domain]={'subsets':summaries,'unique_ids':len(set().union(*(ids for d,_,ids in all_sets if d==domain)))}
for (ld,ln,a),(rd,rn,b) in itertools.combinations(all_sets,2):
    assert not a&b
    audit['all_file_pair_intersections'].append({'left':f'{ld}/subset-{ln}','right':f'{rd}/subset-{rn}','intersection':0})
assert len(outside)==len({r['silver_id'] for r in outside})==3000
pq.write_table(pa.Table.from_pylist(inputs),TASK/'raw-audit-inputs.parquet')
(TASK/'raw-diversity-audit.json').write_text(json.dumps(audit,indent=2),encoding='utf-8')
(TASK/'raw-outside-cases.json').write_text(json.dumps(outside,indent=2,default=str),encoding='utf-8')
for domain in ('food','fragrance'):
    print('EXAMPLES',domain)
    for row in [r for r in outside if r['domain']==domain][:25]:
        print(json.dumps({k:row.get(k) for k in ['subset','silver_id','source_id','brand_name','listing_name']}))
