"""Write a cars round record from the run artefacts (round 02 on): rounds/cars/round-NN.md, the decisions CSV and one
memory/record.jsonl line. Totals (Codex calls, seconds, tokens) come from runs/cars/ledger.jsonl entries since the round
started (the round's first auto_rules_start entry).

    uv run python -m domains.cars.rounds --round 2 --label "..."
"""
from __future__ import annotations

import argparse
import csv
import json

from taxo.core.config import ROOT, RUNS_DIR
from taxo.core.io import read_jsonl

OUT = RUNS_DIR / "cars"


def ledger_since(rnd: int) -> tuple[dict, dict]:
    started, roles, events = False, {}, {}
    for e in read_jsonl(OUT / "ledger.jsonl"):
        if e["kind"] == "auto_rules_start" and e.get("round") == rnd:
            started = True
        if not started:
            continue
        events[e["kind"]] = events.get(e["kind"], 0) + 1
        if e["kind"] != "codex_call":
            continue
        t = roles.setdefault(e.get("role", "?"), {"calls": 0, "cache_hits": 0, "seconds": 0.0, "listings": 0, "tokens": {}})
        if e.get("cached"):
            t["cache_hits"] += 1
            continue
        t["calls"] += 1
        t["seconds"] = round(t["seconds"] + (e.get("seconds") or 0), 1)
        t["listings"] += e.get("listings") or 0
        for k, v in (e.get("usage") or {}).items():
            t["tokens"][k] = t["tokens"].get(k, 0) + v
    return roles, events


