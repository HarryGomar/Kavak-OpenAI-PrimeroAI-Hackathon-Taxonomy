"""Both loops, end to end, no one in between (SPEC §5): many cheap rule rounds on silver, then one human round that
checks the rules and improves the validator, then again.

    uv run python -m taxo.loop fragrance --cycles 2 --rule-rounds 6

One cycle:
  1. rules     taxo.climb phase on the current silver set: hill-climb vocab edits and rule on/off, gated on silver
  2. check     human checkpoint: Pedia dev gold + one logged sealed read (did silver-trained rules really improve?)
  3. human     Loop B round: fresh Pedia-labelled sample, the validator labels it blind, Pedia settles disagreements
  4. improve   Codex proposes checklist steps from the validator's misses on human labels; A/B on a fresh sample;
               kept only if exact rises and harm does not (validator.yaml version + 1)
  5. silver    a fresh silver set labelled by the current validator, for the next cycle's rule phase
Pedia's label stands in for the person (the project's choice for testing). Every step writes a KPI row.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from taxo import climb, kpis, loopb, score, validator
from taxo.core.config import DOMAINS_DIR, ROOT, RUNS_DIR
from taxo.lattice.vocab import tokens

STEP_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["steps"],
               "properties": {"steps": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["id", "text", "fixes"],
                   "properties": {"id": {"type": "string"}, "text": {"type": "string"},
                                  "fixes": {"type": "string"}}}}}}


def _say(msg: str) -> None:
    print(msg, flush=True)


def _next_v(domain: str) -> str:
    d = RUNS_DIR / domain / "loopb"
    used = [int(m.group(1)) for f in d.glob("V*-blind.jsonl") if (m := re.match(r"V(\d+)-blind", f.name))]
    return f"V{max(used, default=0) + 1}"


def _next_s(domain: str) -> str:
    d = RUNS_DIR / domain / "silver"
    used = [int(m.group(1)) for f in d.glob("S*.jsonl") if (m := re.match(r"S(\d+)\.jsonl$", f.name))]
    return f"S{max(used, default=0) + 1}"


def _row(domain: str, loop: str, rnd: int, label: str, silver: dict) -> None:
    m = json.loads((RUNS_DIR / domain / "metrics.json").read_text(encoding="utf-8"))
    kpis.append(domain, kpis.row(domain, m, loop, rnd, label, DOMAINS_DIR / domain / "vocab.yaml",
                                 [ROOT / "rules" / domain, ROOT / "rules" / "global"], silver=silver))


def _misses(domain: str, version: str, suffix: str = "") -> list[dict]:
    """The validator's labels on a Pedia-labelled sample that the scorer does not call exact, with the human answer."""
    d = RUNS_DIR / domain / "loopb"
    P = {json.loads(x)["id"]: json.loads(x) for x in open(RUNS_DIR / domain / "placements.jsonl", encoding="utf-8")}
    blind = {json.loads(x)["id"]: json.loads(x) for x in open(d / f"{version}-blind.jsonl", encoding="utf-8")}
    out = []
    for x in open(d / f"{version}-validator{suffix}.jsonl", encoding="utf-8"):
        v = json.loads(x)
        p = P[v["id"]]
        gp = p["pedia_path"]
        j = score.judge(p["pedia_brand"], v["path"], p["pedia_brand"], gp, set(tokens(gp[0])))
        if j.cls != "exact":
            out.append({"title": blind[v["id"]]["title"], "validator": " > ".join(v["path"]),
                        "human": " > ".join(gp), "class": j.cls})
    return out


def propose_steps(domain: str, misses: list[dict], log: Path) -> list[dict]:
    """Codex as the improver: up to 3 general checklist steps that would fix these misses (no per-item answers)."""
    c = validator.card(domain)
    active = [s["text"] for s in c.get("checklist") or [] if s.get("status") == "active"]
    text = ("You improve the instructions of a labeller that places fragrance listings on a product tree.\n\n"
            "Its instructions:\n" + c["task"].strip()
            + ("\n\nIts current checklist:\n" + "\n".join(f"- {s}" for s in active) if active else "")
            + "\n\nBelow are listings it got wrong: its answer and the human's answer. Write at most 3 new checklist "
              "steps that state GENERAL conventions (true for many listings) that would have fixed several of these. "
              "Never mention a specific product or brand by name as the rule itself; never write a step that fixes a "
              "single listing. Do not run commands or read files.\n\n"
            + json.dumps(misses, ensure_ascii=False, indent=0))
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "schema.json").write_text(json.dumps(STEP_SCHEMA), encoding="utf-8")
        cmd = [shutil.which("codex") or "codex", "exec", "--ignore-user-config", "--sandbox", "read-only",
               "--skip-git-repo-check", "--ephemeral", "--color", "never", "-C", tmp,
               "--output-schema", str(t / "schema.json"), "-o", str(t / "out.json"), "-"]
        p = subprocess.run(cmd, input=text, capture_output=True, text=True, encoding="utf-8", timeout=1800)
        raw = (t / "out.json").read_text(encoding="utf-8") if (t / "out.json").exists() else ""
    log.write_text(f"exit {p.returncode}\n--- stderr\n{p.stderr[-3000:]}\n--- answer\n{raw}", encoding="utf-8")
    try:
        return json.loads(raw)["steps"][:3]
    except (json.JSONDecodeError, KeyError, TypeError):
        return []


