"""Loop B's validator, run (SPEC §5.2): label a random sample blind, score the validator on human labels, and extend
the pipeline's KPI from the human rows to the validator's bigger sample (metrics.extend, docs/KPIS.md).

    uv run python -m taxo.validate fragrance --human 50 --fresh 300
    uv run python -m taxo.validate fragrance --dry            draw the samples and count the calls; no model calls

Runs on the Codex CLI (`codex exec`, the ChatGPT login: no API key) by default; --runner sdk uses OPENAI_API_KEY.
About 20 s a call, 5 at a time: the default 350 calls take about 25 minutes.

Reads the pipeline's last run (runs/<domain>/placements.jsonl and metrics.json: run taxo.pipeline first) and samples,
with a fixed seed:
  - human rows: dev rows a person labelled (never sealed), each linked to a listing the pipeline placed;
  - fresh rows: listings with no label at all.
The validator sees the listing only: never the label, never the pipeline's answer. Each answer is saved as it comes
(runs/<d>/silver-v<k>.jsonl, keyed by the setup's hash), so a rerun of the same setup only pays for new rows.

Writes runs/<d>/validator-v<k>.json (its score on the human rows) and one KPI row (loop B) whose `silver` holds the
extended exact and right-or-shallower rates.

"Right per the validator" is the pipeline's path judged against the validator's path by the same scorer as gold; an
abstention or a failed call counts as not right. Any fixed rule works: the offset measured on the human rows
corrects for it.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import time
from collections import Counter
from dataclasses import fields
from pathlib import Path

import yaml

from taxo import gold as goldmod, kpis, score
from taxo.core.config import DOMAINS_DIR, ROOT, RUNS_DIR
from taxo.core.metrics import extend, rate
from taxo.lattice.vocab import tokens
from taxo.parse import Brands
from taxo.pipeline import load_gold

SEED = 20261109
EXACT = {"exact"}
RIGHT = {"exact", "shallower"}

PROMPT = """Listing title: {title}
Brand field: {brand_field}
Maker field: {maker_field}
Shop: {source}