def fmt_tok(t: dict) -> str:
    if not t:
        return "-"
    return f"{t.get('input_tokens', 0):,} in ({t.get('cached_input_tokens', 0):,} cached) / {t.get('output_tokens', 0):,} out"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--label", required=True)
    ap.add_argument("--gold-set", default="round-01")
    a = ap.parse_args()
    rnd = a.round
    lp = OUT / f"loop-r{rnd:02d}"
    rd = lambda p: json.loads(p.read_text()) if p.exists() else {}
    ev, ar, av, m = rd(OUT / "eval" / f"eval-{a.gold_set}.json"), rd(lp / "auto-rules.json"), rd(lp / "auto-validator.json"), rd(OUT / "metrics.json")
    roles, events = ledger_since(rnd)
    rdir = ROOT / "rounds" / "cars"
    rdir.mkdir(parents=True, exist_ok=True)
    with open(rdir / f"round-{rnd:02d}-decisions.csv", "w", newline="", encoding="utf-8") as f:   # ids + tree paths only
        w = csv.writer(f)
        w.writerow(["listing_id", "source", "step", "route", "settled_level", "settled_path", "agent_answer",
                    "agent_confidence", "agent_answer_reused", "reason_codes"])
        for p in read_jsonl(OUT / "placements.jsonl"):
            if not (p.get("agent") or p["route"]):
                continue
            ag = p.get("agent") or {}
            w.writerow([p["listing_id"], p["source"], p["step"], p["route"] or "", p["level"], " > ".join(p["path"]),
                        ag.get("answer", ""), ag.get("confidence", ""), ag.get("reused", ""), p["reason"].split(";agent:")[0]])
    rows = "\n".join(
        f"| {k} | {s['right']}/{s['n']} ({s['right_rate']:.0%}) | {s['right_ci95'][0]:.0%}–{s['right_ci95'][1]:.0%} | "
        f"{s['not_harmful']}/{s['n']} ({s['not_harmful_rate']:.0%}) | {s['not_harmful_ci95'][0]:.0%}–{s['not_harmful_ci95'][1]:.0%} | "
        + (f"{s['flags']['pipeline_really_wrong']}/{s['flags']['n']}" if s.get("flags") else "") + " |"
        for k, s in ev.get("systems", {}).items())
    gate_rows = "\n".join(
        f"| {e['step']} | {e.get('origin', '')} | {e.get('verdict', '')} | {e.get('dev_rows_touched', '')} | "
        f"{json.dumps(e.get('delta'))} | {json.dumps(e.get('sealed')) if e.get('sealed') else '-'} |"
        for e in ar.get("log", [])[1:] if e.get("step") not in ("proposer_done",))
    shares = m.get("settled_by_step", {})
    md = f"""# Cars round {rnd:02d}: {a.label}

Rules {ev.get('current_rules')} (`{ev.get('rules_sha256', '')[:12]}`): `identity.yaml` + `vocab.yaml` + `identity-learned.yaml`
(edits kept by the gate). Gold: `{a.gold_set}.yaml` ({ev.get('rows')} random listings, 10 per source;
provenance {json.dumps(ev.get('provenance'))}: Opus pre-labels checked by Diego, so not fully blind; every row compare
{json.dumps(ev.get('compare'))}), plus the owner's A/B review (review-r01, provenance review) and the imported round-0
reviews for the gate. Scored with the cars judge (`domains/cars/judge.py`: make, model, year, version incl. engine size
and gearbox), not taxo/score.py (it drops digit tokens). Intervals are 95% Wilson.

Owner decision this round: "CHRYSLER ATTITUDE SE CVT 2024" is a Dodge (gold row changed by Diego, noted in its `why`).

## 1. Headline: random gold (n = {ev.get('rows')})

| System | Right | 95% CI | Not harmful | 95% CI | Validator flags right |
|---|---:|---|---:|---|---|
{rows}

"Right" = the gold path holds (exact compare: a deeper answer fails). "Not harmful" = right, or correct but shallower /
version missing a word; never a wrong make, model, year or version. "Validator flags right" = of the listings where the
validator disagrees with rules+placer, how many gold says rules+placer got wrong.

## 2. Loop A, automatic (Codex proposer + gate)

Gate: rules only on dev gold ({ar.get('log', [{}])[0].get('n')} rows), kept only if it touches gold, holds no fewer rows, adds no harm and
holds more (or routes fewer); then one logged sealed read that must not fall. Sealed reads so far: {ar.get('sealed_reads_total')}.

| Change | From | Verdict | Dev rows touched | Delta (holds, harm, routed, version nodes) | Sealed |
|---|---|---|---:|---|---|
{gate_rows}

Kept: {json.dumps(ar.get('kept'))}. Dev after: {json.dumps({k: ar.get('final_dev', {}).get(k) for k in ('holds', 'n', 'harm')})}.

## 3. Validator improver (Codex)

{json.dumps({k: av.get(k) for k in ('from_version', 'candidate_version', 'lines', 'kept', 'verdict')}, ensure_ascii=False, indent=1) if av else 'not run'}

Current on dev gold: {json.dumps(av.get('current'))}
Candidate on dev gold: {json.dumps(av.get('candidate'))}

## 4. Where listings were settled now

{json.dumps(shares)}; still routed: {json.dumps(m.get('routed'))}. Placer this round: {json.dumps({k: m.get('agent', {}).get(k) for k in ('calls', 'sent', 'accepted', 'reused_unchanged', 'outcome')})}.

## 5. Cost this round (ledger, since the round started)

| Role | Codex calls | Cache hits | Seconds (sum of calls) | Listings | Tokens |
|---|---:|---:|---:|---:|---|
""" + "\n".join(f"| {r} | {t['calls']} | {t['cache_hits']} | {t['seconds']} | {t['listings']} | {fmt_tok(t['tokens'])} |"
                for r, t in sorted(roles.items())) + f"""

Ledger events this round: {json.dumps(events)}.

## 6. Reading

- The big gain came from the owner's round-1 decision ("as specific as possible"); validator flags fixed the make errors;
  the gate kept the two review-driven label fixes. The placer adds nothing on this sample: it confirms the rules.
- The validator labels these random listings better than the pipeline: it is the place to look for the next rules.
- Candidates left: Codex's "4WD is generic in trims" (untestable: no gold row touches it); the model-number guard
  (dropped on dev).
"""
    (rdir / f"round-{rnd:02d}.md").write_text(md, encoding="utf-8")
    rec = {"domain": "cars", "round": rnd, "kind": a.label, "branch": "cars-pipeline", "rules": ev.get("current_rules"),
           "rules_sha256": ev.get("rules_sha256"), "gold": {"set": a.gold_set, "n": ev.get("rows"), "provenance": ev.get("provenance")},
           "eval": {k: {x: s.get(x) for x in ("right", "n", "right_ci95", "not_harmful", "not_harmful_ci95", "flags")}
                    for k, s in ev.get("systems", {}).items()},
           "auto_rules": {"kept": ar.get("kept"), "log": [{x: e.get(x) for x in ("step", "origin", "verdict", "dev_rows_touched", "delta", "sealed")}
                                                          for e in ar.get("log", [])[1:]]},
           "validator": {k: av.get(k) for k in ("from_version", "candidate_version", "lines", "kept", "current", "candidate", "verdict")},
           "settled_by_step": {k: v["share"] for k, v in shares.items()}, "routed": m.get("routed"),
           "cost": roles, "sealed_reads": ar.get("sealed_reads_total"),
           "owner_decisions": ["CHRYSLER ATTITUDE is Dodge (gold row changed by Diego)"]}
    with open(ROOT / "memory" / "record.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote rounds/cars/round-{rnd:02d}.md, round-{rnd:02d}-decisions.csv and a memory/record.jsonl line")


if __name__ == "__main__":
    main()
