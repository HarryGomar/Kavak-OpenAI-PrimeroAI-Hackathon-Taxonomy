"""Cars agents through the local Codex CLI (`codex exec`, ChatGPT login; no OPENAI_API_KEY needed).

Two roles, both answering in a fixed JSON schema, read-only in an empty scratch folder, cached by prompt hash:

  placer     SPEC §4 step 6. A routed listing already sits on its supported node; the placer chooses among STOP (stay),
             the rules' deeper candidate, or existing children of that node, or names a new version written in the
             listing. Code checks every answer (option exists; a new version's words must be in the listing).
  validator  SPEC §5.2 (Loop B). Labels a listing's make > model > year > version BLIND (never sees the pipeline's
             answer), with confidence; scored on gold, compared with the pipeline to make a review queue. Silver only.

    uv run python -m domains.cars.pipeline --agent-calls 5               placer: 5 Codex calls (20 listings each)
    uv run python -m domains.cars.codex_agents validate --set gold       validator on the gold rows, scored
    uv run python -m domains.cars.codex_agents validate --set sample-r01 validator on the random 50 (silver + review queue)
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import tempfile
import time

import yaml

from taxo.core import config
from taxo.core.config import RUNS_DIR

from domains.cars import resolve

HERE = Path(__file__).resolve().parent
CACHE = RUNS_DIR / "cars" / "codex-cache"


LEDGER = RUNS_DIR / "cars" / "ledger.jsonl"


def _usage(stdout: str) -> dict:
    """Token usage from `codex exec --json` events (turn.completed); same parse as taxo/roles/codex_placer.py."""
    u = {}
    for line in stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "turn.completed":
            for k, v in (ev.get("usage") or {}).items():
                u[k] = u.get(k, 0) + v
    return u


def _ledger():
    from taxo.core.ledger import Ledger
    return Ledger(LEDGER)


def codex_json(prompt: str, schema: dict, effort: str = "medium", timeout: int = 900, role: str = "?", ledger=None,
               listings: int = 0) -> dict:
    """One `codex exec --json` call (cached by prompt). Every call, cached or not, is one hash-chained ledger entry with
    seconds and token usage (input, cached input, output, reasoning)."""
    key = hashlib.sha256((effort + "\0" + json.dumps(schema, sort_keys=True) + "\0" + prompt).encode()).hexdigest()[:20]
    prompt_sha = hashlib.sha256(prompt.encode()).hexdigest()[:12]
    cached = CACHE / f"{key}.json"
    if cached.exists():
        data = json.loads(cached.read_text(encoding="utf-8"))
        if ledger is not None:
            ledger.append("codex_call", domain="cars", role=role, key=key, cached=True, seconds=0.0, usage={},
                          listings=listings, effort=effort, prompt_sha256=prompt_sha, orig=data.get("_meta"))
        return {"_cached": True, **data}
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "schema.json").write_text(json.dumps(schema))
        out = Path(tmp) / "out.json"
        cmd = ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral", "-C", tmp,
               "-c", f'model_reasoning_effort="{effort}"', "--output-schema", str(Path(tmp) / "schema.json"),
               "-o", str(out), "--color", "never", "--json", "-"]
        proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=timeout)
        secs = round(time.time() - t0, 2)
        usage = _usage(proc.stdout)
        if proc.returncode != 0 or not out.exists():
            if ledger is not None:
                ledger.append("codex_call", domain="cars", role=role, key=key, cached=False, seconds=secs, usage=usage,
                              listings=listings, effort=effort, prompt_sha256=prompt_sha, error=True)
            return {"_error": (proc.stderr or proc.stdout)[-600:]}
        data = json.loads(out.read_text(encoding="utf-8"))
    data["_meta"] = {"secs": secs, "usage": usage, "tokens": sum(v for k, v in usage.items() if k != "cached_input_tokens")}
    if ledger is not None:
        ledger.append("codex_call", domain="cars", role=role, key=key, cached=False, seconds=secs, usage=usage,
                      listings=listings, effort=effort, prompt_sha256=prompt_sha)
    CACHE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return {"_cached": False, **data}


def run_all(prompts, schema, effort, workers=4, role="?", sizes=None):
    ledger = _ledger()
    sizes = sizes or [0] * len(prompts)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(lambda ps: codex_json(ps[0], schema, effort, role=role, ledger=None, listings=ps[1]),
                          zip(prompts, sizes)))
    wall = round(time.time() - t0, 2)
    for p, n, r in zip(prompts, sizes, res):   # ledger written in order, from one thread (hash chain)
        m = r.get("_meta") or {}
        ledger.append("codex_call", domain="cars", role=role, cached=bool(r.get("_cached")), error="_error" in r,
                      seconds=0.0 if r.get("_cached") else m.get("secs"), usage={} if r.get("_cached") else m.get("usage"),
                      listings=n, effort=effort, prompt_sha256=hashlib.sha256(p.encode()).hexdigest()[:12])
    tot = {}
    for r in res:
        if not r.get("_cached"):
            for k, v in ((r.get("_meta") or {}).get("usage") or {}).items():
                tot[k] = tot.get(k, 0) + v
    ledger.append("codex_batch", domain="cars", role=role, calls=sum(not r.get("_cached") for r in res),
                  cached=sum(bool(r.get("_cached")) for r in res), errors=sum("_error" in r for r in res),
                  wall_seconds=wall, call_seconds=round(sum((r.get("_meta") or {}).get("secs") or 0 for r in res if not r.get("_cached")), 2),
                  tokens=tot, workers=workers, effort=effort, listings=sum(sizes))
    for r in res:
        r["_wall"] = wall
    return res


def conventions() -> str:
    return yaml.safe_load((HERE / "pack.yaml").read_text(encoding="utf-8")).get("conventions", "")


def listing_text(raw: dict) -> str:
    keep = {k: v for k, v in raw.items() if k not in ("image", "imageUrl", "analytics", "_scraped_at", "url", "href")
            and v not in (None, "", [], {}, "$undefined")}
    if isinstance(keep.get("meta"), dict):
        keep["meta"] = {k: keep["meta"][k] for k in ("make", "serie", "ca-year", "body", "engine", "transmission",
                                                     "drive", "mileage", "price") if keep["meta"].get(k)}
    return json.dumps(keep, ensure_ascii=False)[:700]


# ------------------------------------------------------------------ placer (step 6)

PLACER_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["decisions"], "properties": {
    "decisions": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                  "required": ["listing_id", "choice", "new_version", "confidence", "reason"], "properties": {
                      "listing_id": {"type": "string"}, "choice": {"type": "string"},
                      "new_version": {"type": ["string", "null"]}, "confidence": {"type": "number"},
                      "reason": {"type": "string"}}}}}}

PLACER_PROMPT = """You finish placing used-car listings (Mexico) in the tree make > model > year > version.
Rules already settled each listing on a node. For each listing pick ONE option id:
- STOP: the listing gives no reliable deeper step (keep the settled node).
- one of the listed option ids: the deeper node the listing's own words support (most specific it supports, never more).
- NEW: the listing states a version (trim words, engine, gearbox) that matches none of the options; then put the
  version exactly as the listing writes it in new_version (only words from the listing).