Give the path brand first: the brand, then the product line if the brand sells one as a line, then the product's own
name. Stop at the deepest level you are sure of: a correct shorter path beats a wrong longer one. Leave sizes, pack
counts and concentration out of the names. No proposed path is given: answer abstain only if you cannot place it at
all, otherwise accept."""


def load_run(run_dir: Path) -> tuple[list[dict], dict]:
    p = run_dir / "placements.jsonl"
    if not p.exists():
        raise SystemExit(f"{p} not found: run `uv run python -m taxo.pipeline <domain>` first")
    items = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return items, json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))


def draw(items: list[dict], truth: list[goldmod.GoldRow], n_human: int, n_fresh: int, seed: int = SEED):
    """(human pairs [(row, item)], fresh items). Human rows: accept rows on dev brands only, linked to an item."""
    by_gold = {g: it for it in items for g in it.get("gold") or []}
    pairs = [(r, by_gold[r.id]) for r in truth
             if r.expect == "accept" and r.id in by_gold and not goldmod.is_sealed(r.brand)]
    fresh = [it for it in items if not it.get("gold") and it.get("source") != "gold"]
    rng = random.Random(seed)
    return rng.sample(pairs, min(n_human, len(pairs))), rng.sample(fresh, min(n_fresh, len(fresh)))


def setup_hash(domain: str) -> str:
    return hashlib.sha256((DOMAINS_DIR / domain / "validator.yaml").read_bytes()).hexdigest()[:10]


def load_cache(path: Path, key: str) -> dict[str, dict]:
    if not path.exists():
        return {}
    rows = (json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip())
    return {r["id"]: r for r in rows if r.get("setup") == key}


def _runner(kind: str = "cli"):
    """cli: the Codex CLI (`codex exec`, the ChatGPT login; taxo/core/codex.py), the default. sdk: the Agents SDK,
    which needs OPENAI_API_KEY. None when the chosen one is not available."""
    if kind == "sdk":
        if not os.environ.get("OPENAI_API_KEY"):
            return None
        from agents import Runner
        return lambda agent, msg, ctx: Runner.run(agent, msg, context=ctx)
    try:
        from taxo.core.codex import runner
    except ImportError:
        return None
    run = runner("cli")
    return run and (lambda agent, msg, ctx: asyncio.to_thread(run, agent, msg, ctx))


async def ask_live(domain: str, names: list[str], todo: list[dict], concurrency: int, on_done,
                   runner: str = "cli") -> None:
    from taxo.roles.validator import ValidateContext, make_validator
    run = _runner(runner)
    agent = make_validator(domain)
    has_id = "listing_id" in {f.name for f in fields(ValidateContext)}
    sem = asyncio.Semaphore(concurrency)

    async def one(it: dict) -> None:
        ctx = ValidateContext(domain=domain, brands=names, **({"listing_id": it["id"]} if has_id else {}))
        msg = PROMPT.format(title=it["title"], brand_field=it.get("brand_field") or "-",
                            maker_field=it.get("maker_field") or "-", source=it.get("source") or "-")
        async with sem:
            try:
                out = (await run(agent, msg, ctx)).final_output
            except Exception as e:                           # one failed call must not sink the batch
                on_done(it, {"error": repr(e)[:300]})
                return
        trace = getattr(out, "trace", None) or getattr(out, "steps_done", None) or []
        on_done(it, {"path": out.path, "decision": out.decision.value, "confidence": out.confidence,
                     "reason": out.reason, "trace": [t.model_dump() if hasattr(t, "model_dump") else t for t in trace]})

    await asyncio.gather(*(one(it) for it in todo))


def _slug(brands: Brands, path: list[str]) -> str | None:
    return (brands.exact(path[0]) or brands.lead(tokens(path[0]))) if path else None


def _btoks(brands: Brands, slug: str | None) -> set[str]:
    return {t for r in brands.runs(slug) for t in r} if slug else set()


def system_vs(it: dict, ref_brand: str | None, ref_path: list[str], brands: Brands, compare: str = "prefix") -> str:
    """The pipeline's class (exact, shallower, ...) with `ref` as the expected path; no_ref when there is none."""
    if not ref_brand or not ref_path:
        return "no_ref"
    return score.judge(it.get("brand"), it.get("path") or [], ref_brand, ref_path, _btoks(brands, ref_brand),
                       compare).cls


