import json
import zipfile
from pathlib import Path
import pyarrow.parquet as pq

root = Path('/hackaton')
config = json.loads((root / 'tasks/s3-gold-check-20261109/overlap-inputs.json').read_text())
def local(value):
    return Path(value.replace('\\', '/').replace('C:/Users/eduar/Desktop/M4M/04_Retail/M4R_REAL/', '/m4r/').replace('/work/', '/m4r/'))
for domain, view in [('food','brand_v1'),('food','listing'),('fragrance','brand_v1')]:
    print(domain, view)
    for stage, directory in config[domain][view].items():
        if stage not in ('catalog','embeddings','mantis','binary'): continue
        for path in sorted((local(directory) / 'tables').glob('*.parquet')):
            if path.stem not in ('products','members','assignments','contributions','listings','mentions','hierarchies'): continue
            parquet = pq.ParquetFile(path)
            print(stage, path.name, parquet.metadata.num_rows, parquet.schema_arrow.names)
            print('EXAMPLE', json.dumps(parquet.read_row_group(0).slice(0,1).to_pylist(), default=str)[:1600])
for domain in ('food','fragrance'):
    path = root / f'data/subsets/silver-n5000-seed42/{domain}/{domain}_listings.parquet'
    print('SUBSET',domain,pq.ParquetFile(path).schema_arrow.names)
archive = Path('/m4r/data/5-view-2467/canonical-final-pedia/food/inputs/mapping/71fc287a300d0f82f291fe3a62d514c85b4b71232f8057e6b1a884608f4bf71d/listing-mapping.zip')
with zipfile.ZipFile(archive) as bundle:
    print('MAPPING_ZIP',bundle.namelist())