Answer only from the text; do not run commands. Confidence 0-1. Reason: one sentence naming the words you used.
Conventions:
{conventions}

Listings:
{items}
"""


def placer(placements, raw_by_lid, nodes, children, max_calls: int, batch: int = 20, effort: str = "medium",
           gold_first: set[str] = frozenset()) -> dict:
    routed = [p for p in placements if p["route"] and p["node_id"]]
    first = [p for p in routed if p["listing_id"] in gold_first]
    rest = sorted((p for p in routed if p["listing_id"] not in gold_first), key=lambda p: p["listing_id"])
    random.Random(20261109).shuffle(rest)
    todo = (first + rest)[:max_calls * batch]
    items = []
    for p in todo:
        opts = {}
        if p["candidate"]:
            opts[p["candidate"]["node_id"]] = p["candidate"]
        for c in children.get(p["node_id"], []):
            if len(opts) >= 15:
                break
            opts.setdefault(c, nodes[c])
        items.append((p, opts))
    prompts = []
    for i in range(0, len(items), batch):
        lines = []
        for p, opts in items[i:i + batch]:
            o = "\n".join(f"    - {k}: {' > '.join(v['path'])}" for k, v in opts.items())
            lines.append(f"- listing_id: {p['listing_id']}\n  listing: {listing_text(raw_by_lid[p['listing_id']])}\n"
                         f"  settled: {' > '.join(p['path'])}\n  options:\n    - STOP\n    - NEW\n{o}")
        prompts.append(PLACER_PROMPT.format(conventions=conventions(), items="\n".join(lines)))
    results = run_all(prompts, PLACER_SCHEMA, effort, role="placer",
                      sizes=[len(items[i:i + batch]) for i in range(0, len(items), batch)])
    info = {"calls": sum(not r.get("_cached") and "_error" not in r for r in results),
            "cached": sum(bool(r.get("_cached")) for r in results), "errors": sum("_error" in r for r in results),
            "sent": len(items), "tokens": sum((r.get("_meta") or {}).get("tokens") or 0 for r in results),
            "secs": sum((r.get("_meta") or {}).get("secs") or 0 for r in results), "outcome": {}}
    answers = {d["listing_id"]: d for r in results for d in r.get("decisions", [])}
    out = {}
    for p, opts in items:
        d = answers.get(p["listing_id"])
        if not d:
            out[p["listing_id"]] = ("no_answer", None)
            continue
        ch = d["choice"].strip()
        words = set(resolve.key(listing_text(raw_by_lid[p["listing_id"]])).split())
        if ch == "STOP":
            out[p["listing_id"]] = ("stop", d)
        elif ch in opts:
            out[p["listing_id"]] = ("node", d | {"node": opts[ch], "node_id": ch})
        elif ch == "NEW" and d.get("new_version") and set(resolve.key(d["new_version"]).split()) <= words:
            out[p["listing_id"]] = ("new_version", d)
        else:
            out[p["listing_id"]] = ("refused", d)
    from collections import Counter
    info["outcome"] = dict(Counter(v[0] for v in out.values()))
    return {"info": info, "answers": out}


# ------------------------------------------------------------------ validator (Loop B, blind)

VALIDATOR_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["labels"], "properties": {
    "labels": {"type": "array", "items": {"type": "object", "additionalProperties": False,
               "required": ["listing_id", "out_of_domain", "make", "model", "year", "version", "confidence", "reason",
                            "question"], "properties": {
                   "listing_id": {"type": "string"}, "out_of_domain": {"type": "boolean"},
                   "make": {"type": ["string", "null"]}, "model": {"type": ["string", "null"]},
                   "year": {"type": ["integer", "null"]}, "version": {"type": ["string", "null"]},
                   "confidence": {"type": "number"}, "reason": {"type": "string"},
                   "question": {"type": ["string", "null"]}}}}}}

VALIDATOR_PROMPT = """You label used-car listings from Mexican marketplaces on your own. Nobody else's answer is shown.
For each listing give the deepest path you are sure of: make > model > model year > version (trim as the listing
states it: trim words, engine, gearbox). Leave a level null when the listing does not support it; never guess.
The make is the car's brand, never a dealer, marketplace or parent company (e.g. General Motors, Stellantis).
Model year is the car's model year, not the publication date. Body type is not part of the path.
If it is not a single car for sale (promo card, placeholder, part), set out_of_domain true.
Confidence 0-1. Reason: one sentence. question: the one thing a person must settle, or null.
Conventions:
{conventions}

