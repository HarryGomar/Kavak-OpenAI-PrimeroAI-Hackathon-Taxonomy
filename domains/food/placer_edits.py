"""Pure, explicit placer-instruction edits; no automatic cleanup or default writes."""
from __future__ import annotations

import copy
import hashlib
import json


def build_candidate_card(retained, proposal, gold_names, owner_conventions):
    """Return a candidate card and edit receipt without mutating retained state.

    The trusted retained/owner policy corpus may already use a generic identity
    phrase such as Variety Pack. Only newly introduced feedback-gold label names
    outside that corpus are refused. Admission still requires actual evaluation.
    Tool qualification stays with the caller, exactly as for the append handler.
    """
    payload = json.loads(proposal['payload_json'])
    if not isinstance(payload, dict) or set(payload)-{'text', 'mode', 'tool_report'}:
        raise ValueError('Placer edit accepts only text, mode, and optional tool_report')
    text, mode = payload.get('text'), payload.get('mode', 'append')
    if not isinstance(text, str) or not text.strip():
        raise ValueError('Placer instruction proposal requires concrete text')
    if mode not in ('append', 'replace_instruction'):
        raise ValueError('Placer edit mode must be append or replace_instruction')
    tool_report = payload.get('tool_report')
    if tool_report is not None and (not isinstance(tool_report, str) or not tool_report.strip()):
        raise ValueError('tool_report must be a nonempty qualification-report path')
    before = retained['instruction']
    trusted_policy = before.casefold()+'\n'+owner_conventions.casefold()
    matches = {name.casefold() for name in gold_names if name.casefold() in text.casefold()}
    if any(name not in trusted_policy for name in matches):
        raise ValueError('New specific gold name in proposed placer instruction')
    after = before+'\nPLACER RULE CANDIDATE:\n'+text if mode == 'append' else text
    candidate = copy.deepcopy(retained)
    candidate.update(hypothesis=proposal['description'], change_id=proposal['id'], instruction=after)
    digest = lambda value: hashlib.sha256(value.encode('utf-8')).hexdigest()
    receipt = {'mode': mode, 'before_instruction_sha256': digest(before),
               'after_instruction_sha256': digest(after),
               'owner_conventions_sha256': digest(owner_conventions),
               'inherited_policy_phrases': sorted(matches), 'tool_report': tool_report,
               'retained_card_mutated': False, 'production_default_modified': False,
               'requires_actual_evaluation': True}
    return candidate, receipt
