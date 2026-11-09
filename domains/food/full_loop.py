"""Food adapter for SPEC loops A/B and native Loop C records, using real CLI roles."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from domains.food import loop_roles, validate_paths
from domains.food.continue_loop import propose, select
from domains.food.place_paths import execute as place, read, rows, score, dump_rows
from taxo import distill, memory
from taxo.codex_cli import write, fingerprint
from taxo.core.schemas import Listing, Node, RuleSpec, Status
from taxo.learn import curator
from taxo.gate import decide as gate_decide
from taxo.tools import checks


def run(root, baseline, name, setup_path):
    out = root/name
    out.mkdir(exist_ok=False)
    write(out/'stage-status.json', {'status': 'running', 'stage': 'independent_validation'})
    validate_paths.execute(root, setup_path, name+'-validator-current')
    current = root/(name+'-validator-current')
    gold = {r['observation_id']: r for r in read(current/'gold-rulings.json')}
    pipeline = {r['id']: r for r in rows(baseline/'placements.jsonl')}
    judgments = {r['listing_id']: r for r in read(current/'judgments.json')}
    feedback = set(read(root/'protocol.json')['partition']['feedback_ids'])
    review, counts = [], Counter()
    for r in read(baseline/'gold-rulings.json'):
        lid = r['observation_id']
        pr = r['systems']['candidate']['ruling']['identity_path_exact']
        vr = gold[lid]['systems']['candidate']['ruling']['identity_path_exact']
        disagree = pipeline[lid]['path'] != judgments[lid]['path']
        verdict = 'pipeline_right' if pr else 'validator_right' if vr else 'both_wrong'
        counts['disagree' if disagree else 'agree'] += 1
        counts[verdict] += 1
        review.append({'id': lid, 'partition': 'feedback' if lid in feedback else 'withheld_feedback',
                       'pipeline': pipeline[lid], 'validator': judgments[lid],
                       'reviewed_against_existing_owner_gold': verdict, 'disagree': disagree})
    write(out/'review.json', review)
    write(out/'validator-findings.json', dict(counts))
    # Reuse existing role factories/runtime on authorized feedback only.
    role_name = name+'-feedback'
    (root/role_name).mkdir()
    write(root/role_name/'feedback-diagnosis.json', read(baseline/'feedback-diagnosis.json'))
    loop_roles.execute(root, role_name, current/'judgments.json')
    roles = root/(role_name+'-feedback-roles')
    write(out/'stage-status.json', {'status': 'running', 'stage': 'analysis_and_candidate'})
    card = propose(root, baseline, out/'analyst')
    candidate_name = name+'-candidate'
    place(root, candidate_name, card, baseline)
    candidate = root/candidate_name
    decision = select(baseline, candidate)
    old_metrics, new_metrics = read(baseline/'metrics.json'), read(candidate/'metrics.json')
    deltas = read(candidate/'paired-deltas.json')
    old_paths = {r['id']: r['path'] for r in rows(baseline/'placements.jsonl')}
    touched = sum(p['path'] != old_paths[p['id']] for p in rows(candidate/'placements.jsonl'))
    dev_gate, gate_reasons = gate_decide({'before': {'exact': old_metrics['identity_path_exact']},
        'after': {'exact': new_metrics['identity_path_exact']}, 'touched': touched,
        'better': sum(d['exact_gain'] for d in deltas), 'worse': sum(d['exact_regression'] for d in deltas)}, 1.0, 1.0)
    decision.update(documented_gate_checks_on_development=dev_gate, gate_reasons=gate_reasons,
                    advance_eligible=dev_gate and decision['keep_for_development'], sealed_gate_executed=False)
    write(out/'candidate-decision.json', decision)
    proposal = read(roles/'proposer-decision.json')
    shadow = {'status': 'rejected_invalid_proposal', 'production_admission': False,
              'reason': proposal['reason'], 'caught': 0, 'false_rejects': 0, 'fires': 0}
    if proposal['accept_for_shadow_experiment']:
        p = proposal['rule']
        rule = RuleSpec(id=p['id'], check=p['check'], decision=p['decision'], description=p['description'],
                        params=json.loads(p['params_json']), status=Status.SHADOW, domains=['food'])
        nodes = {n['id']: Node.model_validate(n) for n in rows(candidate/'nodes.jsonl')}
        sources = {r['id']: Listing.model_validate(r) for r in rows(root/'source-snapshot.jsonl')}
        rulings = {r['observation_id']: r for r in read(candidate/'gold-rulings.json')}
        caught = false_rejects = fires = 0
        shadow_rows = []
        for pred in rows(candidate/'placements.jsonl'):
            lid = pred['id']
            if lid not in feedback or pred['node_id'] is None:
                continue
            finding = checks.run(rule.check, sources[lid], nodes[pred['node_id']], nodes, rule.decision, **rule.params)
            if finding:
                fires += 1
                good = rulings[lid]['systems']['candidate']['ruling']['identity_path_exact']
                false_rejects += bool(good and rule.decision in ('veto', 'abstain'))
                caught += bool(not good and rule.decision in ('veto', 'abstain'))
                shadow_rows.append({'id': lid, 'check': finding.check, 'decision': finding.decision,
                                    'detail': finding.detail, 'gold_exact': good})
        write(out/'rule-shadow-findings.json', shadow_rows)
        # No fabricated planted fault. Curator refuses admission without that check and the sealed gate.
        admitted = curator.admit(rule, 'food', caught, false_rejects, False, false_rejects == 0)
        shadow.update(status='shadow_evaluated', caught=caught, false_rejects=false_rejects, fires=fires,
                      curator_admitted=admitted, reason='No verified planted-fault qualification or Food sealed gate')
    else:
        memory.record(proposal['rule']['id'], 'food', admitted=False, reason=proposal['reason'])
    write(out/'rule-curation.json', shadow)
    improvement = read(roles/'improver-decision.json')
    validator_decision = {'status': 'rejected_unsupported_proposal', 'kept_for_development': False,
                          'production_admission': False, 'reason': improvement['reason']}
    if improvement['accept_for_validator_experiment']:
        next_setup = roles/'validator-setup-v2.json'
        validate_paths.execute(root, next_setup, name+'-validator-candidate')
        vm = read(root/(name+'-validator-candidate')/'metrics.json')
        old = read(current/'metrics.json')
        # Compare on the other dev partition; this is not a fresh/brand-sealed holdout.
        a, b = old['partitions']['withheld_feedback'], vm['partitions']['withheld_feedback']
        harms = lambda m: sum(m['classes'].get(k, 0) for k in ('wrong_brand', 'wrong_deeper', 'wrong_label_path'))
        keep = b['identity_path_exact'] > a['identity_path_exact'] and harms(b) <= harms(a) and (
            b['abstentions_all_frozen']/b['frozen_n'] <= a['abstentions_all_frozen']/a['frozen_n'] + .05)
        validator_decision.update(status='actual_ab_evaluated', kept_for_development=keep,
            before=old, after=vm, reason='Exact must rise; harm cannot rise; abstention rate may rise at most .05')
    write(out/'validator-curation.json', validator_decision)
    calls = Counter()
    for label, folder in [('validator_current', current), ('proposer', roles/'proposer'),
                          ('improver', roles/'improver'), ('analyst', out/'analyst'), ('placer', candidate),
                          ('validator_candidate', root/(name+'-validator-candidate'))]:
        calls[label] = sum('transport' in read(p) for p in folder.rglob('manifest.json')) if folder.exists() else 0
    cm = read(candidate/'manifest.json')
    summary = {'status': 'completed_development_cycle', 'roles_actual_calls': dict(calls),
        'sample': len(pipeline), 'feedback': len(feedback), 'withheld_feedback': len(pipeline)-len(feedback),
        'hypothesis': read(card)['hypothesis'], 'change': read(out/'analyst/final.json'),
        'candidate_decision': decision, 'independent_validator': read(current/'metrics.json'),
        'validator_findings': dict(counts), 'rule': shadow, 'checklist': validator_decision,
        'production_admission': False, 'gate': 'blocked: no untouched Food brand-sealed gold',
        'limitations': ['Previously inspected development gold; no fresh-holdout claim',
                        'Existing owner-authorized Pedia labels adjudicate; no new human review or gold edits',
                        'Source-only validator: no web/siblings budget; dollar cost and served tier unavailable'],
        'artifacts': str(out)}
    write(out/'loop-report.json', summary)
    kpi = {'ts': cm['started_utc'], 'domain': 'food', 'loop': 'A', 'round': 1, 'label': name,
           'code': cm['code']['sha256'], 'vocab': None, 'rules': None, 'data': cm['source']['sha256'],
           'gold_dev': None, 'gold_sealed': None, 'human_dev': None, 'human_sealed': None,
           'shares': {'to_agent': 1.0}, 'agent_calls': sum(calls.values()), 'secs': cm['elapsed_seconds'],
           'silver': {'version': name, 'agreement': counts['agree']/len(pipeline)},
           'metadata': summary | {'change': summary['change'], 'artifacts': fingerprint(out/'loop-report.json')}}
    # Public metadata has general proposals and aggregates only, no source observations or gold labels.
    record_path = distill.record('food', kpi, lesson='food-pedia-full-cli-loop', kind='card_text')
    native = read(record_path) if record_path else None
    lessons = distill.lessons({native['id']: native}) if native else []
    write(out/'distillation.json', {'native_record': str(record_path), 'active_lessons': lessons,
                                   'reason': 'Ungated development records remain pending; no automatic lesson activation'})
    write(out/'stage-status.json', {'status': 'completed', 'stage': 'native_distillation_record'})
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, required=True)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--setup', type=Path, required=True)
    a = ap.parse_args()
    run(a.root, a.baseline, a.name, a.setup)
