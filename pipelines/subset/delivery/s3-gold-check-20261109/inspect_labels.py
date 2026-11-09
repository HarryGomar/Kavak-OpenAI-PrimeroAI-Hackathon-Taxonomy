"""Inspect hydrated Parquet files locally without modifying their contents."""
import hashlib
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq

root = Path('/hackaton/data/gold')
report = {}
for domain in ('food', 'fragrance'):
    folder = root / domain
    manifest = json.loads((folder / 'manifest.json').read_text())
    print(domain, 'release', manifest['release'])
    files = []
    for path in sorted(folder.glob('*.parquet')):
        parquet = pq.ParquetFile(path)
        info = {
            'file': path.name,
            'rows': parquet.metadata.num_rows,
            'bytes': path.stat().st_size,
            'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest(),
            'schema': [{'column': field.name, 'type': str(field.type)} for field in parquet.schema_arrow],
        }
        declared = manifest['tables'][path.stem]
        info['manifest_verified'] = (
            info['sha256'] == declared['sha256']
            and info['rows'] == declared['rows']
            and info['bytes'] == declared['bytes']
        )
        if not info['manifest_verified']:
            raise ValueError(f'Manifest mismatch: {path}')
        is_labels = path.stem.endswith('_labels') or path.stem == 'label_corrections'
        if is_labels:
            rows = parquet.read().to_pylist()
            info['samples'] = rows[:2] + rows[-2:]
            info['categorical_values'] = {
                field: dict(Counter(str(row[field]) for row in rows))
                for field in parquet.schema_arrow.names
                if field in ('review_disposition', 'evidence_status',
                             'heterogeneity', 'relation_kind',
                             'correction_type', 'status', 'level', 'view')
            }
            if 'cluster_id' in parquet.schema_arrow.names:
                keys = [(row.get('hierarchy_id'), row['cluster_id']) for row in rows]
                info['distinct_hierarchy_cluster_keys'] = len(set(keys))
            if 'label' in parquet.schema_arrow.names:
                info['null_or_blank_labels'] = sum(not row['label'] or not row['label'].strip() for row in rows)
            print(path.name, info['rows'], 'rows', json.dumps(info['categorical_values']))
        else:
            print(path.name, info['rows'], 'rows')
            info['samples'] = parquet.read_row_group(0).slice(0, 2).to_pylist() if info['rows'] else []
        files.append(info)
    labels = [f for f in files if f['file'].endswith('_labels.parquet')]
    joins = []
    for info in labels:
        prefix = info['file'].removesuffix('_labels.parquet')
        key_columns = ['statistics_id', 'hierarchy_id', 'cluster_id']
        def keys(suffix):
            return [tuple(row[column] for column in key_columns)
                    for row in pq.read_table(folder / f'{prefix}_{suffix}.parquet', columns=key_columns).to_pylist()]
        label_keys = keys('labels')
        profile_keys = keys('cluster_profiles')
        term_keys = set(keys('cluster_terms'))
        joins.append({
            'view': prefix,
            'unique_label_keys': len(label_keys) == len(set(label_keys)),
            'unique_profile_keys': len(profile_keys) == len(set(profile_keys)),
            'label_profile_keys_equal': set(label_keys) == set(profile_keys),
            'term_keys_without_labels': len(term_keys - set(label_keys)),
        })
    review_counts = Counter()
    for info in labels:
        review_counts.update(info['categorical_values'].get('review_disposition', {}))
    report[domain] = {
        'release': manifest['release'],
        'label_rows': sum(info['rows'] for info in labels),
        'review_disposition': dict(review_counts),
        'relationship_review_complete': manifest['provenance'].get('relationship_review_complete'),
        'all_members_match_manifest': all(info['manifest_verified'] for info in files),
        'cluster_joins': joins,
        'parquet_files': files,
    }
    print('TOTAL', domain, report[domain]['label_rows'], dict(review_counts))
(root / 'inspection.json').write_text(json.dumps(report, indent=2, default=str), encoding='utf-8')
