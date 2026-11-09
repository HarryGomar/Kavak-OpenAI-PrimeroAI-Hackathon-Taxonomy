"""Entry point.

    uv run python -m taxo.cli inspect <domain>        counts, a few listings, rules enabled (no model calls)
    uv run python -m taxo.cli place <domain> --n 5    run the placer agent on n listings (Codex CLI; --runner sdk
                                                      uses OPENAI_API_KEY)
"""
from __future__ import annotations

import argparse
import random

from taxo import memory
from taxo.core import domain as domains
from taxo.core.ledger import Ledger


def inspect(name: str) -> None:
    d = domains.load(name)
    listings = list(d.listings())
    nodes = d.nodes()
    print(f"{name}: {len(listings)} listings, {len(nodes)} taxonomy nodes")
    print("rules enabled:", [r.id for r in memory.rules_for(name, tuple(d.pack.get("families", [])))])
    for l in random.Random(0).sample(listings, min(3, len(listings))):
        print(" -", l.source, "|", l.title[:100])


def place(name: str, n: int, runner: str = "cli") -> None:
    from taxo.core.codex import runner as pick_runner  # only needed when calling models
    from taxo.roles.placer import PlaceContext, make_placer

    run = pick_runner(runner)
    if run is None:
        raise SystemExit("cli: the `codex` CLI is needed on PATH" if runner == "cli" else "sdk: set OPENAI_API_KEY")
    d = domains.load(name)
    nodes = {x.id: x for x in d.nodes()}
    ctx = PlaceContext(name, nodes, memory.rules_for(name, tuple(d.pack.get("families", []))))
    agent = make_placer(name, d.pack.get("conventions", ""))
    ledger = Ledger()
    sample = random.Random(0).sample(list(d.listings()), n)
    for l in sample:
        out = run(agent, f"Listing title: {l.title}\nSource: {l.source}\nBrand field: {l.brand}", ctx).final_output
        ledger.append("placement", domain=name, listing_id=l.id, node_id=out.node_id, confidence=out.confidence,
                      reason=out.reason, by=agent.name)
        print(f"{l.title[:70]!r} -> {nodes[out.node_id].path if out.node_id in nodes else None} ({out.confidence:.2f})")


def main() -> None:
    p = argparse.ArgumentParser(prog="taxo")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("inspect").add_argument("domain", choices=domains.DOMAINS)
    pl = sub.add_parser("place")
    pl.add_argument("domain", choices=domains.DOMAINS)
    pl.add_argument("--n", type=int, default=5)
    pl.add_argument("--runner", choices=["cli", "sdk"], default="cli",
                    help="cli: the Codex CLI (ChatGPT login); sdk: the Agents SDK (OPENAI_API_KEY)")
    a = p.parse_args()
    inspect(a.domain) if a.cmd == "inspect" else place(a.domain, a.n, a.runner)


if __name__ == "__main__":
    main()
