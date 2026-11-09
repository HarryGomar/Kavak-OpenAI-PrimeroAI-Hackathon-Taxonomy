"""Both loops, end to end, no one in between (SPEC §5): many cheap rule rounds on silver, then one human round that
checks the rules and improves the validator, then again.

    uv run python -m taxo.loop fragrance --cycles 3          per cycle: 3 rule rounds on silver, then 1 validator change

One cycle:
  1. rules     taxo.climb phase on the current silver set: hill-climb vocab edits and rule on/off, gated on silver
  2. check     checkpoint on dev human labels, the placer agent on (sealed is read ONCE, after the last cycle)
  3. human     Loop B round: fresh Pedia-labelled sample, the validator labels it blind, Pedia settles disagreements
  4. improve   the improver agent proposes ONE question change from the validator's misses and traces on human
               labels; A/B on a fresh sample; kept only if exact rises and harm does not (validator.yaml version + 1)
  5. silver    a fresh silver set labelled by the current validator, for the next cycle's rule phase
Pedia's label stands in for the person (the project's choice for testing). Every step writes a KPI row.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from taxo import climb, kpis, loopb, score, validator
from taxo.core.codex import Runner
from taxo.core.config import DOMAINS_DIR, ROOT, RUNS_DIR
from taxo.lattice.vocab import tokens
from taxo.roles.improver import make_improver

RULE_ROUNDS, VB_MISSES, VB_AB = 3, 60, 120   # per cycle: 3 rule rounds, then 1 validator change


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
            out.append({"title": blind[v["id"]]["title"], "validator": " > ".join(v["path"]), "trace": v.get("trace"),
                        "human": " > ".join(gp), "class": j.cls})
    return out


def propose_change(domain: str, misses: list[dict], log: Path) -> dict | None:
    """The improver agent (taxo/roles/improver.py) on the Codex runner: ONE SetupChange from the validator's mistakes
    and their traces. Returns the change as a dict, or None."""
    s = validator.card(domain)
    qs = [{k: q.get(k) for k in ("id", "ask", "tools", "then")} for q in s.get("questions") or []
          if q.get("status") in ("admitted", "shadow")]
    text = ("Current questions:\n" + json.dumps(qs, ensure_ascii=False, indent=0)
            + "\n\nTools: similar_brands, ask_person, brand_products" + (", web_search" if s.get("web") else "")
            + "\n\nA new tool: `code` is one Python function decorated with @function_tool (imported already, with "
              "RunContextWrapper and ValidateContext; ctx.context has .brands (all brand names) and .menus "
              "(brand -> its known product names)). `fires_on` and `quiet_on` are JSON objects of the function's "
              "arguments; code runs both and keeps the tool only if both run and give different results. Say in "
              "`ask` which question uses it."
            + "\n\nMistakes (listing, the validator's answer and trace, the person's answer):\n"
            + json.dumps(misses[:30], ensure_ascii=False, indent=0))
    try:
        r = Runner.run_sync(make_improver(domain), text, timeout=900)
    except Exception as e:
        log.write_text(f"improver failed: {e}", encoding="utf-8")
        return None
    change = r.final_output.model_dump()
    log.write_text(json.dumps(change, indent=1, ensure_ascii=False), encoding="utf-8")
    return change


def apply_change(s: dict, ch: dict, origin: str) -> dict | None:
    """A question change applied to a copy of the setup (next version); other kinds are not applied yet."""
    if not ch.get("question_id") or not ch.get("ask"):   # judged by content: the improver may mislabel the kind
        return None
    q = {"id": ch["question_id"], "ask": ch["ask"], "tools": ch.get("tools") or [], "then": ch.get("then"),
         "status": "admitted", "origin": origin}
    qs = [x for x in s.get("questions") or [] if x.get("id") != q["id"]]
    at = next((i + 1 for i, x in enumerate(qs) if x.get("id") == ch.get("after")), len(qs))
    return {**s, "version": int(s.get("version", 1)) + 1, "questions": qs[:at] + [q] + qs[at:]}


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
    ch = propose_change(domain, misses, d / f"{v}-improver.json")
    c = validator.card(domain)
    cand = apply_change(c, ch, f"improver {v}: {(ch or {}).get('rationale', '')[:200]}") if ch else None
    if cand is None:
        _say(f"  improver: no question change to test ({(ch or {}).get('kind')}: {(ch or {}).get('text')})")
        _row(domain, "B", cyc * 100 + 2, f"validator improver cycle {cyc}: nothing testable",
             {"version": v, "validator": "codex-agent", "reviewer": "pedia", "agreement": None, "change": ch})
        return {"round": v, "kept": False, "human": s, "change": ch}
    return ab_test(domain, cyc, v, ch, cand, c) | {"human": s}


def ab_test(domain: str, cyc: int, v: str, ch: dict, cand: dict, c: dict) -> dict:
    """The improver's change, A/B on a fresh dev human sample: current setup vs candidate, same listings."""
    d = RUNS_DIR / domain / "loopb"
    steps = [ch]
    ab = _next_v(domain)
    loopb.sample(domain, ab, pool="pedia-dev")
    items = [json.loads(x) for x in open(d / f"{ab}-blind.jsonl", encoding="utf-8")]
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(2) as pool:   # current and candidate label the same listings at the same time
        fa = pool.submit(validator.label, domain, items, d / f"{ab}-validator.log")
        fb = pool.submit(validator.label, domain, items, d / f"{ab}-validator-cand.log", False, 600, cand)
        cur, new = fa.result(), fb.result()
    (d / f"{ab}-validator.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in cur), "utf-8")
    (d / f"{ab}-validator-cand.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in new), "utf-8")
    a, b = loopb.validator_vs_pedia(domain, ab), loopb.validator_vs_pedia(domain, ab, "-cand")
    abst = {k: sum(x.get("decision") in ("abstain", "reject") for x in L) / max(len(L), 1) for k, L in (("a", cur), ("b", new))}
    a["abstain_rate"], b["abstain_rate"] = round(abst["a"], 3), round(abst["b"], 3)
    keep = b["exact"] > a["exact"] and b["harm_rate"] <= a["harm_rate"] and abst["b"] <= abst["a"] + 0.05
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
    _say(f"cycle {cyc}: 3-4. one validator change: human round, improver, A/B on fresh dev human rows")
    from taxo import improve   # one iteration per cycle: 3 rule rounds, then 1 validator change
    out["validator"] = improve.iteration(domain, cyc, VB_MISSES, VB_AB)
    if (out["validator"] or {}).get("kept"):
        nxt = _next_s(domain)
        _say(f"cycle {cyc}: 5. the validator changed: fresh silver set {nxt} with it")
        climb.label(domain, nxt, seed=100 + cyc)
    else:   # same validator: its silver is still valid; relabelling would only cost calls
        nxt = silver
        _say(f"cycle {cyc}: 5. the validator is unchanged: the next cycle reuses silver {nxt}")
    out["next_silver"] = nxt
    (RUNS_DIR / domain / f"cycle{cyc}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    (RUNS_DIR / domain / f"cycle{cyc}-report.md").write_text(report(domain, cyc), encoding="utf-8")
    return out


def report(domain: str, cyc: int) -> str:
    """The cycle's report, built only from what the run wrote (no estimates)."""
    R = RUNS_DIR / domain
    c = json.loads((R / f"cycle{cyc}.json").read_text(encoding="utf-8"))
    L = [f"# Cycle {cyc} (silver {c['silver']})", ""]
    rounds = json.loads((R / "silver" / f"phase{cyc}-rounds.json").read_text(encoding="utf-8"))         if (R / "silver" / f"phase{cyc}-rounds.json").exists() else []
    kept = c.get("rules") or []
    start = next((ln for ln in (R / "silver" / f"phase{cyc}-start.txt").read_text(encoding="utf-8").splitlines()), "")         if (R / "silver" / f"phase{cyc}-start.txt").exists() else ""
    L += ["## Rule phase (gated on silver)", f"- start: {start}",
          f"- end: silver exact {kept[-1]['silver_exact']} harm {kept[-1]['silver_harm']}" if kept else "- end: unchanged",
          f"- proposer calls: {sum(1 for r in rounds if r.get('proposal') is not None)} of {len(rounds)} rounds"]
    for r in rounds:
        p = r.get("proposal") or {}
        g = r.get("proposal_gate")
        fate = ("kept" if r.get("proposed_by") == "proposer-agent" else
                f"dropped by the gate {g}" if g and not g.get("passed") else
                "passed but a code-search change won" if g else "not testable this round (recorded)")
        L.append(f"  - round {r['round']}: {p.get('kind')} `{p.get('id')}`: {p.get('description', '')[:160]} -> {fate}")
    for k in kept:
        L.append(f"  - KEPT round {k['round']} [{k['proposed_by']}]: {k['change']} (better {k['better']}, worse "
                 f"{k['worse']}, exact {k['exact'][0]} -> {k['exact'][1]})")
    v = c.get("validator") or {}
    L += ["", "## Validator (human round, improver, A/B)"]
    if "ab" in v or "outcome" in v:   # a taxo.improve iteration
        ch = v.get("change") or {}
        L += [f"- human round {v.get('human_round')}: {v.get('misses')} misses of {v.get('of')} (validator "
              f"v{v.get('card_before')}); improver: {ch.get('kind')} `{ch.get('question_id') or ch.get('tool_name')}`: "
              f"{ch.get('text')}"]
        if v.get("tool_test"):
            L.append(f"- tool test: {v['tool_test']}")
        if "ab" in v:
            for m in ("exact", "harm", "abstain"):
                x = v["ab"][m]
                L.append(f"- {m}: {x['current']} {x['current_ci']} -> {x['candidate']} {x['candidate_ci']}, "
                         f"delta {x['delta']} {x['delta_ci']} (n={v['ab']['n']}, {x['changed']} changed)")
            L.append(f"- {'KEPT: validator v' + str(v['card_before']) + ' -> v' + str(v['card_after']) + ' ' + str(v.get('commit', '')) if v['kept'] else 'dropped: validator stays v' + str(v['card_before'])}")
        else:
            L.append(f"- {v.get('outcome')}")
        v = {}
    h = v.get("human") or {}
    if v.get("current"):
        L += [f"- improver change: {(v.get('steps') or [{}])[0].get('kind')} "
              f"`{(v.get('steps') or [{}])[0].get('question_id')}`: {(v.get('steps') or [{}])[0].get('text')}",
              f"- A/B on dev human rows ({v['round']}): current exact {v['current']['exact_rate']} harm "
              f"{v['current']['harm_rate']} abstain {v['current'].get('abstain_rate')} -> candidate "
              f"{v['candidate']['exact_rate']} / {v['candidate']['harm_rate']} / {v['candidate'].get('abstain_rate')}",
              f"- validator card: {v.get('card')} ({'KEPT' if v.get('kept') else 'dropped'})"]
    elif v:
        L.append(f"- improver: nothing testable ({(v.get('change') or {}).get('kind')}: {(v.get('change') or {}).get('text')})")
    ck = c.get("checkpoint") or {}
    pl = ck.get("placer") or {}
    L += ["", "## Dev checkpoint (human labels; sealed not read)",
          f"- dev exact {ck.get('dev')} harm {ck.get('dev_harm')}; human dev exact {ck.get('human_dev')}; "
          f"to agent {ck.get('to_agent')}",
          f"- placer: {pl.get('calls')} calls, {pl.get('placed')} placed, {pl.get('abstained')} abstained, "
          f"{pl.get('refused')} refused, {pl.get('failed')} failed, {pl.get('tool_calls')} tool calls, {pl.get('secs')} s"]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.loop")
    ap.add_argument("domain")
    ap.add_argument("--cycles", type=int, default=2)
    ap.add_argument("--rule-rounds", type=int, default=RULE_ROUNDS)
    ap.add_argument("--start", type=int, default=1, help="number of the first cycle")
    ap.add_argument("--silver", default="S1", help="silver set for the first cycle's rule phase")
    ap.add_argument("--skip-first-rules", action="store_true", help="the first cycle's rule phase already ran")
    ap.add_argument("--final-sealed", action="store_true", help="after the last cycle, read sealed gold once")
    a = ap.parse_args()
    silver = a.silver
    for k in range(a.start, a.start + a.cycles):
        res = cycle(a.domain, k, silver, a.rule_rounds, skip_rules=a.skip_first_rules and k == a.start)
        silver = res["next_silver"]
    if a.final_sealed:
        _say("final: one sealed read")
        fin = climb.pipeline_run(a.domain, 999, f"final after cycle {a.start + a.cycles - 1}: one sealed read", sealed=True)
        _say(f"  final: {fin}")
        (RUNS_DIR / a.domain / "loop-final.json").write_text(json.dumps(fin, indent=1), encoding="utf-8")
    print(kpis.table(kpis.history(a.domain)[-16:]))


if __name__ == "__main__":
    main()
