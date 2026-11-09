"""Electronics KPI rows in the team's format (taxo/kpis.py: runs/electronics/kpis.jsonl, `python -m taxo.kpis electronics`).

    uv run python -m domains.electronics.kpis row --loop A --round 3 --label "auto rules: 3 dropped"
    uv run python -m domains.electronics.kpis history          the two headline metrics per round, as a table

The two headline metrics, both on the owner's DEV gold (sealed is read only by the gate):
  rules right       share of gold listings the rules (+ placer agent) place exactly right; harm = deeper/wrong/wrong brand
  validator safe    share of gold listings where the validator's own label is NOT harmful (1 - harm), its exact rate,
                    and its flag precision (when it says the pipeline is wrong, how often it is)
Every rate carries a 95% Wilson interval (taxo.core.metrics.rate). With few gold rows the interval is wide: say so.
"""
from __future__ import annotations

import argparse
import hashlib
import json

from domains.electronics import graph
from domains.electronics.loop import CATS, OUT, ejudge, gold_rows, read_jsonl, rules_only, type_labels, vdir
from taxo import gold as goldmod, kpis
from taxo.core.metrics import rate


def _summ(classes, n):
    keys = ("exact", "shallower", "deeper", "wrong", "wrong_brand", "no_brand")
    c = {k: classes.get(k, 0) for k in keys}
    d = max(n, 1)
    return {"accept_rows": n, **c, "exact_rate": round(c["exact"] / d, 3),
            "right_or_shallower": round((c["exact"] + c["shallower"]) / d, 3),
            "harm_rate": round((c["deeper"] + c["wrong"] + c["wrong_brand"]) / d, 3),
            "levels": {}, "reject_rows": 0, "rejects_held": 0}


def score_paths(paths, dev, lid, tl):
    cl = {}
    for r in dev:
        k = ejudge(paths.get(lid[r.id], []), r.expected_path, tl)
        cl[k] = cl.get(k, 0) + 1
    return _summ(cl, len(dev))


def validator_score(ver, rnd, dev, lid, tl, ppaths):
    vlog = {x["listing_id"]: x for x in read_jsonl(vdir(rnd, ver) / "validator.jsonl")}
    rows = [r for r in dev if lid[r.id] in vlog]
    s = score_paths({k: v["validator_path"] for k, v in vlog.items()}, rows, lid, tl)
    flags = right = 0
    for r in rows:
        x = vlog[lid[r.id]]
        if x["relation"] != "same":
            flags += 1
            right += ejudge(ppaths.get(lid[r.id], []), r.expected_path, tl) not in ("exact", "shallower")
    n = s["accept_rows"]
    harm = round(s["harm_rate"] * n)
    return {"version": ver, "rows": n, "exact": rate(s["exact"], n), "not_harmful": rate(n - harm, n),
            "flag_precision": rate(right, flags) if flags else None}


def build_row(loop, rnd, label, validator_version=None, validator_round=1, cfg=None):
    rows, lid, files = gold_rows()
    g = goldmod.Gold(rows, OUT / "sealed-reads.jsonl")
    dev = [r for r in g.dev if r.expect == "accept"]
    tl = type_labels()
    m = json.loads((OUT / "metrics.json").read_text())
    cfg = cfg or graph.load_cfg()
    pl, _, _, _ = rules_only(cfg)                       # rules = steps 1-5, no agent: what the rules alone get right
    rules = score_paths(pl, dev, lid, tl)
    result = {"listings": m["in_scope"], "dev": rules, "sealed": None, "data": "deepmatcher",
              "gold_by_origin": {f.name: 1 for f in files},
              "shares_subset": {"placed_by_lattice": [0, m["settled_by_step_in_scope"].get("lattice")],
                                "to_agent": [0, round(m["agent"].get("routed", 0) / max(m["in_scope"], 1), 3)],
                                "placed_by_agent": [0, m["settled_by_step_in_scope"].get("agent")]},
              "agent_calls": m["agent"].get("calls", 0), "secs": m.get("seconds")}
    row = kpis.row("electronics", result, loop, rnd, label, graph.CONFIG_PATH, [graph.CONFIG_PATH.parent])
    row["identity_rules"] = cfg["version"]
    row["rules_right"] = {"exact": rate(rules["exact"], rules["accept_rows"]),
                          "not_harmful": rate(rules["accept_rows"] - round(rules["harm_rate"] * rules["accept_rows"]),
                                              rules["accept_rows"])}
    if validator_version:
        row["validator"] = validator_score(validator_version, validator_round, dev, lid, tl, pl)
    row["pair_eval_validation"] = (m.get("pair_evaluation") or {}).get("validation")
    return row


def history():
    rows = [r for r in kpis.history("electronics") if "rules_right" in r]
    f = lambda c: "-" if not c else f"{c['k']}/{c['n']} = {c['p']:.2f} [{c['lo']:.2f}-{c['hi']:.2f}]"
    out = ["| loop/round | label | rules | rules right (exact) | rules not harmful | validator | validator exact | "
           "validator not harmful | flag precision |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        v = r.get("validator") or {}
        out.append(f"| {r['loop']}/{r['round']} | {r['label']} | {r['identity_rules']} | {f(r['rules_right']['exact'])} | "
                   f"{f(r['rules_right']['not_harmful'])} | {('v' + str(v['version'])) if v else '-'} | {f(v.get('exact'))} | "
                   f"{f(v.get('not_harmful'))} | {f(v.get('flag_precision'))} |")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("row")
    r.add_argument("--loop", required=True)
    r.add_argument("--round", type=int, required=True)
    r.add_argument("--label", required=True)
    r.add_argument("--validator", type=int, default=None)
    sub.add_parser("history")
    sub.add_parser("backfill", help="rows for rounds 00-03 from the rule and validator versions they used")
    a = ap.parse_args()
    if a.cmd == "row":
        row = build_row(a.loop, a.round, a.label, a.validator)
        kpis.append("electronics", row)
        print(json.dumps({k: row[k] for k in ("loop", "round", "identity_rules", "rules_right", "validator")
                          if k in row}, indent=1))
    elif a.cmd == "backfill":
        import subprocess, yaml
        v040 = yaml.safe_load(subprocess.run(["git", "show", "origin/cars-pipeline~3:domains/electronics/identity.yaml"],
                                             capture_output=True, text=True, check=True).stdout)
        v050 = graph.read_yaml(graph.CONFIG_PATH)
        for loop, rnd, label, ver, cfg in (("A", 0, "baseline rules", None, v040),
                                           ("B", 1, "validator v1", 1, v040),
                                           ("B", 2, "validator v3 (query fix)", 3, v040),
                                           ("A", 2, "rule kept: field part in own text", 3, v050),
                                           ("A", 3, "auto: 3 proposals dropped", 3, v050),
                                           ("B", 3, "auto: validator v4 kept", 4, v050)):
            kpis.append("electronics", build_row(loop, rnd, label, ver, 1, cfg))
        print(history())
    else:
        print(history())
