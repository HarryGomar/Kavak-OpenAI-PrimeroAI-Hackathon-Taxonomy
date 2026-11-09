"""Check preserved delivery code without executing any extraction or upload."""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    inventory = json.loads((root / 'source-inventory.json').read_text('utf-8'))
    checks = []
    for entry in inventory['files']:
        path = root / entry['copy']
        content = path.read_bytes()
        assert hashlib.sha256(content).hexdigest() == entry['sha256'], path
        if path.suffix == '.py':
            ast.parse(content.decode('utf-8-sig'), filename=str(path))
        check = {'path': entry['copy'], 'sha256': entry['sha256'],
                 'syntax': 'PASS' if path.suffix == '.py' else 'checked separately'}
        if args.workspace:
            source = args.workspace / entry['source']
            assert source.read_bytes() == content, source
            check['original_task_copy'] = 'identical'
        checks.append(check)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({'status': 'PASS', 'files': checks,
                                      'delivery_scripts_executed': False}, indent=2),
                           encoding='utf-8')
    print(f'PASS: {len(checks)} delivery code files; report: {args.report}')


if __name__ == '__main__':
    main()
