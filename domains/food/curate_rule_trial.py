"""Diagnostic native rule curation after a completed Food configuration arm.

Planning reads source only. Frozen benchmark scoring follows planning, and only
authorized feedback rows contribute to curator counts. No active state is written.
"""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

import yaml

from domains.food import checks, executable_changes
from domains.food.place_paths import dump_rows, normalize_plan, read, rows, score
from taxo import memory
from taxo.codex_cli import fingerprint, write
from taxo.core.schemas import Listing, Node, RuleSpec
from taxo.gate import decide
from taxo.learn.curator import admit


def _verify(entry):
    if fingerprint(Path(entry['path']))['sha256'] != entry['sha256']:
        raise ValueError('Qualification or measured artifact hash drift: ' + entry['path'])


def _node(path):
    if not path or len(path) > 3:
        raise ValueError('Expected a nonempty Food brand/model/variant candidate')
    return Node(id='curation-candidate', domain='food', name=path[-1], path=path,
                level=('brand', 'model', 'variant')[len(path)-1])


def _qualify(path, check, source, protocol):
    qualification = read(path)
    implementation = qualification['implementation_final']
    _verify(implementation)
    if fingerprint(Path(checks.__file__))['sha256'] != implementation['sha256']:
        raise ValueError('Qualification does not name the actual imported checks implementation')
    _verify(qualification['frozen_source'])
    if qualification['frozen_source']['sha256'] != protocol['source']['sha256']:
        raise ValueError('Qualification source differs from the measured source')
    fn = checks.CHECKS[check][0]
    replay = []
    for probe in qualification['qualification_tests']:
        for key in ('saved_placement', 'saved_plan'):
            if key in probe:
                _verify(probe[key])
        lid = probe.get('listing_id')
        row = copy.deepcopy(source[lid]) if lid else {
            'id': 'qualification-fixture', 'domain': 'food', 'title': '',
            'fields': {'raw_source': {}}}
        if 'mutated_source_flavour_text' in probe:
            row['fields']['raw_source']['flavor_text'] = probe['mutated_source_flavour_text']
        path_value = probe.get('constructed_path', probe.get('actual_saved_path'))
        if 'actual_saved_path' in probe:
            saved = {r['id']: r for r in rows(Path(probe['saved_placement']['path']))}
            if saved[lid]['path'] != path_value:
                raise ValueError('Qualification actual path differs from its saved placement')
        fired = bool(fn(Listing.model_validate(row), _node(path_value), {}))
        if type(probe.get('expected_flag')) is not bool or type(probe.get('actual_flag')) is not bool:
            raise ValueError('Qualification must contain actual boolean results')
        if fired != probe['actual_flag'] or fired != probe['expected_flag']:
            raise ValueError('Actual check replay disagrees with qualification')
        replay.append({'kind': probe['kind'], 'expected_flag': probe['expected_flag'],
                       'actual_flag': fired})
    positive = any(p['kind'].startswith('planted_') and p['expected_flag'] and p['actual_flag'] for p in replay)
    quiet = any(p['kind'].startswith('planted_quiet_') and not p['expected_flag'] and not p['actual_flag'] for p in replay)
    if not positive or not quiet:
        raise ValueError('Missing verified planted positive or quiet qualification')
    return {'planted_fault_fires': positive, 'known_good_quiet': quiet, 'replayed_probes': replay,
            'qualification': fingerprint(path), 'implementation': implementation}