Listings:
{items}
"""


EVIDENCE = ("title", "subtitle", "make", "maker", "brand", "slice_brand", "model", "version", "year", "year_km",
            "attributes", "transmission", "body_type", "subType", "traction", "drive", "fuel_type", "km", "kilometers",
            "mileageType", "condition", "dealer", "seller")
META = ("make", "serie", "ca-year", "body", "engine", "transmission", "drive", "fuel", "condition")


def evidence_text(raw: dict) -> str:
    """v2 query: only the fields that identify the car, never truncated (v1 cut raw JSON at 700 chars, which dropped
    Seminuevos/Kavak version and gearbox fields behind paging and promo fields)."""
    ev = {k: raw[k] for k in EVIDENCE if raw.get(k) not in (None, "", [], {}, "$undefined")}
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    ev.update({f"meta.{k}": meta[k] for k in META if meta.get(k) not in (None, "", "Sin Definir")})
    return json.dumps({"source": raw.get("_source"), **ev}, ensure_ascii=False)


_TREE = None


def catalogue_hint(raw: dict) -> str:
    """Catalogue versions of the model the listing ITSELF names (its make/model fields or first title words). Built
    from the listing and the catalogue only, never from the pipeline's answer."""
    global _TREE
    from domains.cars.gold_sample import catalogue_tree
    if _TREE is None:
        _TREE = catalogue_tree(config.data_dir() / "cars" / "taxonomy.jsonl")
    norm = lambda x: re.sub(r"[^a-z0-9]", "", resolve.fold(str(x or "")))
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    text = " ".join(str(x) for x in (raw.get("make") or raw.get("maker") or raw.get("brand") or raw.get("slice_brand")
                                      or meta.get("make") or "", raw.get("model") or meta.get("serie") or "",
                                      raw.get("title") or "") if x)
    words = [norm(w) for w in re.split(r"[\s,•|/]+", text) if w]
    for mk in _TREE:
        mkn = norm(mk)
        if mkn and (mkn in words or (len(mkn) > 3 and any(w.startswith(mkn) for w in words))):
            for md in sorted(_TREE[mk], key=len, reverse=True):
                if norm(md) and norm(md) in words or (" " in md and norm(md) in norm(text)):
                    vs = [f"{y}: " + "; ".join(v[:6]) for y, v in sorted(_TREE[mk][md].items()) if y and v]
                    return f"catalogue for {mk} {md}: " + (" | ".join(vs[:3]) or "no versions listed")
    return "catalogue: no model matched"


