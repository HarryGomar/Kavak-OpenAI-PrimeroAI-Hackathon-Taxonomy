"""Curator (code, not an agent): keeps the books. It admits, promotes and retires rules on their record: what a rule
caught and wrongly rejected against the frozen, gold-scored validator's silver (and gold where gold exists). It is the
only role that reads labels, so no agent can be fooled into, or fool anyone by, reading the truth. The sealed gold
gate (taxo/gate.py) still has the last word before a rule goes active.

Stub: the admission test and promotion rule are written; wiring them to runs comes next.
"""
from __future__ import annotations

from taxo import memory
from taxo.core.schemas import RuleSpec

K_PER_FALSE_REJECT = 5  # a rule must catch at least k bad placements per good one it rejects


def admit(rule: RuleSpec, domain: str, caught: int, false_rejects: int, planted_fault_fires: bool,
          known_good_quiet: bool) -> bool:
    """Admit a rule into a domain only if it is a real check (fires on a planted fault, quiet on a known-good
    case) and it pays on dev labels (k caught per false reject)."""
    ok = planted_fault_fires and known_good_quiet and caught >= K_PER_FALSE_REJECT * max(false_rejects, 1)
    memory.record(rule.id, domain, caught=caught, false_rejects=false_rejects, admitted=ok,
                  check_fires=planted_fault_fires, check_quiet=known_good_quiet)
    return ok


def promotable(rule_id: str) -> bool:
    """A domain rule becomes universal once it was admitted in two different domains."""
    domains = {e["domain"] for e in memory.history(rule_id) if e.get("admitted")}
    return len(domains) >= 2
