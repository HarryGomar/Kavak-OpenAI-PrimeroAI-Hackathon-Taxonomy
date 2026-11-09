"""Loop A on silver: hill-climb rules against the validator's labels, because human labels are expensive.

    uv run python -m taxo.climb label fragrance S1                 the validator labels a silver set (Codex, ~5 calls)
    uv run python -m taxo.climb phase fragrance S1 --phase 1 --rounds 6    many cheap rule rounds, gated on silver
    uv run python -m taxo.climb checkpoint fragrance --phase 1      the human step: Pedia dev gold + one sealed read

A phase runs many rule rounds against one frozen silver set (no human, no gold). Each round builds candidates from the
pipeline's disagreements with silver (vocab edits, rule on/off), runs every candidate, keeps the best one that passes the
silver gate, and logs a KPI row. Kept changes are written to vocab.yaml and the rule files at the end of the phase. Then
one checkpoint against human labels (Pedia stands in for the person) says whether the silver-trained rules really
improved; Loop B (taxo.loopb + taxo.validator) improves the validator between phases.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import yaml

from taxo import evaluator, gold as goldmod, kpis, validator
from taxo.core.config import DOMAINS_DIR, ROOT, RUNS_DIR
from taxo.gate import RANK, wilson_lower
from taxo.lattice import vocab as vocabmod
from taxo.parse import Brands
from taxo.tools.checks import CHECKS
from taxo.pipeline import Item, brand_spread, load_gold, load_items, run, score_rows, shares, vocab_candidates

N_SILVER, BATCH, MIN_TOUCHED, BAR = 200, 200, 5, 0.5   # BATCH: listings handed to the validator at once
AGENT_CALLS = 40   # placer calls per checkpoint run
WORKERS = max(1, min(24, (os.cpu_count() or 2) - 2))   # candidates of a round run in parallel
TOGGLE = ("veto/", "child/", "settle/single-name")    # rules whose on/off changes a placement


def _sdir(domain: str) -> Path:
    d = RUNS_DIR / domain / "silver"
    d.mkdir(parents=True, exist_ok=True)
    return d


def label(domain: str, name: str, n: int = N_SILVER, seed: int = 3) -> Path:
    """Sample n dev listings the pipeline gave a brand (none used by a Loop B round) and have the validator label them."""
    P = [json.loads(x) for x in open(RUNS_DIR / domain / "placements.jsonl", encoding="utf-8")]
    used = {json.loads(x)["id"] for f in (RUNS_DIR / domain / "loopb").glob("V*-blind.jsonl")
            for x in open(f, encoding="utf-8")}
    menu: dict[str, Counter] = {}
    for p in P:
        if p["level"] == "product":
            menu.setdefault(p["brand"], Counter())[" > ".join(p["path"])] += 1
    pool = [p for p in P if p["brand"] and p["title"] and p["id"] not in used and p["pedia_brand"]
            and not goldmod.is_sealed(p["pedia_brand"])]
    pick = random.Random(seed).sample(pool, min(n, len(pool)))
    blind = [{"id": p["id"], "title": p["title"], "source": p["source"], "url": p.get("url"), "brand": p["path"][0],
              "slug": p["brand"], "menu": [m for m, _ in (menu.get(p["brand"]) or Counter()).most_common(40)]}
             for p in pick]
    d = _sdir(domain)
    (d / f"{name}-blind.jsonl").write_text("".join(json.dumps(b, ensure_ascii=False) + "\n" for b in blind), "utf-8")
    labels = []
    for i in range(0, len(blind), BATCH):
        labels += validator.label(domain, blind[i:i + BATCH], d / f"{name}-batch{i // BATCH}.log")
    slug = {b["id"]: b["slug"] for b in blind}
    out = d / f"{name}.jsonl"
    out.write_text("".join(json.dumps(x | {"slug": slug[x["id"]]}, ensure_ascii=False) + "\n" for x in labels), "utf-8")
    print(f"{len(labels)} of {len(blind)} labelled -> {out}")
    return out


def silver_rows(domain: str, name: str) -> list[goldmod.GoldRow]:
    return [goldmod.GoldRow(id=f"silver:{x['id']}", title="", brand=x["slug"], expected_path=x["path"],
                            origin=f"silver/{name}", extra={"listing": x["id"], "validator": x["validator"]})
            for x in map(json.loads, open(_sdir(domain) / f"{name}.jsonl", encoding="utf-8"))]


def _attach(items: list[Item], rows: list[goldmod.GoldRow]) -> dict[str, Item]:
    by_id = {it.id: it for it in items}
    by_gold = {}
    for g in rows:
        it = by_id[g.extra["listing"]]
        if g.id not in it.gold:
            it.gold.append(g.id)
        by_gold[g.id] = it
    return by_gold


def _judge(rows, by_gold, brands):
    """(per silver row: (class against the validator's label, path), summary, judged triples)."""
    rep, judged = score_rows(rows, by_gold, brands)
    return {g.id: (j.cls, tuple(it.path)) for g, it, j in judged}, rep.summary(), judged


def _gate(before: dict, after: dict) -> tuple[bool, dict]:
    better = sum(RANK[after[k][0]] > RANK[before[k][0]] for k in before)
    worse = sum(RANK[after[k][0]] < RANK[before[k][0]] for k in before)
    touched = sum(after[k][1] != before[k][1] for k in before)
    exact_b = sum(v[0] == "exact" for v in before.values())
    exact_a = sum(v[0] == "exact" for v in after.values())
    lb = wilson_lower(better, better + worse)
    ok = exact_a >= exact_b and touched >= MIN_TOUCHED and lb >= BAR and better > worse
    return ok, {"better": better, "worse": worse, "touched": touched, "exact": [exact_b, exact_a], "wilson": round(lb, 2)}


def _vocab_of(doc: dict, tmp: Path):
    tmp.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return vocabmod.load(tmp)


def _toggled(rules: list[evaluator.Rule], rid: str) -> list[evaluator.Rule]:
    return [evaluator.Rule(**{**r.__dict__, "status": "shadow" if r.status == "active" else "active"}) if r.id == rid
            else r for r in rules]


_W: dict = {}


def _worker_init(domain: str, name: str) -> None:
    """Each worker loads the data once: listings, gold, silver rows, the base rules."""
    rows, human, names = load_gold("drive")
    _W["brands"] = Brands(names)
    _W["items"] = load_items("drive", rows, human)
    _W["srows"] = silver_rows(domain, name)
    _W["by_gold"] = _attach(_W["items"], _W["srows"])
    _W["only"] = {g.brand for g in _W["srows"]}
    _W["rules"] = evaluator.load(ROOT / "rules" / domain, ROOT / "rules" / "global")
    _W["tmp"] = _sdir(domain) / f"vocab-try-{os.getpid()}.yaml"


def _worker_eval(arg: tuple[dict, list[dict]]) -> dict:
    """One candidate (vocab doc, its whole rule list as dicts) -> per silver row (class, path)."""
    doc, rule_dicts = arg
    rules = [evaluator.Rule(**d) for d in rule_dicts]
    run(_W["items"], _W["brands"], _vocab_of(doc, _W["tmp"]), rules, only=_W["only"])
    return _judge(_W["srows"], _W["by_gold"], _W["brands"])[0]


# ---------------------------------------------------------------- the proposer agent as the main source of changes
PAYLOAD_HELP = """payload_json formats that code can apply and test this round:
- vocab: {"op": "add" or "remove", "axis": "strip" | "concentration" | "audience" | "form" | "edition" | "pack",
          "tokens": ["word or phrase", ...]}
- code_rule: {"params": {}} with `check` set to one of the known checks and `decision` veto or abstain
- convention_question: {} (the description is the question for a person)
Other kinds (agentic_rule, registry, route, new_check) are recorded as proposals for later rounds."""


def clusters(sets: dict[str, list], limit: int = 6, examples: int = 4) -> list[dict]:
    """Disagreements grouped by shape: (against which reference, class, the step that decided), biggest first."""
    groups: dict[tuple, list] = {}
    for ref, judged in sets.items():
        for g, it, j in judged:
            if j.cls == "exact":
                continue
            groups.setdefault((ref, j.cls, it.reason or it.step or "none"), []).append((g, it, j))
    out = []
    for (ref, cls, why), rows in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:limit]:
        words = Counter(w for _, _, j in rows for w in (j.extra if cls in ("deeper", "wrong") else j.missing))
        out.append({"against": ref, "shape": f"{cls} / {why}", "n": len(rows), "words": words.most_common(6),
                    "examples": [{"title": it.title[:110], "pipeline": " > ".join(it.path) or "-",
                                  "reference": " > ".join(g.expected_path)} for g, it, _ in rows[:examples]]})
    return out


def ask_proposer(domain: str, cl: list[dict], doc: dict, log: Path, history: list[dict] | None = None) -> dict | None:
    from taxo.core.codex import Runner
    from taxo.roles.proposer import make_proposer
    closed_f = DOMAINS_DIR / domain / "memory" / "closed_questions.yaml"
    closed = yaml.safe_load(closed_f.read_text(encoding="utf-8")) if closed_f.exists() else []
    text = (PAYLOAD_HELP + "\n\nCurrent vocabulary (variant axes and strip words):\n"
            + json.dumps({"variant": doc.get("variant"), "strip": doc.get("strip")}, ensure_ascii=False)
            + ("\n\nClosed questions: decided already. Never propose them again, nor a vocab or rule change that only "
               "restates them:\n" + json.dumps(closed, ensure_ascii=False) if closed else "")
            + ("\n\nYour earlier proposals this phase and what happened to them. Do not repeat one. A kind that is "
               "not testable this round changes nothing now, so prefer a vocab edit or a code_rule:\n"
               + json.dumps(history, ensure_ascii=False) if history else "")
            + "\n\nDisagreement clusters (pipeline vs the frozen validator's silver, and vs dev human labels):\n"
            + json.dumps(cl, ensure_ascii=False, indent=0))
    try:
        r = Runner.run_sync(make_proposer(domain), text, timeout=900)
    except Exception as e:
        log.write_text(json.dumps({"error": str(e)[:500]}), encoding="utf-8")
        return None
    p = r.final_output.model_dump(mode="json")
    log.write_text(json.dumps({"proposal": p, "clusters": cl}, indent=1, ensure_ascii=False), encoding="utf-8")
    return p


def proposal_candidate(domain: str, p: dict, doc: dict, rules: list[evaluator.Rule]):
    """(label, doc, rules) that code can test, or None (the proposal is recorded only)."""
    try:
        payload = json.loads(p.get("payload_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    kind, pid = p.get("kind"), re.sub(r"[^a-z0-9_]+", "_", (p.get("id") or "proposal").lower())
    if kind == "vocab" and payload.get("tokens"):
        d = yaml.safe_load(yaml.safe_dump(doc))
        axis = payload.get("axis") or "strip"
        lst = d.setdefault("strip", []) if axis == "strip" else d.setdefault("variant", {}).setdefault(axis, [])
        toks = [t for t in payload["tokens"] if isinstance(t, str) and t.strip()]
        if payload.get("op") == "remove":
            lst[:] = [x for x in lst if x not in toks]
        else:
            lst.extend(t for t in toks if t not in lst)
        return f"proposer vocab {axis} {payload.get('op', 'add')} {toks}", d, rules
    if kind == "code_rule" and p.get("check") in CHECKS:
        rule = evaluator.Rule(id=f"proposed/{pid}", stage="place", status="active", why=p.get("description", ""),
                              when=[{"fact": "placement.step", "eq": "lattice"},
                                    {"check": p["check"], "params": payload.get("params") or {}}],
                              then={"veto": True, "route": "agent_title"})
        return f"proposer code_rule {p['check']} ({p.get('decision')})", doc, rules + [rule]
    if kind == "convention_question":
        q = RUNS_DIR / domain / "questions.jsonl"
        with open(q, "a", encoding="utf-8") as f:
            f.write(json.dumps({"from": "proposer", "question_id": pid, "question": p.get("description")}) + "\n")
    return None


def phase(domain: str, name: str, ph: int, rounds: int) -> list[dict]:
    rows, human, names = load_gold("drive")
    brands = Brands(names)
    items = load_items("drive", rows, human)
    srows = silver_rows(domain, name)
    by_gold = _attach(items, srows)
    only = {g.brand for g in srows}
    vocab_path = DOMAINS_DIR / domain / "vocab.yaml"
    rule_dirs = [ROOT / "rules" / domain, ROOT / "rules" / "global"]
    doc = yaml.safe_load(vocab_path.read_text(encoding="utf-8"))
    rules = evaluator.load(*rule_dirs)
    tmp = _sdir(domain) / "vocab-try.yaml"
    run(items, brands, _vocab_of(doc, tmp), rules, only=only)
    cur, summ, judged = _judge(srows, by_gold, brands)
    spread = brand_spread(items)
    kept = []
    msg = f"phase {ph} start: silver exact {summ['exact_rate']} harm {summ['harm_rate']} ({len(srows)} rows)"
    print(msg, flush=True)
    (_sdir(domain) / f"phase{ph}-start.txt").write_text(msg, encoding="utf-8")
    gold_by = {gid: it for it in items for gid in it.gold}
    dev_rows = [g for g in rows if g.brand in only and not goldmod.is_sealed(g.brand) and g.id in gold_by]
    record = []
    for rnd in range(1, rounds + 1):
        # 1. the proposer agent reads the disagreement clusters and proposes ONE change
        _, dev_judged = score_rows(dev_rows, gold_by, brands)
        cl = clusters({"silver (validator)": judged, "dev gold (human)": dev_judged})
        hist = [{"kind": (r.get("proposal") or {}).get("kind"), "id": (r.get("proposal") or {}).get("id"),
                 "what": (r.get("proposal") or {}).get("description", "")[:200],
                 "outcome": ("kept" if r.get("proposed_by") == "proposer-agent" else
                             "dropped by the silver gate" if r.get("proposal_gate") else "not testable (recorded only)")}
                for r in record]
        prop = ask_proposer(domain, cl, doc, _sdir(domain) / f"phase{ph}-round{rnd}-proposer.json", hist)
        pc = proposal_candidate(domain, prop, doc, rules) if prop else None
        cands = [(pc[0], pc[1], pc[2], "proposer-agent")] if pc else []
        # 2. code search adds its own candidates
        cands += [(lbl, d, rules, "code-search") for lbl, d in vocab_candidates(judged, doc, _vocab_of(doc, tmp), spread)]
        cands += [(f"rule {r.id}: {r.status} -> {'shadow' if r.status == 'active' else 'active'}", doc,
                   _toggled(rules, r.id), "code-search")
                  for r in rules if r.id.startswith(TOGGLE) and r.status in ("active", "shadow")]
        # 3. shadow every candidate on silver (in parallel); the gate decides; a passing proposer change wins
        with ProcessPoolExecutor(max_workers=min(len(cands), WORKERS), initializer=_worker_init,
                                 initargs=(domain, name)) as pool:
            outs = list(pool.map(_worker_eval, [(d, [r.__dict__ for r in rs]) for _, d, rs, _ in cands]))
        best, prop_info = None, None
        for (lbl, d, rs, src), after in zip(cands, outs):
            ok, info = _gate(cur, after)
            if src == "proposer-agent":
                prop_info = {**info, "passed": ok}
            score_ = (src == "proposer-agent", info["better"] - info["worse"])
            if ok and (best is None or score_ > best[5]):
                best = (lbl, d, rs, info, after, score_, src)
        rec = {"round": rnd, "proposal": prop, "proposal_tested": bool(pc), "proposal_gate": prop_info,
               "candidates": len(cands)}
        print(f"  round {rnd}: proposer -> {(prop or {}).get('kind')}: {(prop or {}).get('description', '')[:100]} | "
              f"{'tested ' + str(prop_info) if pc else 'not testable this round (recorded)'}", flush=True)
        if best is None:
            record.append(rec | {"kept": None})
            empty = len(record) >= 2 and all(r.get("kept") is None for r in record[-2:])
            print(f"  round {rnd}: none of {len(cands)} candidates passes the silver gate"
                  + ("; two empty rounds in a row, phase ends" if empty else "; next round"), flush=True)
            if empty:
                break
            continue
        lbl, doc, rules, info, cur, _, src = best
        run(items, brands, _vocab_of(doc, tmp), rules, only=only)
        _, summ, judged = _judge(srows, by_gold, brands)
        kept.append({"round": rnd, "change": lbl, "proposed_by": src, **info, "silver_exact": summ["exact_rate"],
                     "silver_harm": summ["harm_rate"], "candidates": len(cands)})
        record.append(rec | {"kept": lbl, "proposed_by": src})
        print(f"  round {rnd}: KEPT [{src}] {lbl} | {info} | silver exact {summ['exact_rate']} harm {summ['harm_rate']}",
              flush=True)
        kpis.append(domain, kpis.row(domain, {"shares_subset": shares(items), "data": "drive"}, "A", ph * 100 + rnd,
                                     f"silver climb p{ph} r{rnd} [{src}]: {lbl}", vocab_path, rule_dirs,
                                     silver={"set": name, "validator": srows[0].extra["validator"],
                                             "agreement": summ["exact_rate"], "harm": summ["harm_rate"], **info}))
    (_sdir(domain) / f"phase{ph}-rounds.json").write_text(json.dumps(record, indent=1, ensure_ascii=False), "utf-8")
    if kept:   # write the kept changes back: vocab and rule statuses
        vocab_path.write_text("# Fragrance vocabulary. Written by taxo.climb; the silver-climb edits are logged in "
                              "runs/fragrance/silver/phase*.json.\n"
                              + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")
        for r in rules:
            if not r.path:   # a rule the proposer wrote and the gate kept: its own file
                f = ROOT / "rules" / domain / f"{r.id.replace('/', '-')}.yaml"
                f.write_text(yaml.safe_dump({"id": r.id, "stage": r.stage, "when": r.when, "then": r.then,
                                             "status": r.status, "why": r.why,
                                             "origin": f"proposer agent, silver climb phase {ph}"},
                                            sort_keys=False, allow_unicode=True), encoding="utf-8")
                continue
            if r.path and r.id.startswith(TOGGLE):
                t = Path(r.path).read_text(encoding="utf-8")
                t2 = re.sub(r"^status: \w+$", f"status: {r.status}", t, count=1, flags=re.M)
                if t2 != t:
                    Path(r.path).write_text(t2, encoding="utf-8")
    (_sdir(domain) / f"phase{ph}.json").write_text(json.dumps(kept, indent=1, ensure_ascii=False), encoding="utf-8")
    return kept


def checkpoint(domain: str, ph: int) -> dict:
    """The human step after a rule phase: score on human labels (Pedia stands in): dev, plus one logged sealed read."""
    return pipeline_run(domain, ph * 100 + 99, f"human checkpoint after silver phase {ph} (dev; placer on)")


def pipeline_run(domain: str, rnd: int, label: str, sealed: bool = False, agent_calls: int = AGENT_CALLS) -> dict:
    """A full pipeline run with the placer agent on `agent_calls` routed listings; sealed only when asked (once, at
    the end of a loop)."""
    subprocess.run([sys.executable, "-m", "taxo.pipeline", domain, "--data", "drive", "--no-experiments",
                    "--agent-calls", str(agent_calls), "--loop", "A", "--round", str(rnd), "--label", label]
                   + (["--sealed"] if sealed else []), check=True)
    m = json.loads((RUNS_DIR / domain / "metrics.json").read_text(encoding="utf-8"))
    out = {"dev": m["dev"]["exact_rate"], "dev_harm": m["dev"]["harm_rate"], "human_dev": m["human_dev"]["exact_rate"],
           "to_agent": m["shares_subset"]["to_agent"][1], "placer": m.get("placer")}
    if sealed:
        out |= {"sealed": m["sealed"]["exact_rate"], "sealed_harm": m["sealed"]["harm_rate"],
                "sealed_reads": m.get("sealed_reads_logged")}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.climb")
    ap.add_argument("cmd", choices=["label", "phase", "checkpoint"])
    ap.add_argument("domain")
    ap.add_argument("name", nargs="?", default="S1")
    ap.add_argument("--phase", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--n", type=int, default=N_SILVER)
    a = ap.parse_args()
    if a.cmd == "label":
        label(a.domain, a.name, a.n)
    elif a.cmd == "phase":
        phase(a.domain, a.name, a.phase, a.rounds)
    else:
        print(json.dumps(checkpoint(a.domain, a.phase), indent=1))


if __name__ == "__main__":
    main()
