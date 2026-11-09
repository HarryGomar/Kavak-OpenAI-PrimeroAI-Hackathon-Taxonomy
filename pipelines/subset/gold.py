"""Split original Gold label tables into row batches; retain native join tables."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

import pyarrow.parquet as pq


def sha256(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def extract_domain(domain, entry, out, size):
    report = {'gold_release': entry['gold_release'], 'gold_rows': 0, 'batches': 0, 'views': {}}
    for view, files in sorted(entry['views'].items()):
        if sha256(files['labels']) != files['labels_sha256']:
            raise ValueError(f'{domain}/{view}: original Gold checksum differs')
        labels = pq.read_table(files['labels'])
        destination = out / domain / view
        destination.mkdir(parents=True)
        # Native mapping tables are copied once per view, without expanding Gold rows.
        join_dir = destination / 'join_tables'
        join_dir.mkdir()
        mappings = {}
        for field in ('assignments', 'products', 'members'):
            if field not in files:
                continue
            target = join_dir / f'{field}.parquet'
            shutil.copyfile(files[field], target)
            mappings[field] = {
                'path': str(target.relative_to(out)),
                'source': files.get('original_' + field, files[field]),
                'rows': pq.read_metadata(target).num_rows,
                'sha256': sha256(target),
            }
        batches = []
        for offset in range(0, labels.num_rows, size):
            number = offset // size + 1
            path = destination / f'batch-{number:05d}.parquet'
            batch = labels.slice(offset, size)
            # Arrow slicing retains every original field, value and schema metadata.
            pq.write_table(batch, path, compression='zstd')
            batches.append({'path': str(path.relative_to(out)), 'rows': batch.num_rows,
                            'source_row_offset': offset, 'sha256': sha256(path)})
        manifest = {
            'format': 'original_gold_row_batches/v2', 'domain': domain, 'view': view,
            'gold_release': entry['gold_release'], 'gold_rows': labels.num_rows,
            'batch_size': size, 'batches': batches, 'join_tables': mappings,
            'source': files.get('original_labels', files['labels']),
            'source_sha256': files['labels_sha256'],
            'all_original_columns_preserved': True,
            'ordering': 'Original source row order; disjoint slices covering the entire table.',
            'relationship': ('Gold (hierarchy_id,cluster_id) -> assignments.id -> Silver observation_key'
                             if view == 'listing' else
                             'Gold (hierarchy_id,cluster_id) -> assignments.product_key -> products.product_id -> members.silver_id -> Silver observation ID'),
            'cardinality': 'A Gold row labels a cluster, so it can reach many Silver listings. A listing can have Gold labels at multiple hierarchy levels and views.',
        }
        (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        summary = {'gold_rows': labels.num_rows, 'batches': len(batches),
                   'last_batch_rows': batches[-1]['rows'] if batches else 0}
        report['views'][view] = summary
        report['gold_rows'] += labels.num_rows
        report['batches'] += len(batches)
        print(json.dumps({'domain': domain, 'view': view, **summary}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--size', default=500, type=int)
    parser.add_argument('--domain', choices=['food', 'fragrance', 'both'], default='both')
    args = parser.parse_args()
    if args.size <= 0:
        parser.error('size must be positive')
    if args.out.exists():
        parser.error('Output exists; choose a new directory')
    config = json.loads(args.sources.read_text('utf-8-sig'))
    domains = ('food', 'fragrance') if args.domain == 'both' else (args.domain,)
    reports = {domain: extract_domain(domain, config['domains'][domain], args.out, args.size)
               for domain in domains}
    result = {'format': 'original_gold_row_batches/v2', 'batch_size': args.size,
              'gold_rows': sum(r['gold_rows'] for r in reports.values()),
              'batches': sum(r['batches'] for r in reports.values()), 'domains': reports}
    (args.out / 'report.json').write_text(json.dumps(result, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
