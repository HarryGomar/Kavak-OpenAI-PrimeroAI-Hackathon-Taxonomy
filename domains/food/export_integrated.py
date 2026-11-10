"""Refresh aggregate-only public evidence for completed integrated Food loops.

Existing baseline, sample provenance, and detailed loops 002-004 are preserved.
No source rows, gold names, proposal prose, prompts, or tool bodies are exported.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from taxo.codex_cli import fingerprint


METRICS = ('rates_denominator', 'identity_path_exact', 'strict_full_path_exact',
           'brand_correct', 'abstentions_all_frozen', 'classes')
COMPONENTS = {'source_extraction_only', 'configuration_only', 'cohort_only', 'placer_only', 'integrated'}
KINDS = {'agentic_rule', 'vocab', 'route', 'code_rule', 'new_check', 'registry',
         'convention_question', 'no_change'}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def metrics(value):
    return {k: value[k] for k in METRICS if k in value}


def numeric_tree(value):
    """Copy aggregate numeric structures without carrying arbitrary string text."""
    if isinstance(value, dict):
        return {k: numeric_tree(v) for k, v in value.items()
                if isinstance(v, (dict, list, int, float, bool)) or v is None}
    if isinstance(value, list):
        return [numeric_tree(v) for v in value if isinstance(v, (dict, list, int, float, bool)) or v is None]
    return value


def profile(card):
    value = read(card).get('source_profile') or {}
    return {k: bool(value.get(k, False)) for k in ('include_listing_url', 'include_selected_image_alt', 'include_option_role_facts', 'include_selected_coffee_form', 'include_brand_prose_designation', 'include_source_brand_corroboration', 'include_identifier_peer_evidence')}


def transport_stats(folder):
    manifests = [read(p) for p in Path(folder).rglob('manifest.json')]
    transports = [m for m in manifests if 'transport' in m]
    return {'actual_cli_calls': len(transports),
            'status_counts': dict(Counter(m.get('status', 'unknown') for m in transports)),
            'transport_elapsed_seconds_sum': round(sum(m.get('elapsed_seconds', 0) for m in transports), 3)}


def export_loop(root, folder):
    report_path = folder/'loop-report.json'
    report = read(report_path)
    calls = dict(report['roles_actual_calls'])
    comparisons, pipeline_folders = {}, set()
    for name, value in report.get('component_and_integrated_comparisons', {}).items():
        if name not in COMPONENTS:
            continue
        measured = Path(value['output'])
        pipeline_folders.add(measured)
        manifest = read(measured/'manifest.json')
        if manifest['status'] != 'completed':
            raise ValueError(f'Completed loop points at incomplete pipeline: {measured}')
        comparisons[name] = {'before': metrics(value['before']), 'after': metrics(value['after']),
            'paired': numeric_tree(value['paired']), 'keep_for_development': value['keep_for_development'],
            'actual_placer_calls': value['actual_placer_calls'], 'routed': value['routed'],
            'free': value['free'], 'cached_fallback_answers': value['cached_fallback_answers'],
            'exact_request_reused_rows': value.get('exact_request_reused_rows', 0),
            'source_profile': profile(measured/'hypothesis.json'),
            'elapsed_seconds': manifest.get('elapsed_seconds'),
            'artifact': fingerprint(measured/'manifest.json')}
        label = measured.name.removeprefix(folder.name+'-').removesuffix('-pipeline')
        plan_path = folder/(label+'-source-plan')/'plan.json'
        if plan_path.exists():
            plan = read(plan_path)
            if isinstance(plan.get('cohort'), dict):
                comparisons[name]['executable_cohort'] = plan['cohort']
    observed, durations = {}, {}
    role_folders = {'validator_current': root/(folder.name+'-validator-current'),
                    'validator_candidate': root/(folder.name+'-validator-candidate'),
                    'proposer': root/(folder.name+'-feedback-feedback-roles/proposer'),
                    'improver': root/(folder.name+'-feedback-feedback-roles/improver')}
    for role, path in role_folders.items():
        observed[role] = transport_stats(path) if path.exists() else {'actual_cli_calls': 0}
        marker = path/'role-manifest.json'
        durations[role] = {'role_elapsed_seconds': read(marker).get('elapsed_seconds') if marker.exists() else None,
                           'transport_elapsed_seconds_sum': observed[role].get('transport_elapsed_seconds_sum')}
    pipeline_stats = [transport_stats(p) for p in pipeline_folders]
    observed['actual_placer'] = {'actual_cli_calls': sum(p['actual_cli_calls'] for p in pipeline_stats),
        'unique_actual_measurements': len(pipeline_folders),
        'transport_elapsed_seconds_sum': round(sum(p['transport_elapsed_seconds_sum'] for p in pipeline_stats), 3)}
    durations['pipeline_measurement_wall_seconds'] = {p.name: read(p/'manifest.json').get('elapsed_seconds')
                                                     for p in sorted(pipeline_folders)}
    durations['loop_wall_seconds'] = None
    durations['qualification'] = 'Role/pipeline times come from actual manifests; concurrent call-time sums are not loop wall time, which was not recorded.'
    validator = report.get('validator_comparison') or {}
    validator_result = {k: numeric_tree(validator[k]) for k in ('paired_all', 'withheld_development') if k in validator}
    validator_result.update(status=validator.get('status'), keep_for_development=validator.get('keep_for_development', False))
    for role in ('validator_current', 'validator_candidate'):
        path = role_folders[role]
        if (path/'metrics.json').exists():
            validator_result[role] = metrics(read(path/'metrics.json'))
    if validator.get('setup') and Path(validator['setup']).is_file():
        validator_result['candidate_setup'] = fingerprint(Path(validator['setup']))
    if isinstance(validator.get('change'), dict):
        kind = validator['change'].get('kind')
        validator_result['change_kind'] = kind if kind in {'question', 'tool', 'checklist_step', 'web', 'model', 'inputs'} else 'other'
    before_state_path = folder/'retained-state-before.json'
    state_before = read(before_state_path) if before_state_path.exists() else {}
    retained = Path(report['retained_output'])
    proposals = report.get('pipeline_proposals', [report.get('pipeline_proposal')])
    kinds = [p.get('kind') if p.get('kind') in KINDS else 'other' for p in proposals if isinstance(p, dict)]
    entry = {'run': folder.name, 'status': report['status'], 'sample': report['sample'],
        'feedback': report['feedback'], 'withheld_feedback': report['sample']-report['feedback'],
        'calls': calls, 'observed_transport_calls': observed,
        'call_counts_match_saved_report': all(observed[k]['actual_cli_calls'] == v for k,v in calls.items() if k in observed),
        'version_before': report['version_before'], 'version_after': report['version_after'],
        'proposal_kinds': kinds, 'comparisons': comparisons, 'validator': validator_result,
        'retained_exact': report['retained_exact'], 'retained_metrics': metrics(read(retained/'metrics.json')),
        'retained_source_profile': profile(retained/'hypothesis.json'),
        'retained_before': {'version': state_before.get('version'), 'routing_mode': state_before.get('routing_mode')},
        'retained_output_manifest': fingerprint(retained/'manifest.json'),
        'durations': durations, 'cached_answers_in_final_evaluations': report['cached_answers_in_final_evaluations'],
        'exact_request_reused_rows':report.get('exact_request_reused_rows',0),
        'offline_cached_fallback_answers_in_final_evaluations':report.get('offline_cached_fallback_answers_in_final_evaluations',0),
        'production_admission': False, 'artifact': fingerprint(report_path)}
    tool_counts = Counter()
    for path in role_folders['validator_candidate'].glob('batch-*/tool-transcript.json'):
        for call in read(path):
            name = call.get('request', {}).get('name', '')
            if re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,80}', name):
                tool_counts[name] += 1
    entry['actual_candidate_validator_tool_calls'] = dict(tool_counts)
    tool_trial = role_folders['proposer'].parent/'tool-trial/report.json'
    if tool_trial.exists():
        trial = read(tool_trial)
        entry['validator_python_tool_trial'] = {k: trial.get(k) for k in
            ('accepted', 'tool_name', 'source_sha256', 'semantic_probe_status', 'semantic_review_required')}
        entry['validator_python_tool_trial']['artifact'] = fingerprint(tool_trial)
    curations = []
    for path in sorted(folder.glob('rule-curation-*/report.json')):
        result = read(path)
        if result.get('status') != 'diagnostic_rule_curation_completed':
            continue
        curations.append({'attempt':path.parent.name, 'independent_measurement':False,
            'check':result['check'], 'counts':result['counts'],
            'native_executed':result['native_curator']['executed'],
            'native_admitted':result['native_curator']['admitted'],
            'new_model_calls':result['new_model_calls'],
            'production_admission':False, 'artifact':fingerprint(path)})
    if curations:
        latest = {result['check']: result['attempt'] for result in curations}
        for result in curations:
            result['superseded'] = result['attempt'] != latest[result['check']]
        entry['qualified_rule_curation'] = curations
    if (folder/'artifact-index.json').exists():
        entry['artifact_index'] = fingerprint(folder/'artifact-index.json')
    if before_state_path.exists():
        entry['retained_before']['artifact'] = fingerprint(before_state_path)
    post_path = folder/'postmeasurement.json'
    if post_path.exists():
        post = read(post_path)
        gates = {}
        for label, gate in post.get('pipeline_gates', {}).items():
            if label in COMPONENTS:
                gates[label] = numeric_tree(gate) | {'canonical_function': 'taxo.gate.decide',
                    'reasons': [s for s in gate.get('reasons', []) if isinstance(s, str) and s.startswith(('PASS ', 'FAIL '))]}
        curation = post.get('rule_curation', [])
        distilled = post.get('distillation') or {}
        lessons = distilled.get('lessons') or []
        entry['postmeasurement'] = {'artifact': fingerprint(post_path),
            'status': post['status'], 'pipeline_gates': gates,
            'advance_eligible': post['advance_eligible'], 'new_model_calls': post['new_model_calls'],
            'separate_analyst_calls': post.get('separate_analyst_calls'),
            'rule_curation': {'proposals': len(curation),
                'canonical_curator_executed': sum(bool(c.get('canonical_curator_executed')) for c in curation),
                'not_applicable_to_deterministic_curator': sum(c.get('kind') not in ('code_rule', 'new_check') for c in curation)},
            'distillation': {'function': 'taxo.distill.lessons', 'native_record': distilled.get('record'),
                'lessons': len(lessons), 'active_lessons': sum(x.get('status') == 'active' for x in lessons)},
            'production_admission': False}
        if (folder/'postmeasurement-index.json').exists():
            entry['postmeasurement']['index'] = fingerprint(folder/'postmeasurement-index.json')
    return entry


def refresh(root, output):
    root, output = Path(root), Path(output)
    document = read(output)
    protected = {k: document[k] for k in ('sampling', 'baseline')}
    if document['sampling']['source']['sha256'] != read(root/'protocol.json')['source']['sha256']:
        raise ValueError('Export source differs from preserved sample provenance')
    old = {r['run']: r for r in document.get('loops', [])}
    protected_loops = {k: v for k, v in old.items() if k in {'loop-002', 'loop-003', 'loop-004'}}
    exported = []
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not re.fullmatch(r'loop-\d{3}', folder.name) or int(folder.name[-3:]) < 5:
            continue
        if not (folder/'loop-report.json').exists() or not (folder/'stage-status.json').exists():
            continue
        if read(folder/'stage-status.json').get('status') != 'completed':
            continue
        if read(folder/'loop-report.json').get('status') != 'completed_integrated_development_cycle':
            continue
        old[folder.name] = export_loop(root, folder)
        exported.append(folder.name)
    document['loops'] = [old[k] for k in sorted(old)]
    pointer = root/'system-state/current.json'
    if pointer.exists():
        current = read(pointer)
        state_path = Path(current['path'])
        state = read(state_path)
        if fingerprint(state_path)['sha256'] != current['sha256']:
            raise ValueError('Retained system pointer fingerprint mismatch')
        document['retained_system'] = {'version': state['version'], 'routing_mode': state['routing_mode'],
            'artifact': fingerprint(state_path), 'source': state['source'], 'scorer': state['scorer'],
            'source_profile': profile(Path(state['placer']['card']['path'])), 'production_admission': False}
    document['exporter'] = {'implementation': fingerprint(Path(__file__)),
        'qualification': 'New records export aggregate metrics, counts, booleans and artifact fingerprints only; proposal/source/gold text omitted.'}
    assert all(document[k] == v for k,v in protected.items())
    assert all(old[k] == v for k,v in protected_loops.items())
    temporary = output.with_suffix(output.suffix+'.tmp')
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(output)
    return {'exported': exported, 'total_records': len(document['loops']), 'preserved_original_detailed_loops': sorted(protected_loops)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(refresh(args.root, args.output)))