VALIDATOR_PROMPT_V2 = VALIDATOR_PROMPT.replace(
    "For each listing give the deepest path",
    "Each listing is its identifying fields (all of them, nothing cut) plus, when the listing names a model the "
    "catalogue knows, that model's current catalogue versions. The catalogue only covers recent years: use it to spell "
    "a version the listing states, never to add words the listing does not have. Fields such as version, subtitle, "
    "meta.serie, meta.engine and transmission are evidence like the title. A single trim letter (L, S, GL, LX) is a "
    "version.\nFor each listing give the deepest path")
VALIDATOR_PROMPTS = {1: VALIDATOR_PROMPT, 2: VALIDATOR_PROMPT_V2}


def validate(rows: list[tuple[str, dict]], batch: int = 15, effort: str = "high", version: int = 1) -> dict[str, dict]:
    prompts = []
    for i in range(0, len(rows), batch):
        if version == 1:
            items = "\n".join(f"- listing_id: {lid}\n  listing: {listing_text(raw)}" for lid, raw in rows[i:i + batch])
        else:
            items = "\n".join(f"- listing_id: {lid}\n  listing: {evidence_text(raw)}\n  {catalogue_hint(raw)}"
                              for lid, raw in rows[i:i + batch])
        prompts.append(VALIDATOR_PROMPTS[version].format(conventions=conventions(), items=items))
    results = run_all(prompts, VALIDATOR_SCHEMA, effort, role=f"validator_v{version}",
                      sizes=[len(rows[i:i + batch]) for i in range(0, len(rows), batch)])
    out = {l["listing_id"]: l for r in results for l in r.get("labels", [])}
    out["_stats"] = {"prompts": len(prompts), "errors": sum("_error" in r for r in results),
                     "cached": sum(bool(r.get("_cached")) for r in results),
                     "tokens": sum((r.get("_meta") or {}).get("tokens") or 0 for r in results if not r.get("_cached")),
                     "secs": sum((r.get("_meta") or {}).get("secs") or 0 for r in results if not r.get("_cached")),
                     "wall_secs": results[0].get("_wall") if results else 0, "version": version,
                     "error_samples": [r["_error"][-200:] for r in results if "_error" in r][:2]}
    return out


GEAR = {"aut", "at", "auto", "automatico", "automatica", "cvt", "std", "mt", "manual", "tm", "dct", "dsg", "tiptronic",
        "l", "t", "estandar", "standard", "base"}
SAME = {"4wd": "4x4", "awd": "4x4", "4x4": "4x4", "fwd": "4x2", "4x2": "4x2"}


def _make_aliases() -> dict:
    ident = yaml.safe_load((HERE / "identity.yaml").read_text(encoding="utf-8"))
    return {resolve.key(k): v for k, v in ident["brands"]["aliases"].items()}


ALIASES = _make_aliases()


def canon_make(s) -> str:
    k = resolve.key(s)
    return ALIASES.get(k, k).replace(" ", "").replace("-", "")


def words(s) -> set[str]:
    out = set()
    for t in resolve.key(s).split():
        t = re.sub(r"^(\d\.\d)l$", r"\1", t)          # 2.0l -> 2.0
        t = SAME.get(t, t)
        if t not in GEAR:
            out.add(t)
    return out


def versions_agree(a: set[str], b: set[str]) -> bool:
    """Same trim when one side's words are inside the other's, or they share a trim word and no number conflicts."""
    if not a or not b:
        return False
    if a <= b or b <= a:
        return True
    na = {t for t in a if re.fullmatch(r"[\d.]+", t)}
    nb = {t for t in b if re.fullmatch(r"[\d.]+", t)}
    return bool((a - na) & (b - nb)) and not (na and nb and not na & nb)