def evaluate(pairs, fresh: list[dict], answers: dict[str, dict], brands: Brands, population: int | None) -> dict:
    """The validator's score on the human rows, its tilt, and the pipeline's KPIs extended to the fresh rows."""
    def v(it: dict) -> tuple[str | None, list[str], dict]:
        a = answers.get(it["id"]) or {"error": "not asked"}
        path = [] if "error" in a or a.get("decision") == "abstain" else a.get("path") or []
        return _slug(brands, path), path, a

    rep, abstain, failed = score.Report(), 0, 0
    h_sys, v_sys = [], []                                         # pipeline's class per person / per validator
    for r, it in pairs:
        vb, vp, a = v(it)
        abstain += a.get("decision") == "abstain"
        failed += "error" in a
        rep.add(score.judge(vb, vp, r.brand, r.expected_path, _btoks(brands, r.brand), r.compare, r.expect))
        h_sys.append(system_vs(it, r.brand, r.expected_path, brands, r.compare))
        v_sys.append(system_vs(it, vb, vp, brands))
    f_v = [v(it) for it in fresh]
    f_sys = [system_vs(it, vb, vp, brands) for it, (vb, vp, _) in zip(fresh, f_v)]
    n = len(pairs)
    on_human = rep.summary()
    if n:
        on_human["ci"] = {k: rate(round(on_human[k] * n), n) for k in kpis.RATES}
    out = {"human_rows": n, "fresh_rows": len(fresh), "abstain": round(abstain / n, 3) if n else None,
           "failed_calls": failed + sum("error" in a for _, _, a in f_v), "on_human": on_human}
    for name, ok in (("exact", EXACT), ("right_or_shallower", RIGHT)):
        h, vh = [c in ok for c in h_sys], [c in ok for c in v_sys]
        # tilt: the validator calls the pipeline right when the person said wrong (lenient), or the reverse (strict)
        out[f"{name}_lenient"] = round(sum(b and not a for a, b in zip(h, vh)) / n, 3) if n else None
        out[f"{name}_strict"] = round(sum(a and not b for a, b in zip(h, vh)) / n, 3) if n else None
        if n >= 2 and len(fresh) >= 2:
            out[name] = extend(h, vh, [c in ok for c in f_sys], population)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.validate")
    ap.add_argument("domain", choices=["fragrance"])
    ap.add_argument("--data", choices=["drive", "edu"], default="drive")
    ap.add_argument("--run", type=Path, help="pipeline run dir (default runs/<domain>)")
    ap.add_argument("--truth", choices=["human", "gold"], default="human",
                    help="human: the people's labels (default); gold: the primary gold (Pedia's labels on drive)")
    ap.add_argument("--human", type=int, default=50, help="human-labelled rows to validate")
    ap.add_argument("--fresh", type=int, default=300, help="unlabelled listings to validate")
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--runner", choices=["cli", "sdk"], default="cli",
                    help="cli: Codex CLI on the ChatGPT login, no key (default); sdk: Agents SDK with OPENAI_API_KEY")
    ap.add_argument("--concurrency", type=int, default=5)
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--label", default="validator run")
    ap.add_argument("--dry", action="store_true", help="draw the samples and count the calls; no model calls")
    a = ap.parse_args()
    t0 = time.time()
    items, metrics = load_run(a.run or RUNS_DIR / a.domain)
    rows, human_rows, names = load_gold(a.data)
    brands = Brands(names)
    pairs, fresh = draw(items, human_rows if a.truth == "human" else rows, a.human, a.fresh, a.seed)
    setup = yaml.safe_load((DOMAINS_DIR / a.domain / "validator.yaml").read_text(encoding="utf-8"))
    ver, key = f"v{setup.get('version', 0)}", setup_hash(a.domain)
    cache_path = RUNS_DIR / a.domain / f"silver-{ver}.jsonl"
    answers = load_cache(cache_path, key)
    todo = [it for it in [it for _, it in pairs] + fresh if it["id"] not in answers]
    print(f"{len(pairs)} human rows, {len(fresh)} fresh rows: {len(todo)} validator calls to make "
          f"({ver}, model {setup.get('model')}, setup {key}, {len(answers)} cached)")
    if a.dry:
        return
    if todo:
        if _runner(a.runner) is None:
            raise SystemExit("cli: taxo/core/codex.py and the `codex` CLI are needed" if a.runner == "cli"
                             else "sdk: OPENAI_API_KEY is not set (.env)")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        done = [0]

        def on_done(it: dict, ans: dict) -> None:
            done[0] += 1
            row = {"id": it["id"], "title": it["title"], "validator": ver, "setup": key,
                   "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **ans}
            answers[it["id"]] = row
            if "error" not in ans:                               # failures are retried on the next run
                with open(cache_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
            if done[0] % 25 == 0 or done[0] == len(todo):
                print(f"  {done[0]}/{len(todo)}")

        asyncio.run(ask_live(a.domain, sorted(names.values()), todo, a.concurrency, on_done, a.runner))
    res = evaluate(pairs, fresh, answers, brands, metrics.get("listings"))
    silver = {"validator": ver, "setup": key, "model": setup.get("model"), "truth": a.truth, "seed": a.seed,
              "human_sample": kpis._sample(Counter(r.origin for r, _ in pairs)), **res}
    (RUNS_DIR / a.domain / f"validator-{ver}.json").write_text(json.dumps(silver, indent=1), encoding="utf-8")
    kp = kpis.append(a.domain, kpis.row(a.domain, metrics, "B", a.round, f"{a.label} ({ver})",
                                        DOMAINS_DIR / a.domain / "vocab.yaml",
                                        [ROOT / "rules" / a.domain, ROOT / "rules" / "global"], silver=silver))
    print(json.dumps({k: v for k, v in silver.items() if k != "on_human"} | {"secs": round(time.time() - t0, 1)},
                     indent=1))
    print(f"KPI row appended to {kp}")


if __name__ == "__main__":
    main()