def improve_validator(domain: str, cyc: int) -> dict:
    """Loop B: one human round with the current validator, then an A/B of Codex-proposed steps on a fresh sample."""
    d = RUNS_DIR / domain / "loopb"
    # 3. human round with the current validator
    v = _next_v(domain)
    loopb.sample(domain, v, pool="pedia-dev")
    validator.run(domain, v)
    loopb.compare(domain, v)
    loopb.pedia_verdicts(domain, v)
    s = loopb.settle(domain, v, d / f"{v}-verdicts.json")
    _say(f"  human round {v}: validator vs human exact {s['validator_vs_pedia']['exact_rate']}, "
         f"agreement with pipeline {s['agreement']}, pipeline errors found {s['pipeline_wrong_found']}")
    # 4. improver: steps from this round's misses (and the previous round's), A/B on a fresh sample
    prev = f"V{int(v[1:]) - 1}"
    misses = _misses(domain, v) + (_misses(domain, prev) if (d / f"{prev}-validator.jsonl").exists() else [])
    steps = propose_steps(domain, misses, d / f"{v}-improver.log")
    if not steps:
        _say("  improver proposed no steps")
        return {"round": v, "kept": False, "human": s}
    c = validator.card(domain)
    cand = {**c, "version": c.get("version", 1) + 1,
            "checklist": (c.get("checklist") or []) + [{"id": st["id"], "text": st["text"], "status": "active",
                                                        "origin": f"improver {v}: {st['fixes']}"} for st in steps]}
    ab = _next_v(domain)
    loopb.sample(domain, ab, pool="pedia-dev")
    items = [json.loads(x) for x in open(d / f"{ab}-blind.jsonl", encoding="utf-8")]
    cur = validator.label(domain, items, d / f"{ab}-validator.log")
    new = validator.label(domain, items, d / f"{ab}-validator-cand.log", c=cand)
    (d / f"{ab}-validator.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in cur), "utf-8")
    (d / f"{ab}-validator-cand.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in new), "utf-8")
    a, b = loopb.validator_vs_pedia(domain, ab), loopb.validator_vs_pedia(domain, ab, "-cand")
    keep = b["exact"] > a["exact"] and b["harm_rate"] <= a["harm_rate"]
    result = {"round": ab, "current": a, "candidate": b, "steps": steps, "kept": keep,
              "card": f"v{c.get('version', 1)}" + (f" -> v{cand['version']}" if keep else " (unchanged)")}
    (d / f"{ab}-improver-ab.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
    if keep:
        path = DOMAINS_DIR / domain / "validator.yaml"
        head = "".join(ln for ln in path.read_text(encoding="utf-8").splitlines(keepends=True) if ln.startswith("#"))
        path.write_text(head + yaml.safe_dump(cand, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
    _say(f"  improver A/B {ab}: current {a['exact_rate']} (harm {a['harm_rate']}) vs candidate {b['exact_rate']} "
         f"(harm {b['harm_rate']}) -> {'KEPT' if keep else 'dropped'}")
    _row(domain, "B", cyc * 100 + 2, f"validator improver cycle {cyc}: {'KEPT' if keep else 'dropped'} "
         f"({len(steps)} steps)", {"version": ab, "validator": "codex-cli", "reviewer": "pedia",
                                   "agreement": None, "ab": {"current": a, "candidate": b}, "kept": keep})
    return result


def cycle(domain: str, cyc: int, silver: str, rounds: int, skip_rules: bool = False) -> dict:
    out: dict = {"cycle": cyc, "silver": silver}
    if not skip_rules:
        _say(f"cycle {cyc}: 1. rule phase on silver {silver}")
        out["rules"] = climb.phase(domain, silver, cyc, rounds)
    _say(f"cycle {cyc}: 2. human checkpoint")
    out["checkpoint"] = climb.checkpoint(domain, cyc)
    _say(f"  checkpoint: {out['checkpoint']}")
    _say(f"cycle {cyc}: 3-4. human round and validator improvement")
    out["validator"] = improve_validator(domain, cyc)
    nxt = _next_s(domain)
    _say(f"cycle {cyc}: 5. fresh silver set {nxt} with the current validator")
    climb.label(domain, nxt, seed=100 + cyc)
    out["next_silver"] = nxt
    (RUNS_DIR / domain / f"cycle{cyc}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.loop")
    ap.add_argument("domain")
    ap.add_argument("--cycles", type=int, default=2)
    ap.add_argument("--rule-rounds", type=int, default=6)
    ap.add_argument("--start", type=int, default=1, help="number of the first cycle")
    ap.add_argument("--silver", default="S1", help="silver set for the first cycle's rule phase")
    ap.add_argument("--skip-first-rules", action="store_true", help="the first cycle's rule phase already ran")
    a = ap.parse_args()
    silver = a.silver
    for k in range(a.start, a.start + a.cycles):
        res = cycle(a.domain, k, silver, a.rule_rounds, skip_rules=a.skip_first_rules and k == a.start)
        silver = res["next_silver"]
    print(kpis.table(kpis.history(a.domain)[-12:]))


if __name__ == "__main__":
    main()
