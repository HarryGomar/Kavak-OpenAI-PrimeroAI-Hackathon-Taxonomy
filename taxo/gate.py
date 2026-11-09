"""The Loop A gate (SPEC §5.1), in code: keep a change only if, on SEALED gold, scored in one logged read,
  - exact does not fall, and either exact rises or the agent share falls;
  - the change touches at least MIN_TOUCHED sealed rows, so the test could have failed;
  - the Wilson lower bound of (rows it made better) / (rows it changed class) clears BAR.

    uv run python -m taxo.gate fragrance runs/fragrance/r0 runs/fragrance --round 1 --label "..."
Both dirs hold a placements.jsonl and metrics.json from taxo.pipeline. One sealed read scores both.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from taxo import gold as goldmod, kpis, score
from taxo.core.config import ROOT, RUNS_DIR
from taxo.core.metrics import wilson
from taxo.parse import Brands
from taxo.pipeline import load_gold

MIN_TOUCHED = 10
BAR = 0.5
RANK = {"exact": 5, "shallower": 4, "no_brand": 3, "deeper": 2, "wrong": 1, "wrong_brand": 0}


def wilson_lower(k: int, n: int) -> float:
    return wilson(k, n)[0] if n else 0.0


def _placed(d: Path) -> dict[str, dict]:
    out = {}
    for line in open(d / "placements.jsonl", encoding="utf-8"):
        p = json.loads(line)
        for g in p["gold"]:
            out[g] = p
    return out


def compare(rows, before: dict, after: dict, brands: Brands) -> dict:
    rep_b, rep_a, better, worse, touched, changes = score.Report(), score.Report(), 0, 0, 0, []
    for g in rows:
        bt = {t for r in brands.runs(g.brand) for t in r}
        jb, ja = (score.judge(x[g.id]["brand"], x[g.id]["path"], g.brand, g.expected_path, bt, g.compare, g.expect)
                  for x in (before, after))
        rep_b.add(jb, g.expect)
        rep_a.add(ja, g.expect)
        touched += (before[g.id]["brand"], before[g.id]["path"]) != (after[g.id]["brand"], after[g.id]["path"])
        if g.expect == "accept" and jb.cls != ja.cls:
            better += RANK[ja.cls] > RANK[jb.cls]
            worse += RANK[ja.cls] < RANK[jb.cls]
            changes.append({"dir": "better" if RANK[ja.cls] > RANK[jb.cls] else "worse", "title": g.title[:100],
                            "before": f"{jb.cls}: {' > '.join(before[g.id]['path'])}",
                            "after": f"{ja.cls}: {' > '.join(after[g.id]['path'])}", "gold": " > ".join(g.expected_path)})
        if g.expect == "reject" and jb.reject_ok != ja.reject_ok:
            better += bool(ja.reject_ok)
            worse += not ja.reject_ok
    return {"before": rep_b.summary(), "after": rep_a.summary(), "touched": touched, "better": better, "worse": worse,
            "changes": changes}


def decide(c: dict, agent_before: float, agent_after: float) -> tuple[bool, list[str]]:
    b, a = c["before"], c["after"]
    lb = wilson_lower(c["better"], c["better"] + c["worse"])
    checks = [
        (a["exact"] >= b["exact"], f"exact {b['exact']} -> {a['exact']} does not fall"),
        (a["exact"] > b["exact"] or agent_after < agent_before,
         f"exact rises or agent share falls ({agent_before:.3f} -> {agent_after:.3f})"),
        (c["touched"] >= MIN_TOUCHED, f"touches {c['touched']} sealed rows (>= {MIN_TOUCHED})"),
        (lb >= BAR, f"better {c['better']} of {c['better'] + c['worse']} changed: Wilson lower bound {lb:.2f} >= {BAR}"),
    ]
    return all(ok for ok, _ in checks), [("PASS " if ok else "FAIL ") + why for ok, why in checks]


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.gate")
    ap.add_argument("domain", choices=["fragrance", "food"])
    ap.add_argument("before", type=Path)
    ap.add_argument("after", type=Path)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--data", choices=["drive", "edu"], default="drive")
    ap.add_argument("--dev", action="store_true", help="diff on dev gold only: no sealed read, no KPI row, no decision")
    a = ap.parse_args()
    rows, human, names = load_gold(a.data, a.domain)
    brands = Brands(names)
    g = goldmod.Gold(rows, RUNS_DIR / a.domain / "sealed_reads.jsonl")
    if a.dev:
        c = compare(g.dev, _placed(a.before), _placed(a.after), brands)
        print(json.dumps({k: c[k] for k in ("touched", "better", "worse", "changes")}, indent=1, ensure_ascii=False))
        print("dev exact", c["before"]["exact"], "->", c["after"]["exact"], "| harm", c["before"]["harm_rate"], "->",
              c["after"]["harm_rate"])
        return
    sealed = g.sealed(f"gate: loop A round {a.round}: {a.label} ({a.data} gold + human)")
    before, after = _placed(a.before), _placed(a.after)
    c = compare(sealed, before, after, brands)
    c.pop("changes")                                  # which sealed rows moved stays unseen: sealed is not for tuning
    hs = [r for r in human if goldmod.is_sealed(r.brand) and r.id in before and r.id in after]   # same read
    h = compare(hs, before, after, brands) if human is not rows else None
    mb, ma = (json.loads((d / "metrics.json").read_text(encoding="utf-8")) for d in (a.before, a.after))
    ab, aa = mb["shares_subset"]["to_agent"][1], ma["shares_subset"]["to_agent"][1]
    keep, why = decide(c, ab, aa)
    out = {"round": a.round, "label": a.label, "keep": keep, "why": why, **c, "agent_before": ab, "agent_after": aa,
           "sealed_reads_total": g.reads()}
    if h:
        out["human_sealed"] = {"before": h["before"], "after": h["after"], "better": h["better"], "worse": h["worse"]}
        ma["human_sealed"] = h["after"]
    (a.after / f"gate-r{a.round}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    ma["sealed"], ma["sealed_reads_logged"] = c["after"], g.reads()
    kpis.append(a.domain, kpis.row(a.domain, ma, "A", a.round, f"gate {'KEPT' if keep else 'DROPPED'}: {a.label}",
                                   ROOT / "domains" / a.domain / "vocab.yaml",
                                   [ROOT / "rules" / a.domain, ROOT / "rules" / "global"]))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
