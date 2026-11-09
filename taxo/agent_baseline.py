"""The agent-only baseline (SPEC §1, §13; slide 4): an agent places every listing by itself, with no rules. On one random
sample of DEV gold rows we score three solvers side by side, against the same gold:

  agent only     the agent's path for every listing (title, shop, url and brand field; no pipeline answer, no menu)
  rules only     the pipeline's free steps; what they route to the agent stays on the brand
  rules + agent  the pipeline, with the agent's answer for the listings the pipeline routes to the agent

and measure what the agent costs: tokens and seconds per listing (codex exec, batches of BATCH).

    uv run python -m taxo.agent_baseline fragrance --n 200 --seed 11
    uv run python -m taxo.agent_baseline fragrance --split sealed --n 400 --seed 11     # one logged sealed read

On dev the rules were tuned on the same brands, so the rules columns there are optimistic; the sealed split is the
fair comparison (the agent sees no gold either way).

Answers are cached per listing in runs/<d>/agent_baseline/answers.jsonl, so a rerun only asks for new listings.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import yaml

from taxo import evaluator, score
from taxo.core.config import DOMAINS_DIR, RUNS_DIR
from taxo.lattice.vocab import tokens
from taxo.propose import Bench

BATCH = 40
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["labels"],
          "properties": {"labels": {"type": "array", "items": {
              "type": "object", "additionalProperties": False, "required": ["id", "brand", "path", "why"],
              "properties": {"id": {"type": "string"}, "brand": {"type": "string"},
                             "path": {"type": "array", "items": {"type": "string"}}, "why": {"type": "string"}}}}}}


def card(domain: str) -> str:
    conv = (yaml.safe_load((DOMAINS_DIR / domain / "pack.yaml").read_text(encoding="utf-8")) or {}).get("conventions", "")
    return (f"You place {domain} marketplace listings on a product tree: brand > family or line (only if the brand "
            "groups products that way) > product > variant (only when the title names one, such as a flavour). For "
            "each listing answer the brand (the maker, never the shop) and the path below the brand, as deep as the "
            "title supports and no deeper. A correct shallower path is better than a wrong deeper one. Use the brand's "
            "own product names, without size, pack count or other buying choices. Give an empty path when the title "
            "names no product. Give a short 'why'.\n\nConventions:\n" + conv.strip()
            + "\n\nAnswer every listing below, in order, with its id. Do not run commands or read files; use only this "
              "text.\n\n")


def ask(domain: str, items: list[dict], log: Path) -> tuple[list[dict], dict]:
    exe = shutil.which("codex") or "codex"
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        cmd = [exe, "exec", "--ignore-user-config", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
               "--color", "never", "-C", tmp, "--output-schema", str(t / "schema.json"), "-o", str(t / "out.json"), "-"]
        p = subprocess.run(cmd, input=card(domain) + json.dumps(items, ensure_ascii=False, indent=0),
                           capture_output=True, text=True, encoding="utf-8", timeout=1800)
        raw = (t / "out.json").read_text(encoding="utf-8") if (t / "out.json").exists() else ""
    lines = p.stderr.splitlines()
    used = next((lines[i + 1].replace(",", "").strip() for i, ln in enumerate(lines)
                 if ln.strip() == "tokens used" and i + 1 < len(lines)), "")
    model = next((ln.split(":", 1)[1].strip() for ln in lines if ln.startswith("model:")), "default")
    log.write_text(f"exit {p.returncode}\n--- stderr\n{p.stderr[-3000:]}\n--- answer\n{raw}", encoding="utf-8")
    meta = {"tokens": int(used) if used.isdigit() else None, "secs": round(time.time() - t0, 1), "n": len(items),
            "model": model}
    try:
        labels = json.loads(raw)["labels"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise SystemExit(f"agent answer refused ({e}); see {log}")
    asked = {it["id"] for it in items}
    return [x for x in labels if x.get("id") in asked and isinstance(x.get("path"), list)], meta


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.agent_baseline")
    ap.add_argument("domain", choices=["fragrance", "food"])
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--split", choices=["dev", "sealed"], default="dev")
    a = ap.parse_args()
    b = Bench(a.domain)
    out = RUNS_DIR / a.domain / "agent_baseline"
    out.mkdir(parents=True, exist_ok=True)
    doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8"))
    ev = b.evaluate(doc, evaluator.load(*b.rule_dirs))        # the pipeline as it stands: placements and routes
    rows = b.dev if a.split == "dev" else b.gold.sealed(f"taxo.agent_baseline: agent alone vs rules on {a.n} sealed rows")
    pool = [g for g in rows if b.by_gold[g.id].title and not b.by_gold[g.id].id.startswith("gold:")]
    sample = random.Random(a.seed).sample(pool, min(a.n, len(pool)))
    cache_p = out / "answers.jsonl"
    cache = {json.loads(x)["id"]: json.loads(x) for x in open(cache_p, encoding="utf-8")} if cache_p.exists() else {}
    calls = [json.loads(x) for x in open(out / "calls.jsonl", encoding="utf-8")] if (out / "calls.jsonl").exists() else []
    todo = [b.by_gold[g.id] for g in sample if b.by_gold[g.id].id not in cache]
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        items = [{"id": it.id, "title": it.title, "shop": it.source, "url": it.url, "brand_field": it.brand_field}
                 for it in chunk]
        labels, meta = ask(a.domain, items, out / f"call-{len(calls):03d}.log")
        calls.append(meta)
        with open(out / "calls.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(meta) + "\n")
        with open(cache_p, "a", encoding="utf-8") as f:
            for x in labels:
                cache[x["id"]] = x
                f.write(json.dumps(x, ensure_ascii=False) + "\n")
        print(f"call {len(calls)}: {len(labels)}/{len(chunk)} answered, {meta['tokens']} tokens, {meta['secs']}s",
              flush=True)
    brands = b.score_brands
    reps = {k: score.Report() for k in ("agent_only", "rules_only", "rules_plus_agent")}
    routed, unanswered = 0, 0
    for g in sample:
        it = b.by_gold[g.id]
        bt = {t for r in brands.runs(g.brand) for t in r}
        ans = cache.get(it.id)
        if ans is None:
            unanswered += 1
            agent = (None, [])
        else:
            slug = brands.exact(ans["brand"]) or brands.lead(tokens(ans["brand"])) or f"unknown:{ans['brand']}"
            at, gt = tokens(ans["brand"]), tokens(brands.names[g.brand])
            if slug != g.brand and at and (gt[:len(at)] == at or at[:len(gt)] == gt):
                slug = g.brand          # lenient, in the agent's favour: "Pure Sugar" names "Pure Sugar Candy"
            name = brands.names.get(slug, ans["brand"])
            agent = (slug, [name] + [s for s in ans["path"] if s.strip()])
        rules = (ev["placed"][g.id]["brand"], ev["placed"][g.id]["path"])     # items still hold this run's routes
        to_agent = it.route is not None and it.step != "agent"
        routed += to_agent
        hybrid = agent if to_agent else rules
        for k, (pb, pp) in (("agent_only", agent), ("rules_only", rules), ("rules_plus_agent", hybrid)):
            reps[k].add(score.judge(pb, pp, g.brand, g.expected_path, bt))
    tok = [c["tokens"] for c in calls if c.get("tokens")]
    per_tok = sum(tok) / sum(c["n"] for c in calls if c.get("tokens")) if tok else None
    per_sec = sum(c["secs"] for c in calls) / sum(c["n"] for c in calls) if calls else None
    share = ev["to_agent"]
    res = {"domain": a.domain, "split": a.split, "n": len(sample), "seed": a.seed, "unanswered": unanswered,
           "sample_routed_to_agent": round(routed / len(sample), 3), "agent_share_all_listings": share,
           "model": calls[-1]["model"] if calls else None,
           "brand_match": "exact or lead alias, or one name the start of the other (lenient to the agent)", "calls": len(calls),
           "tokens_per_listing": round(per_tok) if per_tok else None,
           "secs_per_listing_sequential": round(per_sec, 2) if per_sec else None,
           "tokens_per_1k_listings": {"agent_only": round(per_tok * 1000) if per_tok else None,
                                      "rules_plus_agent": round(per_tok * 1000 * share) if per_tok else None},
           "scores": {k: {m: r.summary()[m] for m in ("accept_rows", "exact", "shallower", "deeper", "wrong",
                                                       "wrong_brand", "no_brand", "exact_rate", "right_or_shallower",
                                                       "harm_rate")} for k, r in reps.items()}}
    name = f"baseline-n{a.n}-s{a.seed}.json" if a.split == "dev" else f"baseline-sealed-n{a.n}-s{a.seed}.json"
    (out / name).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))


if __name__ == "__main__":
    main()
