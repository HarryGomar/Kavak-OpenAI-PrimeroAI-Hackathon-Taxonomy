"""First-match evaluator for YAML rules (SPEC §4.1). Not Pedia's interpreter: a rule is a list of `when` conditions,
all of which must hold, and one `then` dict the pipeline acts on.

    id: veto/concentration-conflict
    stage: place                                   # which pipeline step asks (place | route)
    when:
      - {fact: placement.step, eq: lattice}        # ops: eq ne in not_in ge gt le lt missing present
      - {check: concentration_conflict}            # a check from taxo/tools/checks.py fires on (listing, node)
    then: {veto: true, route: agent_title}
    status: active                                 # active | shadow | proposal | retired
    why: "..."

Only ACTIVE rules decide, first match in file order. SHADOW rules are evaluated after and logged only when their
`then` would change the answer. PROPOSAL and RETIRED rules never run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from taxo.tools import checks

_MISSING = object()


@dataclass
class Rule:
    id: str
    when: list[dict]
    then: dict
    status: str = "proposal"
    stage: str = "place"
    why: str = ""
    path: str = ""


@dataclass
class Outcome:
    rule: str | None = None
    then: dict = field(default_factory=dict)
    detail: str = ""
    shadow: list[tuple[str, dict, str]] = field(default_factory=list)   # (rule id, would-be then, detail)


def load(*dirs: Path) -> list[Rule]:
    """Every *.yaml under the given dirs, in dir order then file name order. A file holds one rule or a list."""
    out: list[Rule] = []
    for d in dirs:
        for p in sorted(Path(d).glob("*.yaml")):
            doc = yaml.safe_load(p.read_text(encoding="utf-8")) or []
            for r in doc if isinstance(doc, list) else [doc]:
                if "check" in r:  # RuleSpec: a different engine, loaded by memory.rules_for
                    continue
                if "when" not in r or "then" not in r:
                    raise ValueError(f"{p}: evaluator rules require when and then")
                if r.get("status", "proposal") not in {"active", "shadow", "proposal", "retired"}:
                    raise ValueError(f"{p}: invalid evaluator status")
                out.append(Rule(id=r["id"], when=r.get("when") or [], then=r.get("then") or {},
                                status=r.get("status", "proposal"), stage=r.get("stage", "place"),
                                why=r.get("why", ""), path=str(p)))
    return out


def fact(facts: dict, name: str) -> Any:
    v: Any = facts
    for part in name.split("."):
        if not isinstance(v, dict) or part not in v:
            return _MISSING
        v = v[part]
    return v


_OPS = {"eq": lambda v, w: v == w, "ne": lambda v, w: v != w, "in": lambda v, w: v in w,
        "not_in": lambda v, w: v not in w, "ge": lambda v, w: v >= w, "gt": lambda v, w: v > w,
        "le": lambda v, w: v <= w, "lt": lambda v, w: v < w}


def _cond(c: dict, facts: dict, ctx: dict) -> tuple[bool, str]:
    if "check" in c:
        if not ctx.get("node"):
            return False, ""
        f = checks.run(c["check"], ctx["listing"], ctx["node"], ctx.get("tax", {}), **(c.get("params") or {}))
        return (f is not None), (f.detail if f else "")
    v = fact(facts, c["fact"])
    absent = v is _MISSING or v is None or v == ""
    if "missing" in c:
        return absent == bool(c["missing"]), ""
    if "present" in c:
        return (not absent) == bool(c["present"]), ""
    if absent:
        return False, ""
    return all(_OPS[op](v, want) for op, want in c.items() if op != "fact"), ""


def matches(rule: Rule, facts: dict, ctx: dict | None = None) -> tuple[bool, str]:
    details = []
    for c in rule.when:
        ok, d = _cond(c, facts, ctx or {})
        if not ok:
            return False, ""
        if d:
            details.append(d)
    return True, "; ".join(details)


def evaluate(rules: list[Rule], stage: str, facts: dict, ctx: dict | None = None) -> Outcome:
    out = Outcome()
    staged = [r for r in rules if r.stage == stage]
    for r in staged:
        if r.status == "active":
            ok, detail = matches(r, facts, ctx)
            if ok:
                out.rule, out.then, out.detail = r.id, dict(r.then), detail
                break
    for r in staged:
        if r.status == "shadow":
            ok, detail = matches(r, facts, ctx)
            if ok and r.then != out.then:
                out.shadow.append((r.id, dict(r.then), detail))
    return out
