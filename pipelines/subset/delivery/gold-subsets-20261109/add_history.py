import json
from pathlib import Path
p=Path('data/gold-sources.json')
c=json.loads(p.read_text())
c['domains']['fragrance']['unlabeled_history']=['C:/Users/eduar/Desktop/M4M/04_Retail/M4R_REAL/data/hydrated/team-snapshot-3562/listing_fragrances.listings.parquet']
p.write_text(json.dumps(c,indent=2),encoding='utf-8')
