"""Find existing catalog context for outside listings; candidates are not adjudicated labels."""
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import html
import json
from pathlib import Path
import re
import unicodedata
import pyarrow.parquet as pq

task=Path('C:/Users/eduar/Desktop/HACKATON/tasks/s3-gold-check-20261109')
cases=json.loads((task/'outside-pedia-cases.json').read_text())
def norm(text):
    text=html.unescape(re.sub('<[^>]+>',' ',text or ''))
    text=unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode().casefold()
    return ' '.join(re.findall('[a-z0-9]+',text))
for domain in ('food','fragrance'):
    entities=pq.read_table(task/f'{domain}-pedia-entities.parquet').to_pylist()
    aliases=pq.read_table(task/f'{domain}-pedia-aliases.parquet').to_pylist()
    by_id={e['entity_id']:e for e in entities}
    by_brand=defaultdict(list)
    brand_lookup=defaultdict(set)
    labels=defaultdict(list)
    for entity in entities:
        by_brand[entity['brand']].append(entity)
        brand_lookup[norm(entity['brand'])].add(entity['brand'])
        if entity['type']=='Brand':
            brand_lookup[norm(entity['label'])].add(entity['brand'])
            brand_lookup[norm(entity.get('display'))].add(entity['brand'])
        for name in (entity['label'],entity.get('display')):
            if name: labels[entity['entity_id']].append(norm(name))
    for alias in aliases:
        e=by_id.get(alias['entity_id'])
        if not e:continue
        if e['type']=='Brand':
            brand_lookup[norm(alias['raw'])].add(e['brand'])
        else:
            labels[e['entity_id']].append(norm(alias['raw']))
    for row in cases:
        if row['domain']!=domain:continue
        brand=norm(row['brand_name'])
        matches=sorted(brand_lookup.get(brand,set())) if brand else []
        row['normalized_source_brand']=brand
        row['exact_brand_candidates']=matches
        row['brand_lookup_status']='exact_name_or_alias' if matches else 'source_brand_missing' if not brand else 'no_exact_brand_name_or_alias'
        title=norm(row['listing_name'])
        stripped=title[len(brand):].strip() if brand and title.startswith(brand+' ') else title
        candidates=[]
        exact=[]
        for matched in matches:
            for entity in by_brand[matched]:
                if entity['type'] not in ('ProductModel','ProductVariant','ProductFamily','GiftSet'):continue
                forms=list(set(labels[entity['entity_id']]))
                is_exact=any(form==stripped or form==title for form in forms if form)
                score=max((max(SequenceMatcher(None,stripped,form).ratio(),
                    len(set(stripped.split())&set(form.split()))/max(1,len(set(stripped.split())|set(form.split()))))
                    for form in forms if form),default=0)
                record={k:entity.get(k) for k in ['entity_id','brand','type','label','node_id']}
                record.update(name_similarity=round(score,3),exact_name_or_alias=is_exact)
                if is_exact:exact.append(record)
                candidates.append(record)
        row['exact_product_name_candidates']=exact
        row['nearby_catalog_candidates']=sorted(candidates,key=lambda e:(-e['name_similarity'],e['entity_id']))[:3]
    rows=[c for c in cases if c['domain']==domain]
    print('SUMMARY',domain,dict(Counter(c['brand_lookup_status'] for c in rows)),
          'exact_product_cases',sum(bool(c['exact_product_name_candidates']) for c in rows))
    wanted=['Chomps','Darrell Lea','Maggi','Mother','Simple Mills','RYZE','KANDYHAUS','Ballard','AFIA','Daylily','Lattafa','Afnan','Khadlaj','Ajmal','Rasasi','Ceremonia','Bond & Grace','Labnatur','Sewrra']
    for row in rows:
        if not any(w.casefold() in (row['brand_name'] or '').casefold() for w in wanted):continue
        print(json.dumps({k:row.get(k) for k in ['domain','subset','silver_id','brand_name','listing_name','product_kind','listing_url','exact_brand_candidates','exact_product_name_candidates','nearby_catalog_candidates']},ensure_ascii=True))
(task/'outside-pedia-cases-enriched.json').write_text(json.dumps(cases,indent=2),encoding='utf-8')
