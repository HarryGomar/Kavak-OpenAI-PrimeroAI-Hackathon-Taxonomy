"""Food loop feedback roles: existing factories/runtime, feedback-only cases, explicit decisions."""
from __future__ import annotations

import argparse
import inspect
import json
import yaml
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from taxo.codex_cli import write, fingerprint
from taxo.roles.proposer import make_proposer
from taxo.roles.improver import make_improver
from taxo.roles.runtime import run_sync
from taxo.tools.checks import CHECKS

from domains.food.place_paths import read, rows, evidence


def execute(root, run_name, validator_path=None, *, executable=False):
    folder = root / (run_name + "-feedback-roles")
    folder.mkdir(exist_ok=False)
    current = read(root / run_name / "feedback-diagnosis.json")
    permitted = set(read(root/'protocol.json')['partition']['feedback_ids'])
    if any(r['observation_id'] not in permitted for r in current):
        raise ValueError('Feedback roles may not read the withheld partition')
    if executable and validator_path is None:
        raise ValueError('Executable Food feedback requires actual current-cycle independent judgments')
    source = {r["id"]: r for r in rows(root / "source-snapshot.jsonl")}
    validator = {r["listing_id"]: r for r in read(validator_path)} if validator_path else None
    cases = []
    for r in current:
        lid = r["observation_id"]
        ev = evidence(source[lid])
        if ev.get("description_text"):
            ev["description_text"] = ev["description_text"][:3000]
        cases.append({"listing_id": lid, "source_evidence": ev, "human_gold": r["gold_original"][0]["pedia_full_path"],
                      "pipeline": r["systems"]["candidate"],
                      "independent_validator": validator[lid] if validator else r["frozen_independent_validator"]})
    write(folder / "feedback-cases.json", cases)
    constraint = ("These are previously inspected, owner-confirmed Food human gold feedback cases, not a fresh external holdout. "
                  "Exact-label mismatches may be synonyms; do not presume semantic errors. "
                  "Propose one general mechanism, no listing/ASIN/title/brand-answer lists. "
                  "Model/CLI pin cannot change; no web or outside evidence. "
                  "A rule must not enforce missing brand fields as missing makers. No per-case exceptions.")
    from taxo.roles.validator import load_setup
    setup = load_setup('food')
    if validator_path and (validator_path.parent / "role-manifest.json").exists():
        setup = yaml.safe_load(Path(read(validator_path.parent / 'role-manifest.json')['setup']['path']).read_text(encoding='utf-8'))
    payload = json.dumps({"constraints": constraint, "cases": cases, "current_setup": setup}, ensure_ascii=False)
    if executable:
        from taxo.core.config import DOMAINS_DIR
        from domains.food.executable_changes import contract
        owner = yaml.safe_load((DOMAINS_DIR/'food/pack.yaml').read_text(encoding='utf-8'))['conventions']
        history = []
        retained_system = None
        if (root/'system-state/current.json').exists():
            from domains.food.system_state import load
            state = load(root)
            retained_system = {'version': state['version'], 'routing_mode': state['routing_mode'],
                'placer_card': read(Path(state['placer']['card']['path'])),
                'active_config': yaml.safe_load(Path(state['active_executable_config']['path']).read_text(encoding='utf-8'))
                    if state.get('active_executable_config') else None}
        for previous in sorted(root.glob('executable-*/report.json')):
            report = read(previous)
            history.append({'trial': previous.parent.name, 'status': report['status'],
                'before_feedback': report.get('before', {}).get('partitions', {}).get('feedback'),
                'after_feedback': report.get('after', {}).get('partitions', {}).get('feedback')})
        payload = json.dumps({'constraints': constraint, 'owner_conventions': owner, 'cases': cases,
                              'current_setup': setup,
                              'retained_full_system': retained_system,
                              'executable_pipeline_language': contract()['language'],
                              'current_vocabulary': yaml.safe_load((DOMAINS_DIR/'food/vocab.yaml').read_text(encoding='utf-8')),
                              'prior_executable_trials_feedback_only': history,
                              'runtime_capabilities': {'executable': ['code_rule', 'agentic_rule', 'vocab', 'route'],
                                  'record_only': ['new_check', 'registry', 'convention_question'],
                                  'source_only': True}}, ensure_ascii=False)
    def call(role, factory):
        scoped = payload
        if role == 'improver':
            # This role learns from validator errors, not from the pipeline's card mistakes.
            mistakes = [c for c in cases if c['independent_validator']['path'] !=
                        [s['label'] for s in c['human_gold'] if s['level'] in ('brand', 'product', 'model', 'variant')]]
            scoped = json.dumps({'constraints': constraint, 'current_setup': setup,
                                 'owner_conventions': owner if executable else None,
                                 'available_tools': ['similar_brands'] + [read(Path(path))['tool_name']
                                     for path in setup.get('tool_reports', [])],
                                 'validator_mistakes': [{k: v for k, v in c.items() if k != 'pipeline'}
                                                       for c in mistakes]}, ensure_ascii=False)
        result = run_sync(factory('food', executable=executable), scoped, output=folder / role, max_turns=1)
        return result.final_output.model_dump(mode="json")
    with ThreadPoolExecutor(max_workers=2) as pool:
        proposer = pool.submit(call, "proposer", make_proposer)
        improver = pool.submit(call, "improver", make_improver)
        proposed, improved = proposer.result(), improver.result()
    write(folder / "proposer-output.json", proposed)
    write(folder / "improver-output.json", improved)
    raw_proposed = proposed
    kind = proposed.get('kind', 'code_rule')
    payload_error = None
    if executable:
        try:
            decoded = json.loads(proposed.get('payload_json') or '{}')
            if not isinstance(decoded, dict):
                raise ValueError('Proposal payload_json must be an object')
        except Exception as error:
            decoded, payload_error = {}, str(error)
        proposed = {'id': proposed['id'], 'description': proposed['description'], 'scope': proposed['scope'],
                    'check': proposed.get('check') or '', 'decision': proposed.get('decision') or 'info',
                    'params_json': json.dumps(decoded.get('params') or {}), 'rationale': proposed['rationale']}
    valid, reason = True, "Existing check with signature-valid general parameters; evaluate in shadow only."
    try:
        if executable and (kind != 'code_rule' or payload_error):
            raise ValueError(payload_error or f'{kind} is not a legacy check; use its executable candidate handler')
        if executable and set(decoded)-{'params'}:
            raise ValueError('code_rule payload only accepts params; undeclared conditions cannot be silently ignored')
        params = json.loads(proposed["params_json"])
        if proposed["check"] not in CHECKS or proposed["decision"] not in {"veto", "abstain", "info"}:
            raise ValueError("Unsupported check/decision")
        if any(isinstance(v, (list, dict)) for v in params.values()):
            raise ValueError("No mined word/name lists or nested lookup parameters accepted")
        inspect.signature(CHECKS[proposed["check"]][0]).bind(None, None, None, **params)
    except Exception as error:
        valid, reason = False, str(error)
    candidate = valid or (executable and kind in {'agentic_rule', 'vocab', 'route'} and payload_error is None)
    candidate_reason = reason
    if executable and kind == 'new_check':
        candidate_reason = 'Missing-check proposal recorded; no implementation was generated or qualified'
    elif executable and kind == 'registry':
        candidate_reason = 'Requires independent source provenance and registry importer; gold is not a runtime catalog'
    elif executable and kind == 'convention_question':
        candidate_reason = 'Policy question recorded for owner review; no executable change'
    elif candidate and not valid:
        candidate_reason = 'Eligible kind; executable candidate handler must validate its payload and measure effects'
    write(folder / "proposer-decision.json", {"accept_for_shadow_experiment": valid, "reason": reason,
          'kind': kind, 'executable_candidate': candidate, 'executable_reason': candidate_reason,
          'raw_proposal': raw_proposed,
          "production_admission": False, "rule": proposed, "feedback_ids": [c["listing_id"] for c in cases]})
    accepted = improved["kind"] == "checklist_step" and len(improved["text"]) < 2000
    names = {s["label"].casefold() for c in cases for s in c["human_gold"] if len(s["label"]) >= 5}
    applied_text = '\n'.join(str(improved.get(k) or '') for k in ('text', 'ask', 'code'))
    name_leak = any(n in applied_text.casefold() for n in names)
    if name_leak:
        accepted = False
    tool_report_path = None
    candidate_setup = None
    improver_reason = 'General supplied-evidence checklist trial' if accepted else 'Unsupported setup change or specific-answer text; rejected'
    if executable:
        from domains.food.tool_trials import try_tool, apply_change
        report = None
        accepted = False
        if name_leak:
            improver_reason = 'Specific gold identity appears in proposed applied question/tool text; rejected'
        elif improved['kind'] in {'question', 'tool'}:
            available = {'similar_brands'}
            for path in setup.get('tool_reports', []):
                available.add(read(Path(path))['tool_name'])
            available |= {improved['tool_name']} if improved['kind'] == 'tool' else set()
            missing = set(improved.get('tools') or [])-available
            if missing:
                improver_reason = f'Question/tool change names unavailable tools: {sorted(missing)}'
            else:
                if improved['kind'] == 'tool':
                    tool_report_path = folder/'tool-trial/report.json'
                    report = try_tool(improved, tool_report_path.parent,
                        {'domain': 'food', 'source_evidence': [c['source_evidence'] for c in cases]})
                candidate_setup = apply_change(setup, improved, report)
                accepted = candidate_setup is not None
                improver_reason = ('Question/tool qualified for actual source-only validator trial; not production admission'
                                   if accepted else (report or {}).get('reason', 'Question/tool proposal could not be applied'))
                if accepted and tool_report_path is not None:
                    candidate_setup['tool_reports'] = [*setup.get('tool_reports', []), str(tool_report_path.resolve())]
        else:
            improver_reason = 'Pinned source-only experiment does not execute model/web/input changes'
    write(folder / "improver-decision.json", {"accept_for_validator_experiment": accepted,
          "reason": improver_reason, 'tool_report': str(tool_report_path) if tool_report_path else None,
          'candidate_setup': str(folder/'validator-setup-v2.json') if accepted else None,
          "original_role": "validator setup improvement", "production_admission": False,
          "feedback_ids": [c["listing_id"] for c in cases], "proposal": improved})
    if accepted:
        setup = candidate_setup if executable else {**setup, "version": int(setup.get('version', 1))+1, "web": False, "use_proposals": True,
                 "checklist": setup.get('checklist', []) + [{"id": improved["step_id"] or "source_identity_check", "text": improved["text"], "status": "proposal"}]}
        write(folder / "validator-setup-v2.json", setup)
    write(folder / "manifest.json", {"feedback_partition_only": True, "feedback_ids": [c["listing_id"] for c in cases],
          'executable_contracts': executable, 'proposal_kind': kind, 'executable_candidate': candidate,
          "source": fingerprint(folder / "feedback-cases.json"), "roles": ["proposer", "improver"],
          "proposer_accepted_for_shadow": valid, "validator_setup_trial_accepted": accepted})
    print(json.dumps({"proposer": proposed, "proposer_valid": valid, "improver": improved, "improver_accepted": accepted}))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--validator", type=Path)
    ap.add_argument('--executable', action='store_true')
    a = ap.parse_args()
    execute(a.root, a.run, a.validator, executable=a.executable)
