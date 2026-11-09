"""Copy the two pinned label deliveries through M4R's verified raw cache."""
import hashlib
import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from m4r import config
from m4r.run.raw import fetch_verified

root = Path('/hackaton/data/gold')
root.mkdir(parents=True, exist_ok=True)
profile = config.profile('team')
sources = {
    'food': {
        'uri': 's3://m4r-raw-428156589460/canonical_food_labels/food-final-pedia-labels-v1-20261011/bundle.zip',
        'version_id': '.X4rdeDhIt3BBt.xltoOXvlgBzek9Bbw',
        'sha256': '10ad0da9b6f904182257a1d74cb50d2d5948d6a9f8003bc46fc0832c32ec7717',
        'bytes': 22467383,
    },
    'fragrance': {
        'uri': 's3://m4r-raw-428156589460/canonical_fragrance_labels/fragrance-canonical-labels-20261010-v1/bundle.zip',
        'version_id': 'WLcSHUlppbxtkWyQz.yfAuWHxyHz5x7J',
        'sha256': 'fb5a0f5fa5c7c4fca498a7cbaeca77f9e031e78774978b7cd4e1b329e75fbd5a',
        'bytes': 7624671,
    },
}
for domain, source in sources.items():
    destination = root / domain
    destination.mkdir(exist_ok=False)
    cached, mode = fetch_verified(source, profile)
    archive = destination / 'bundle.zip'
    shutil.copyfile(cached, archive)
    assert archive.stat().st_size == source['bytes']
    assert hashlib.file_digest(archive.open('rb'), 'sha256').hexdigest() == source['sha256']
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError(f'Unsafe archive member: {member.filename}')
        bundle.extractall(destination)
        source['members'] = [
            {'path': item.filename, 'bytes': item.file_size}
            for item in bundle.infolist() if not item.is_dir()
        ]
    source['cache_result'] = mode
    print(json.dumps({'domain': domain, 'cache': mode, 'members': source['members']}), flush=True)
record = {'hydrated_utc': datetime.now(timezone.utc).isoformat(), 'sources': sources}
(root / 'hydration.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
print('Hydration complete; both archive SHA-256 values verified.')
