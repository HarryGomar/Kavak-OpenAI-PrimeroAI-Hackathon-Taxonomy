"""Integrated Food improvement loop: versioned code, routing, placer, and validator."""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from domains.food import executable_changes, loop_roles, validate_paths
from domains.food.place_paths import read, rows
from domains.food.tool_trials import compare_paired
from taxo import distill, memory
from taxo.codex_cli import fingerprint, write


def scored(folder, partition=None):
    result = {}
    for row in read(folder/'gold-rulings.json'):
        if partition and row['partition'] != partition:
            continue
        ruling = row['systems']['candidate']['ruling']
        if ruling is None:
            continue
        result[row['observation_id']] = {'exact': ruling['identity_path_exact'],
            'harm': ruling['class'] in ('wrong_brand', 'wrong_deeper', 'wrong_label_path'),
            'abstain': not row['systems']['candidate']['saved_prediction']['path']}
    return result


def run(root, fallback, name, setup):
    """One retained full system, component trials, and an actual integrated pipeline."""
    import shutil
    from domains.food import system_state
    from domains.food.place_paths import execute as place, normalize_plan
    from domains.food.tool_trials import load_tool
    completed = root/name/'loop-report.json'
    if completed.exists() and read(completed)['status'] == 'completed_integrated_development_cycle':
        print(json.dumps({'status':'already_completed','report':str(completed)}))
        return
    state_path = root/'system-state/current.json'
    state = system_state.load(root) if state_path.exists() else system_state.initialize(
        root, baseline_output=fallback, placer_card=fallback/'hypothesis.json', validator_setup=setup)
    before_version = state['version']
    fallback = Path(state['baseline_output']['path'])
    setup = Path(state['validator']['setup']['path'])
    card_path = Path(state['placer']['card']['path'])
    config = Path(state['active_executable_config']['path']) if state.get('active_executable_config') else None
    tool_reports = [Path(p['path']) for p in state['placer']['tool_reports']]
    out = root/name
    out.mkdir(exist_ok=True)
    if (out/'loop-report.json').exists() and not (out/'split-run-report.json').exists():
        old = read(out/'loop-report.json')
        if old['status'] != 'completed_integrated_development_cycle':
            shutil.copyfile(out/'loop-report.json', out/'split-run-report.json')
    write(out/'retained-state-before.json', state)
    current = root/(name+'-validator-current')
    if not (current/'role-manifest.json').exists():
        validate_paths.execute(root, setup, current.name)
    current_manifest = read(current/'role-manifest.json')
    if current_manifest['status'] != 'executed' or current_manifest['setup']['sha256'] != fingerprint(setup)['sha256']:
        raise RuntimeError('Current validator must actually complete on the retained setup; no historical substitution')
    role_name, roles = name+'-feedback', root/(name+'-feedback-feedback-roles')
    if not (roles/'manifest.json').exists():
        if roles.exists():
            raise RuntimeError('Feedback stage already started; preserve incomplete evidence')
        (root/role_name).mkdir(exist_ok=True)
        write(root/role_name/'feedback-diagnosis.json', read(fallback/'feedback-diagnosis.json'))
        loop_roles.execute(root, role_name, current/'judgments.json', executable=True)
    proposal = read(roles/'proposer-output.json')
    proposals = read(roles/'pipeline-proposals.json') if (roles/'pipeline-proposals.json').exists() else [proposal]
    primary_proposal = proposal
    improved = read(roles/'improver-decision.json')
    candidate_config, candidate_card, candidate_tools = config, card_path, list(tool_reports)
    config_changed = card_changed = False
    diagnostics = {'status': 'unchanged', 'fresh_model_calls': 0}
    for proposal in proposals:
        if proposal['kind'] in ('vocab', 'route', 'code_rule', 'new_check'):
            trial = out/'configuration-isolation'
            diagnostics = read(trial/'report.json') if (trial/'report.json').exists() else executable_changes.evaluate(
                proposal, root, fallback, trial, base_config=config)
            if diagnostics['status'] == 'evaluated_offline_executable_config':
                candidate_config = trial/'candidate-config.yaml'
                config_changed = True
        elif proposal['kind'] == 'agentic_rule':
            payload = json.loads(proposal['payload_json'])
            if not isinstance(payload.get('text'), str) or not payload['text'].strip():
                raise ValueError('Placer instruction proposal requires concrete text')
            gold_names = {s['label'].casefold() for r in read(fallback/'feedback-diagnosis.json')
                          for s in r['gold_original'][0]['pedia_full_path'] if len(s['label']) >= 5}
            if any(n in payload['text'].casefold() for n in gold_names):
                raise ValueError('Specific gold name in proposed placer instruction')
            card = read(card_path)
            card.update(hypothesis=proposal['description'], change_id=proposal['id'],
                        instruction=card['instruction']+'\nPLACER RULE CANDIDATE:\n'+payload['text'])
            candidate_card = out/'candidate-placer-card.json'
            write(candidate_card, card)
            if payload.get('tool_report'):
                report_path = Path(payload['tool_report'])
                load_tool(report_path)  # qualification/source-hash check before candidate eligibility
                candidate_tools.append(report_path)
            card_changed = True
        else:
            diagnostics = {'status': 'implementation_or_evidence_needed', 'proposal': proposal,
                           'reason': 'No invented registry, check, or policy capability', 'fresh_model_calls': 0}
    proposal = primary_proposal
    write(out/'stage-status.json', {'status': 'running', 'stage': 'actual_full_pipeline_and_validator_comparisons'})
    outcomes, measurements = {}, {}
    def evaluate_pipeline(label, cfg, card, reports):
        signature = json.dumps([fingerprint(cfg)['sha256'] if cfg else None,
            read(card)['instruction'], [fingerprint(p)['sha256'] for p in reports]])
        if signature in measurements:
            return measurements[signature]
        folder = root/(name+'-'+label+'-pipeline')
        plan_folder = out/(label+'-source-plan')
        plan = read(plan_folder/'plan.json') if (plan_folder/'plan.json').exists() else executable_changes.build_plan(
            root, fallback, cfg, plan_folder)
        if not (folder/'manifest.json').exists():
            place(root, folder.name, card, fallback, fixed_placements=plan['free_placements'],
                  routed_ids=plan['routed_ids'], placer_tools=[load_tool(p) for p in reports])
        manifest = read(folder/'manifest.json')
        if manifest['status'] != 'completed' or read(folder/'hypothesis.json')['instruction'] != read(card)['instruction']:
            raise RuntimeError('Actual pipeline measurement incomplete or uses a different candidate card')
        if manifest['source']['sha256'] != state['source']['sha256']:
            raise ValueError('Pipeline measurement source differs from retained system')
        fixed, routed = normalize_plan(rows(root/'source-snapshot.jsonl'), plan['free_placements'], plan['routed_ids'])
        receipt = read(folder/'routing-config.json')
        if receipt['fixed_placements'] != list(fixed.values()) or receipt['routed_ids'] != [r['id'] for r in routed]:
            raise ValueError('Pipeline receipt differs from requested executable routing plan')
        if fingerprint(folder/'routing-config.json')['sha256'] != manifest['routing_config']['sha256']:
            raise ValueError('Pipeline routing receipt drift')
        actual_tools = receipt.get('tools') or []
        loaded = [load_tool(p) for p in reports]
        if [t['name'] for t in actual_tools] != [t.__name__ for t in loaded]:
            raise ValueError('Pipeline receipt differs from requested placer tools')
        paired = compare_paired(scored(fallback), scored(folder))
        b, a = read(fallback/'metrics.json'), read(folder/'metrics.json')
        keep = paired['keep_for_development'] and all(a[k] >= b[k] for k in ('brand_correct', 'strict_full_path_exact'))
        result = {'output': str(folder), 'before': b, 'after': a, 'paired': paired,
            'keep_for_development': keep, 'config': str(cfg) if cfg else None,
            'card': str(card), 'tool_reports': list(map(str,reports)),
            'actual_placer_calls': manifest['model_calls'], 'routed': len(plan['routed_ids']),
            'free': len(plan['free_placements']), 'cached_fallback_answers': 0}
        measurements[signature] = result
        return result
    def pipeline_comparisons():
        if config_changed:
            outcomes['configuration_only'] = evaluate_pipeline('configuration', candidate_config, card_path, tool_reports)
        if card_changed:
            # If this is the only pipeline change, this actual measurement IS the integrated arm.
            label = 'integrated' if not config_changed else 'placer'
            outcomes['placer_only'] = evaluate_pipeline(label, config, candidate_card, candidate_tools)
        if config_changed or card_changed:
            outcomes['integrated'] = evaluate_pipeline('integrated', candidate_config, candidate_card, candidate_tools)
        return outcomes
    validator_folder = root/(name+'-validator-candidate')
    def validator_comparison():
        if not improved['accept_for_validator_experiment']:
            return {'status': 'proposal_rejected', 'reason': improved['reason'], 'keep_for_development': False}
        if not (validator_folder/'role-manifest.json').exists():
            validate_paths.execute(root, Path(improved['candidate_setup']), validator_folder.name)
        vm = read(validator_folder/'role-manifest.json')
        if vm['status'] != 'executed' or vm['setup']['sha256'] != fingerprint(Path(improved['candidate_setup']))['sha256']:
            raise RuntimeError('Candidate independent validator incomplete')
        all_rows = compare_paired(scored(current), scored(validator_folder))
        held = compare_paired(scored(current,'withheld_feedback'), scored(validator_folder,'withheld_feedback'))
        return {'status': 'actual_paired_ab_executed', 'paired_all': all_rows,
            'withheld_development': held, 'keep_for_development': held['keep_for_development'],
            'change': read(roles/'improver-output.json'), 'setup': improved['candidate_setup']}
    with ThreadPoolExecutor(max_workers=2) as pool:
        pf, vf = pool.submit(pipeline_comparisons), pool.submit(validator_comparison)
        outcomes, validator = pf.result(), vf.result()
    # A bad combination is never accepted merely because an isolated component won.
    eligible = [x for x in measurements.values() if x['keep_for_development']]
    chosen = max(eligible, key=lambda x:(x['after']['identity_path_exact'],-x['actual_placer_calls'])) if eligible else None
    changes = {}
    if chosen:
        changes.update(baseline_output=chosen['output'], active_executable_config=chosen['config'],
            routing_mode='rules_then_agent' if chosen['config'] else 'agent_all',
            placer={'card': chosen['card'], 'tool_reports': chosen['tool_reports']})
    if validator['keep_for_development']:
        import yaml
        retained_validator = yaml.safe_load(Path(validator['setup']).read_text(encoding='utf-8'))
        changes['validator'] = {'setup': validator['setup'], 'tool_reports':retained_validator.get('tool_reports', [])}
    if changes:
        changes.setdefault('baseline_output', state['baseline_output']['path'])
    gate = {'keep_for_development': bool(changes), 'production_admission': False,
            'paired': chosen['paired'] if chosen else validator.get('paired_all'),
            'comparisons': outcomes, 'validator': validator}
    write(out/'full-system-decision.json', gate)
    if changes:
        state = system_state.retain_candidate(root, changes, expected_version=before_version,
                                             gate_evidence_path=out/'full-system-decision.json')
    calls = {}
    for label, folder in [('validator_current',current),('proposer',roles/'proposer'),
                          ('improver',roles/'improver'),('validator_candidate',validator_folder)]:
        calls[label] = sum('transport' in read(p) for p in folder.rglob('manifest.json')) if folder.exists() else 0
    calls['actual_placer'] = sum(x['actual_placer_calls'] for x in measurements.values())
    report = {'status':'completed_integrated_development_cycle','sample':len(rows(root/'source-snapshot.jsonl')),
        'feedback':len(read(root/'protocol.json')['partition']['feedback_ids']), 'version_before':before_version,
        'version_after':state['version'],'roles_actual_calls':calls,'pipeline_proposal':proposal, 'pipeline_proposals':proposals,
        'configuration_isolation_diagnostic':diagnostics,'component_and_integrated_comparisons':outcomes,
        'validator_comparison':validator,'retained_output':state['baseline_output']['path'],
        'retained_exact':read(Path(state['baseline_output']['path'])/'metrics.json')['identity_path_exact'],
        'cached_answers_in_final_evaluations':0,'production_admission':False,
        'limitations':['Internal20/30 split; no untouched brand-sealed admission',
            'Unchanged retained reference is a previous actual full run; stochastic variation remains',
            'Missing canonical evidence is not repaired by copying gold']}
    write(out/'loop-report.json',report)
    write(out/'artifact-index.json',[fingerprint(p) for p in out.rglob('*') if p.is_file() and p.name!='artifact-index.json'])
    memory.record(proposal['id'],'food',admitted=False,keep_for_development=bool(changes),
                  version=state['version'],integrated_output=state['baseline_output']['path'])
    distill.record('food',{'ts':time.strftime('%Y-%m-%dT%H:%M:%S'),'loop':'A','round':state['version'],
        'label':name+' integrated','code':fingerprint(Path(__file__))['sha256'],'data':fingerprint(root/'source-snapshot.jsonl')['sha256'],
        'gold_dev':None,'gold_sealed':None,'shares':{},'agent_calls':sum(calls.values()),
        'metadata':{'component_outcomes':{k:{'before':v['before'],'after':v['after'],'paired':v['paired'],
                                          'keep_for_development':v['keep_for_development']} for k,v in outcomes.items()},
                    'validator_paired':validator.get('paired_all'),'calls':calls,'version':state['version'],
                    'production_admission':False,'artifact_index':fingerprint(out/'artifact-index.json')}},
                    lesson='food-integrated-system',kind='rule_shape')
    write(out/'stage-status.json',{'status':'completed','stage':'retained_version_and_native_distillation'})
    print(json.dumps({'status':report['status'],'calls':calls,'retained_exact':report['retained_exact'],
                      'version':state['version'],'output':str(out)}))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--fallback', type=Path, required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--setup', type=Path, required=True)
    a = ap.parse_args()
    run(a.root, a.fallback, a.name, a.setup)
