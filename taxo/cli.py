"""Entry point.

    uv run python -m taxo.cli inspect <domain>        counts, a few listings, rules enabled (no model calls)
    uv run python -m taxo.cli place <domain> --n 5    run the placer through installed Codex CLI FAST
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from taxo import memory
from taxo.core import domain as domains
from taxo.core.ledger import Ledger


def inspect(name: str, limit: int = 50) -> None:
    d = domains.load(name)
    listings = list(d.listings(limit=limit))
    nodes = list(d.nodes())
    print(f"{name}: {len(listings)} sampled listings (limit={limit}), {len(nodes)} taxonomy nodes")
    if not nodes:
        print(f"raw-only bootstrap: python -m taxo.pipeline {name} --construct --limit {limit}")
    print("rule status:", [(r.id, r.status.value) for r in memory.rules_for(name, tuple(d.pack.get("families", [])))])
    for l in random.Random(0).sample(listings, min(3, len(listings))):
        print(" -", l.source, "|", l.title[:100])


def place(name: str, n: int) -> None:
    d = domains.load(name)
    nodes = {x.id: x for x in d.nodes()}
    if not nodes:
        raise ValueError(f"{name}: no taxonomy nodes; use python -m taxo.pipeline {name} --construct before placement")
    from taxo.roles.runtime import run_sync
    from taxo.validate_cli import evidence
    from taxo.roles.placer import PlaceContext, make_placer
    ctx = PlaceContext(name, nodes, memory.rules_for(name, tuple(d.pack.get("families", []))))
    agent = make_placer(name, d.pack.get("conventions", ""))
    ledger = Ledger()
    sample = random.Random(0).sample(list(d.listings()), n)
    for l in sample:
        ctx.listing = l
        result = run_sync(agent, "Listing evidence:\n" + json.dumps(evidence(l.model_dump(mode="json"))), context=ctx)
        out = result.final_output
        if out.node_id is not None:
            if out.node_id not in nodes:
                raise ValueError(f"placer returned unknown node {out.node_id}")
            from taxo.core.rules import run_rules
            findings = run_rules(ctx.rules, l, nodes[out.node_id], nodes)
            if findings.vetoed or findings.abstain:
                raise ValueError(f"placer choice blocked by admitted rules for {l.id}")
        ledger.append("placement", domain=name, listing_id=l.id, node_id=out.node_id, confidence=out.confidence,
                      reason=out.reason, by=agent.name, cli_artifacts=str(result.artifacts))
        print(f"{l.title[:70]!r} -> {nodes[out.node_id].path if out.node_id in nodes else None} ({out.confidence:.2f})")


def main() -> None:
    p = argparse.ArgumentParser(prog="taxo")
    sub = p.add_subparsers(dest="cmd", required=True)
    ins = sub.add_parser("inspect")
    ins.add_argument("domain", choices=domains.DOMAINS)
    ins.add_argument("--limit", type=int, default=50)
    pl = sub.add_parser("place")
    pl.add_argument("domain", choices=domains.DOMAINS)
    pl.add_argument("--n", type=int, default=5)
    role = sub.add_parser("run-role", help="run validator, proposer or improver via pinned Codex CLI FAST")
    role.add_argument("domain", choices=domains.DOMAINS)
    role.add_argument("role", choices=("validator", "proposer", "improver"))
    role.add_argument("--input", type=Path, required=True, help="JSON evidence; see docs/codex-cli-validator.md")
    role.add_argument("--output", type=Path, required=True, help="fresh directory outside Git")
    a = p.parse_args()
    if a.cmd == "inspect":
        inspect(a.domain, a.limit)
    elif a.cmd == "place":
        place(a.domain, a.n)
    else:
        from taxo.roles.runtime import run_sync
        payload = json.loads(a.input.read_text(encoding="utf-8"))
        context = None
        if a.role == "validator":
            from taxo.roles.validator import ValidateContext, make_validator
            from taxo.validate_cli import evidence
            agent = make_validator(a.domain)
            # Validator input is exactly one adapter Listing plus optional source brand pool, never a placement.
            from taxo.core.schemas import Listing
            listing = Listing.model_validate(payload["listing"])
            if listing.domain != a.domain:
                raise ValueError("Validator listing domain mismatch")
            context = ValidateContext(a.domain, payload.get("brands", []))
            payload = evidence(listing.model_dump(mode="json"))
        elif a.role == "proposer":
            from taxo.roles.proposer import make_proposer
            agent = make_proposer(a.domain)
        else:
            from taxo.roles.improver import make_improver
            agent = make_improver(a.domain)
        result = run_sync(agent, json.dumps(payload, ensure_ascii=False), context=context, output=a.output)
        print(result.final_output.model_dump_json())


if __name__ == "__main__":
    main()