def compare(label: dict, path: list[str]) -> dict:
    """Level by level: agree / disagree / one side silent. path = [make, model, year, version] (any depth).
    A word the validator put in the model and the path puts in the version (or the reverse) is not a disagreement."""
    out = {}
    pm = [path[i] if i < len(path) else None for i in range(4)]
    vm = [label.get("make"), label.get("model"), label.get("year"), label.get("version")]
    for i, lvl in enumerate(("make", "model", "year", "version")):
        if vm[i] in (None, "") or pm[i] in (None, ""):
            res = None
        elif lvl == "make":
            res = canon_make(vm[i]) == canon_make(pm[i])
        elif lvl == "year":
            res = str(vm[i]) == str(pm[i])
        elif lvl == "model":
            a, b = words(vm[i]), words(pm[i])
            res = bool(a) and bool(b) and (a <= b or b <= a)
        else:
            a = (words(vm[1]) | words(vm[3])) - words(pm[1])
            b = (words(pm[1]) | words(pm[3])) - words(vm[1]) if vm[1] else words(pm[3])
            a, b = a - words(pm[1]), b - words(vm[1] or "")
            res = None if not a or not b else versions_agree(a, b)
        out[lvl] = "silent" if res is None else ("agree" if res else "disagree")
        if res is False:
            break
    return out


def main() -> None:
    from collections import Counter

    from taxo.core.io import read_jsonl

    from domains.cars.adapter import listing_id
    ap = argparse.ArgumentParser(prog="domains.cars.codex_agents", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--set", default="gold", help="gold | sample-r01 (the random 50) ")
    v.add_argument("--effort", default="high")
    a = ap.parse_args()
    d = config.data_dir() / "cars"
    raw = {}
    for r in read_jsonl(d / "listings.jsonl"):
        raw.setdefault(listing_id(r), r)
    pl = {p["listing_id"]: p for p in read_jsonl(RUNS_DIR / "cars" / "placements.jsonl")}
    gold = {}
    for f in sorted((d / "gold").glob("*.yaml")):
        for g in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
            gold[g["listing_id"]] = g | {"_file": f.name}
    if a.set == "gold":
        ids = sorted(gold)
    else:
        ids = [json.loads(l)["listing_id"] for l in (RUNS_DIR / "cars" / "gold-r01" / f"{a.set}.jsonl").read_text().splitlines()]
    labels = validate([(i, raw[i]) for i in ids], effort=a.effort)
    stats = labels.pop("_stats")
    rows, vs_gold, vs_pipe = [], Counter(), Counter()
    for i in ids:
        lab = labels.get(i)
        p = pl[i]
        pipe_path = (p["candidate"] or p)["path"] if p["node_id"] or p["candidate"] else []
        row = {"listing_id": i, "title": p["title"], "validator": lab,
               "pipeline_settled": p["path"], "pipeline_specific": pipe_path}
        if not lab:
            vs_pipe["no_answer"] += 1
        else:
            if lab["out_of_domain"] or not pipe_path:
                c = "agree" if lab["out_of_domain"] == (not pipe_path) else "disagree"
                row["vs_pipeline"] = {"scope": c}
            else:
                row["vs_pipeline"] = compare(lab, pipe_path)
            worst = "disagree" if "disagree" in row["vs_pipeline"].values() else "agree"
            vs_pipe[worst] += 1
            row["review"] = worst == "disagree" or lab["confidence"] < 0.6
            if i in gold:
                g = gold[i]
                if not g["expected_path"]:
                    row["vs_gold"] = {"scope": "agree" if lab["out_of_domain"] else "disagree"}
                else:
                    row["vs_gold"] = compare(lab, g["expected_path"])
                for lvl, res in row["vs_gold"].items():
                    vs_gold[f"{lvl}:{res}"] += 1
                vs_gold["rows"] += 1
                vs_gold["rows_no_disagreement"] += "disagree" not in row["vs_gold"].values()
        rows.append(row)
    out = RUNS_DIR / "cars" / "validator"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / f"silver-{a.set}.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    queue = [r for r in rows if r.get("review")]
    with open(out / f"review-queue-{a.set}.jsonl", "w", encoding="utf-8") as f:
        for r in queue:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    summary = {"set": a.set, "listings": len(ids), "answered": sum(1 for r in rows if r["validator"]), "codex": stats,
               "validator_vs_pipeline": dict(vs_pipe), "review_queue": len(queue),
               "validator_vs_gold": dict(sorted(vs_gold.items())) if vs_gold else "no gold rows in this set"}
    (out / f"summary-{a.set}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