def _execute(root, name, check, qualification, diagnostic):
    if check != 'source_flavour_omitted':
        raise ValueError('This narrow adapter supports only source_flavour_omitted')
    out = root/name
    report = read(out/'loop-report.json')
    if report['status'] != 'completed_integrated_development_cycle':
        raise ValueError('Configuration arm is not completed')
    arm = report['component_and_integrated_comparisons']['configuration_only']
    folder = Path(arm['output'])
    manifest = read(folder/'manifest.json')
    if manifest['status'] != 'completed':
        raise ValueError('Actual configuration measurement is incomplete')
    protocol = read(root/'protocol.json')
    _verify(protocol['source'])
    if manifest['source']['sha256'] != protocol['source']['sha256']:
        raise ValueError('Measured arm source differs from protocol')
    source_rows = rows(Path(protocol['source']['path']))
    source = {r['id']: r for r in source_rows}
    feedback = set(protocol['partition']['feedback_ids'])
    if len(feedback) != 20 or not feedback <= source.keys():
        raise ValueError('Expected the authorized 20-row feedback partition')
    probes = _qualify(qualification, check, source, protocol)
    config_path = Path(arm['config'])
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    active = [r for r in config['rules'] if r.get('status') == 'active' and
              any(c.get('check') == check for c in r.get('when', []) if isinstance(c, dict))]
    if len(active) != 1 or active[0]['when'] != [{'check': check, 'params': {}}]:
        raise ValueError('Expected one exact active qualified check rule')
    disabled_rule = active[0]
    disabled = copy.deepcopy(config)
    disabled['rules'] = [r for r in disabled['rules'] if r['id'] != disabled_rule['id']]
    disabled_path = diagnostic/'disabled-rule-config.yaml'
    disabled_path.write_text(yaml.safe_dump(disabled, sort_keys=False), encoding='utf-8')
    original_plan_path = out/'configuration-source-plan'/'plan.json'
    original_plan = read(original_plan_path)
    _verify(original_plan['adapter'])
    if original_plan['adapter']['sha256'] != fingerprint(Path(executable_changes.__file__))['sha256']:
        raise ValueError('Completed plan used a different planner implementation')
    if original_plan['source']['sha256'] != protocol['source']['sha256']:
        raise ValueError('Completed plan source differs from protocol')
    if original_plan['config']['sha256'] != fingerprint(config_path)['sha256']:
        raise ValueError('Measured source plan configuration drift')
    receipt = read(folder/'routing-config.json')
    _verify(manifest['routing_config'])
    fixed, routed = normalize_plan(source_rows, original_plan['free_placements'], original_plan['routed_ids'])
    if receipt['routed_ids'] != [r['id'] for r in routed] or receipt['fixed_placements'] != list(fixed.values()):
        raise ValueError('Actual routing receipt differs from completed plan')
    before = Path(read(out/'retained-state-before.json')['baseline_output']['path'])
    # This is the only planning call: no scorer or model execution occurs here.
    plan = executable_changes.build_plan(root, before, disabled_path, diagnostic/'disabled-source-plan')
    original_routes = set(original_plan['routed_ids'])
    disabled_routes = set(plan['routed_ids'])
    if not disabled_routes <= original_routes:
        raise ValueError('Disabled plan introduces unmeasured routed IDs')
    actual = rows(folder/'placements.jsonl')
    actual_by_id = {r['id']: r for r in actual}
    if len(actual) != len(source) or actual_by_id.keys() != source.keys():
        raise ValueError('Actual placement membership differs from source')
    counterfactual = plan['free_placements'] + [actual_by_id[lid] for lid in plan['routed_ids']]
    if len(counterfactual) != len(source) or {r['id'] for r in counterfactual} != source.keys():
        raise ValueError('Diagnostic placements do not cover the exact source membership')
    dump_rows(diagnostic/'placements.jsonl', counterfactual)
    # Frozen labels are accessed only after the source-only plan is complete.
    score(root, diagnostic, counterfactual, folder)
    rulings = {r['observation_id']: r['systems']['candidate']['ruling']
               for r in read(diagnostic/'gold-rulings.json') if r['observation_id'] in feedback}
    findings = []
    for candidate in plan['free_placements']:
        lid = candidate['id']
        if lid not in feedback:
            continue
        detail = checks.CHECKS[check][0](Listing.model_validate(source[lid]), _node(candidate['path']), {})
        findings.append({'listing_id': lid, 'candidate_path': candidate['path'],
                         'flagged': bool(detail), 'detail': detail,
                         'benchmark_identity_path_exact': rulings[lid]['identity_path_exact']})
    caught = sum(f['flagged'] and not f['benchmark_identity_path_exact'] for f in findings)
    false_rejects = sum(f['flagged'] and f['benchmark_identity_path_exact'] for f in findings)
    write(diagnostic/'feedback-shadow-findings.json', findings)
    spec = RuleSpec(id=disabled_rule['id'], check=check, decision='abstain', domains=['food'],
                    description=disabled_rule.get('why', ''), origin=name+' diagnostic feedback benchmark')
    # Execute the native curator unchanged, but isolate its append-only record
    # from the active shared memory. Admission here is diagnostic eligibility.
    native_dir = diagnostic/'native-curator'
    native_dir.mkdir()
    previous_memory = memory.MEMORY_DIR
    try:
        memory.MEMORY_DIR = native_dir
        admitted = admit(spec, 'food', caught, false_rejects,
                         probes['planted_fault_fires'], probes['known_good_quiet'])
    finally:
        memory.MEMORY_DIR = previous_memory
    previous_paths = {r['id']: r['path'] for r in rows(before/'placements.jsonl')}
    if previous_paths.keys() != source.keys():
        raise ValueError('Whole-system comparator membership differs')
    paired = arm['paired']['exact']
    comparison = {'before': {'exact': arm['before']['identity_path_exact']},
                  'after': {'exact': arm['after']['identity_path_exact']},
                  'touched': sum(actual_by_id[k]['path'] != previous_paths[k] for k in source),
                  'better': paired['gains'], 'worse': paired['regressions']}
    agent_before = sum(r.get('by') == 'food_source_path_placer' for r in rows(before/'placements.jsonl'))/len(source)
    agent_after = arm['routed']/len(source)
    passed, reasons = decide(comparison, agent_before, agent_after)
    return {'status': 'diagnostic_rule_curation_completed', 'check': check,
            'qualification': probes, 'counts': {'authorized_feedback': len(feedback),
                'feedback_disabled_free_candidates': len(findings), 'caught_benchmark_nonexact': caught,
                'false_rejects_benchmark_exact': false_rejects},
            'interpretation': 'Benchmark exactness only; nonexact is not a semantic wrong-path verdict.',
            'native_curator': {'function': 'taxo.learn.curator.admit', 'executed': True,
                'admitted': admitted, 'record': fingerprint(native_dir/'record.jsonl'),
                'active_shared_memory_written': False},
            'whole_system_gate': {'function': 'taxo.gate.decide', 'checks_pass': passed,
                'reasons': reasons, 'comparison': comparison, 'agent_before': agent_before,
                'agent_after': agent_after, 'arm_keep_for_development': arm['keep_for_development']},
            'counterfactual': {'diagnostic_only': True, 'model_calls': 0,
                'reused_actual_placements': len(disabled_routes),
                'newly_free_rows': len(original_routes-disabled_routes),
                'unchanged_routed_ids_only': True, 'before_metrics': read(diagnostic/'metrics.json')},
            'provenance': {'source': fingerprint(Path(protocol['source']['path'])),
                'qualification': fingerprint(qualification), 'config': fingerprint(config_path),
                'measured_plan': fingerprint(original_plan_path),
                'actual_placements': fingerprint(folder/'placements.jsonl'),
                'loop_report': fingerprint(out/'loop-report.json'),
                'checks': fingerprint(Path(checks.__file__)), 'adapter': fingerprint(Path(__file__))},
            'new_model_calls': 0, 'sealed_read_executed': False, 'production_admission': False,
            'active_rules_or_state_written': False}


