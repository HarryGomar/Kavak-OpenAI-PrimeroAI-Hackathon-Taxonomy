import json
from pathlib import Path
for domain in ('food','fragrance'):
    p=Path('data/gold')/domain/'manifest.json'
    d=json.loads(p.read_text())
    print('\nDOMAIN',domain,'RELEASE',d.get('release'),'FAMILY',d.get('family'))
    prov=d.get('provenance',{})
    print('PROVENANCE_KEYS',list(prov))
    for key in ('collection','join_contract','label_source','label_authority','labels','annotation_source','labeling','model','human_review'):
        if key not in prov: continue
        value=prov[key]
        if isinstance(value,dict):
            print(key,{k:v for k,v in value.items() if k in ('kind','publication_authority','status','changed_names','new_model_calls','rows','source','model','path','dataset')})
            print(key+'_keys',list(value))
        else: print(key,str(value)[:1800])
    def walk(value,path=''):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in ('model','model_name','model_id','provider','annotation_policy','review_author','annotator','labeler','created_by','label_source','human_reviewed'):
                    print('METADATA',path+'/'+k,str(v)[:500])
                walk(v,path+'/'+k)
        elif isinstance(value,list):
            for i,v in enumerate(value[:2]): walk(v,path+'/'+str(i))
    walk(prov)
