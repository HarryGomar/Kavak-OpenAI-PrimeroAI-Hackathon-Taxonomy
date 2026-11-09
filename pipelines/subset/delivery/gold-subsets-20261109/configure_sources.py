import json
from pathlib import Path
root=Path('C:/Users/eduar/Desktop/HACKATON')
config=json.loads((root/'tasks/s3-gold-check-20261109/overlap-inputs.json').read_text())
m4r=Path('C:/Users/eduar/Desktop/M4M/04_Retail/M4R_REAL')
def local(value):
    return Path(value.replace('/work/',str(m4r)+'/'))
out={'domains':{}}
for domain, views in config.items():
    manifest=json.loads((root/f'data/gold/{domain}/manifest.json').read_text())
    v={}
    for view, stages in views.items():
        files={'labels':str(root/f'data/gold/{domain}/{view}_labels.parquet'), 'labels_sha256':manifest['tables'][view+'_labels']['sha256'], 'assignments':str(local(stages.get('mantis') or stages['binary'])/'tables/assignments.parquet')}
        if view!='listing':
            files.update({k:str(local(stages['catalog'])/f'tables/{k}.parquet') for k in ('members','products')})
        for k in ('labels','assignments','members','products'):
            if k in files and not Path(files[k]).is_file():
                raise FileNotFoundError(files[k])
        v[view]=files
    out['domains'][domain]={'release':manifest['release'],'views':v}
(root/'data/gold-sources.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
print({d:list(e['views']) for d,e in out['domains'].items()})
