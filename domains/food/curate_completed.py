"""Canonical postmeasurement diagnostics for completed Food development loops."""
from __future__ import annotations

import argparse
from pathlib import Path

from domains.food.place_paths import read, rows
from taxo import distill
from taxo.codex_cli import fingerprint, write
from taxo.gate import decide


def execute(root: Path, name: str):
    out = root / name
    report = read(out / 'loop-report.json')
    if report['status'] != 'completed_integrated_development_cycle':
        raise ValueError('Curation requires completed actual integrated measurements')
    before = Path(read(out / 'retained-state-before.json')['baseline_output']['path'])
    old_paths = {r['id']: r['path'] for r in rows(before / 'placements.jsonl')}
    comparisons = {}
    for label, arm in report['component_and_integrated_comparisons'].items():
        folder = Path(arm['output'])
        manifest = read(folder / 'manifest.json')
        paths = {r['id']: r['path'] for r in rows(folder / 'placements.jsonl')}
        if manifest['status'] != 'completed' or paths.keys() != old_paths.keys():
            raise ValueError('Curation refuses incomplete or mismatched pipeline membership')
        paired = arm['paired']['exact']
        touched = sum(paths[k] != old_paths[k] for k in paths)
        # Match the existing Food full_loop adapter: exact gains/regressions are
        # supplied to the unchanged gate, without reinterpreting label classes.
        comparison = {'before': {'exact': arm['before']['identity_path_exact']},
                      'after': {'exact': arm['after']['identity_path_exact']},
                      'touched': touched, 'better': paired['gains'],
                      'worse': paired['regressions']}
        agent_before = len([r for r in rows(before / 'placements.jsonl')
                            if r.get('by') == 'food_source_path_placer']) / len(paths)
        agent_after = arm['routed'] / len(paths)
        passed, reasons = decide(comparison, agent_before, agent_after)
        comparisons[label] = {'canonical_function': 'taxo.gate.decide',
            'development_only': True, 'sealed_read_executed': False,
            'checks_pass': passed, 'reasons': reasons, **comparison,
            'agent_before': agent_before, 'agent_after': agent_after,
            'advance_eligible': passed and arm['keep_for_development']}
    proposals = []
    for proposal in report.get('pipeline_proposals', []):
        kind = proposal['kind']
        proposals.append({'id': proposal['id'], 'kind': kind,
            'canonical_curator_executed': False, 'production_admission': False,
            'reason': ('No declared check qualification and gold shadow caught/false-reject '
                       'counts; admission not executed' if kind in ('code_rule', 'new_check') else
                       'Not a deterministic RuleSpec check; curator.admit is not applicable')})
    native = [p for p in distill.ROUNDS_DIR.joinpath('food').glob('*.json')
              if read(p).get('label') == name + ' integrated']
    if len(native) != 1:
        raise ValueError('Expected exactly one existing native round record for this loop')
    record = read(native[0])
    lessons = distill.lessons({record['id']: record})
    if record['keep'] is not None or any(x['status'] == 'active' for x in lessons):
        raise ValueError('Development evidence cannot activate production lessons')
    result = {'status': 'canonical_development_postmeasurement_completed',
        'pipeline_gates': comparisons, 'rule_curation': proposals,
        'distillation': {'function': 'taxo.distill.lessons', 'record': fingerprint(native[0]),
                         'lessons': lessons, 'reason': 'Ungated native record remains pending'},
        'separate_analyst_calls': 0, 'analysis_role': 'Within the broad pipeline proposer',
        'new_model_calls': 0, 'production_admission': False,
        'advance_eligible': any(x['advance_eligible'] for x in comparisons.values())}
    write(out / 'postmeasurement.json', result)
    write(out / 'postmeasurement-index.json', [fingerprint(out / n) for n in
        ('loop-report.json', 'postmeasurement.json', 'retained-state-before.json')] + [fingerprint(native[0])])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--name', required=True)
    args = parser.parse_args()
    result = execute(args.root, args.name)
    print({'status': result['status'], 'new_model_calls': 0,
           'advance_eligible': result['advance_eligible']})
