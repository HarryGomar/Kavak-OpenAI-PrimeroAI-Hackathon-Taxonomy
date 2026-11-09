"""Loop A steps for electronics, called by the shared cycle (taxo/loop.py: steps(domain)) in place of taxo.climb.

    uv run python -m taxo.loop electronics --cycles 1 --rule-rounds 4

Per cycle the shared loop runs: 1 phase (rules) -> 2 checkpoint (human dev gold) -> 3-4 Loop B with the shared
validator (taxo.validator + validator.yaml + validator_tools.py), reviewed by the owner's gold (pedia_path), and the
shared improver's A/B -> 5 label (next silver set). Electronics differs from fragrance in one place: its rule phase is
the Codex proposer of whitelisted identity-rule edits (domains/electronics/auto.py), gated on owner dev gold and the
benchmark's train pairs, then one logged sealed read; climb's vocab hill-climb on silver does not apply (no lattice
vocabulary to edit). Every step appends a KPI row (taxo.kpis) with the two headline metrics.
"""
from __future__ import annotations

import json

from taxo import kpis
from taxo.core.config import DOMAINS_DIR, ROOT, RUNS_DIR

AGENT_CALLS = 20


def _row(domain, loop, rnd, label, m):
    from domains.electronics import graph
    r = kpis.row(domain, m, loop, rnd, label, DOMAINS_DIR / domain / "vocab.yaml", [graph.CONFIG_PATH.parent])
    r["identity_rules"] = m.get("identity_rules_version")
    kpis.append(domain, r)
    return r


def pipeline_run(domain: str, rnd: int, label: str, sealed: bool = False, agent_calls: int = AGENT_CALLS) -> dict:
    from domains.electronics import pipeline
    m = pipeline.run(agent_calls=agent_calls, sealed_purpose=label if sealed else None)
    _row(domain, "A", rnd, label, m)
    return {"dev": m["dev"], "sealed": m["sealed"], "identity_rules": m["identity_rules_version"],
            "agent": m["agent"], "seconds": m["seconds"]}


def phase(domain: str, silver: str, ph: int, rounds: int) -> list[dict]:
    """The rule phase: up to `rounds` Codex proposals, each gated (dev, then one sealed read if dev passes)."""
    from domains.electronics import auto, graph
    before = graph.load_cfg()["version"]
    auto.auto_rules(rounds, patience=3)
    learned = graph.read_yaml(graph.LEARNED_PATH) if graph.LEARNED_PATH.exists() else {"changes": []}
    return [{"phase": ph, "rules_before": before, "rules_after": graph.load_cfg()["version"],
             "proposals": [{"name": c["name"], "status": c["status"]} for c in (learned or {}).get("changes", [])]}]


def checkpoint(domain: str, ph: int) -> dict:
    """The human step: the pipeline (rules + placer agent) scored on the owner's dev gold."""
    return pipeline_run(domain, ph, f"checkpoint after rule phase {ph}")


def label(domain: str, name: str, n: int = 0, seed: int = 3):
    """Electronics' rule phase gates on owner gold and benchmark pairs, not on silver, so no silver set is drawn;
    the note keeps the shared cycle's bookkeeping."""
    d = RUNS_DIR / domain / "silver"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{name}.json"
    p.write_text(json.dumps({"silver": name, "note": "electronics Loop A gates on owner gold + benchmark pairs"}))
    return p