def execute(root: Path, name: str, check: str, qualification: Path):
    diagnostic = root/name/('rule-curation-'+check)
    attempt = 1
    while diagnostic.exists():
        attempt += 1
        diagnostic = root/name/('rule-curation-'+check+f'-{attempt:03d}')
    original_files = [p for p in (root/name).rglob('*') if p.is_file() and
                      not any(part.startswith('rule-curation-') for part in p.relative_to(root/name).parts)]
    state = root/'system-state'/'current.json'
    original_files += [state] if state.exists() else []
    record = memory.MEMORY_DIR/'record.jsonl'
    original_files += [record] if record.exists() else []
    protected = [fingerprint(p) for p in original_files]
    diagnostic.mkdir(parents=True, exist_ok=False)
    try:
        result = _execute(root, name, check, qualification, diagnostic)
    except (ValueError, KeyError, FileNotFoundError) as error:
        native_record = diagnostic/'native-curator'/'record.jsonl'
        result = {'status': 'diagnostic_rule_curation_skipped', 'reason': str(error),
                  'native_curator_executed': native_record.exists(), 'new_model_calls': 0,
                  'production_admission': False, 'sealed_read_executed': False}
    unchanged = all(fingerprint(Path(p['path']))['sha256'] == p['sha256'] for p in protected)
    write(diagnostic/'protected-input-hashes.json', protected)
    result['original_loop_artifacts_and_active_record_unchanged'] = unchanged
    if not unchanged:
        result['preservation_check_failure'] = 'A protected input changed during diagnostics; review concurrent writes.'
    write(diagnostic/'report.json', result)
    write(diagnostic/'artifact-index.json', [fingerprint(p) for p in sorted(diagnostic.rglob('*'))
                                           if p.is_file() and p.name != 'artifact-index.json'])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--check', required=True)
    parser.add_argument('--qualification', type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.root, args.name, args.check, args.qualification)
    print({k: result[k] for k in ('status', 'new_model_calls', 'production_admission')})
    if 'counts' in result:
        print(result['counts'])
        print({'native_admitted': result['native_curator']['admitted'],
               'whole_system_gate_passed': result['whole_system_gate']['checks_pass']})
    elif 'reason' in result:
        print({'skip_reason': result['reason']})
