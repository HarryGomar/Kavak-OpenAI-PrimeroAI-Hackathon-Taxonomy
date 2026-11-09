"""Shared memory: the rule library (memory/rules/*.yaml) and each rule's track record (memory/record.jsonl).

The only thing the four domains share. A rule is offered to a domain by scope; whether it is *used* there is
decided by its record on that domain's human labels.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import yaml

from taxo.core.config import MEMORY_DIR
from taxo.core.schemas import RuleSpec, Scope


def all_rules() -> list[RuleSpec]:
    rules = []
    for f in sorted((MEMORY_DIR / "rules").glob("*.yaml")):
        rules += [RuleSpec(**r) for r in yaml.safe_load(f.read_text(encoding="utf-8")) or []]
    return rules


def rules_for(domain: str, families: tuple[str, ...] = ()) -> list[RuleSpec]:
    """Universal rules, family rules for the domain's families, and the domain's own rules."""
    out = []
    for r in all_rules():
        if r.scope == Scope.UNIVERSAL and (not r.domains or domain in r.domains):
            out.append(r)
        elif r.scope == Scope.FAMILY and set(r.domains) & set(families):
            out.append(r)
        elif r.scope == Scope.DOMAIN and domain in r.domains:
            out.append(r)
    return out


def record(rule_id: str, domain: str, **outcome) -> None:
    """Append one outcome (caught, false_rejects, admitted, ...) to the rule's track record."""
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "rule": rule_id, "domain": domain, **outcome}
    with open(MEMORY_DIR / "record.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def history(rule_id: str) -> list[dict]:
    path = MEMORY_DIR / "record.jsonl"
    if not path.exists():
        return []
    return [e for e in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if e["rule"] == rule_id]
