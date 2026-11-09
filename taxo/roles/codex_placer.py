"""Placer agent through the local Codex CLI (`codex exec`), for SPEC §4 step 6 when no OPENAI_API_KEY is set.

Each call gets a batch of listings, each with its own short list of candidate nodes, and must answer in a fixed JSON
shape (--output-schema). Codex runs read-only in an empty scratch folder, so it can only read the prompt. Code checks
every answer before it counts (place_checked). Answers are cached by prompt hash, so a rerun never calls twice.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

ACTIONS = ("place", "new_product", "brand_only", "park")
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["decisions"],
    "properties": {"decisions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["listing_id", "action", "node_id", "new_product", "confidence", "reason"],
        "properties": {
            "listing_id": {"type": "string"},
            "action": {"type": "string", "enum": list(ACTIONS)},
            "node_id": {"type": ["string", "null"]},
            "new_product": {"type": ["string", "null"]},
            "confidence": {"type": "number"},
            "reason": {"type": "string"}}}}}}

PROMPT = """You place marketplace listings into the {domain} product tree. Answer ONLY from the text below; do not run
commands or browse. For each listing choose one action:
- place: it is exactly one of its candidate nodes (give node_id). Prefer the MOST SPECIFIC candidate the listing's own
  words support, never more specific than that. A product named after "for"/"compatible with" is NOT the product sold.
- new_product: the listing names a manufacturer model of its brand that is not among the candidates. Give node_id = the
  brand node id and new_product = the model exactly as written in the title.
- brand_only: the brand is clear but the listing names no specific product (give the brand node id).
- park: the brand cannot be told, or it is not a product of this domain.
Confidence 0-1. Reason: one short sentence naming the title words you used.
Domain conventions:
{conventions}

Listings:
{items}
"""


def alnum(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").casefold())


def _call(prompt: str, cache_dir: Path, model: str | None) -> dict:
    key = hashlib.sha256(prompt.encode()).hexdigest()[:20]
    cached = cache_dir / f"{key}.json"
    if cached.exists():
        return {"key": key, "cached": True, **json.loads(cached.read_text())}
    with tempfile.TemporaryDirectory() as tmp:
        schema = Path(tmp) / "schema.json"
        schema.write_text(json.dumps(SCHEMA))
        out = Path(tmp) / "out.json"
        cmd = ["codex", "exec", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral", "-C", tmp,
               "--output-schema", str(schema), "-o", str(out), "--color", "never", "-"]
        if model:
            cmd[2:2] = ["-m", model]
        proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True, timeout=900)
        if proc.returncode != 0 or not out.exists():
            return {"key": key, "cached": False, "error": (proc.stderr or proc.stdout)[-800:]}
        text = out.read_text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        data = json.loads(m.group(0)) if m else {"decisions": []}
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(data))
    return {"key": key, "cached": False, **data}


def run_batches(domain, conventions, items, cache_dir: Path, batch_size=40, max_calls=None, workers=4, model=None):
    """items: [{listing_id, text, candidates: [{id, path, level}]}]. Returns ({listing_id: decision}, stats)."""
    batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
    if max_calls is not None:
        batches = batches[:max_calls]
    prompts = []
    for b in batches:
        lines = []
        for it in b:
            cands = "\n".join(f"    - {c['id']} [{c['level']}] {' > '.join(c['path'])}" for c in it["candidates"])
            lines.append(f"- listing_id: {it['listing_id']}\n  {it['text']}\n  candidates:\n{cands or '    (none)'}")
        prompts.append(PROMPT.format(domain=domain, conventions=conventions or "(none)", items="\n".join(lines)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        results = list(ex.map(lambda p: _call(p, cache_dir, model), prompts))
    out, stats = {}, {"batches": len(batches), "calls": 0, "cached": 0, "errors": 0}
    for b, r in zip(batches, results):
        if "error" in r:
            stats["errors"] += 1
            stats.setdefault("error_samples", []).append(r["error"][-300:])
            continue
        stats["cached" if r["cached"] else "calls"] += 1
        asked = {it["listing_id"] for it in b}
        for d in r.get("decisions", []):
            if d.get("listing_id") in asked:
                out[d["listing_id"]] = d
    return out, stats


def place_checked(decision, item, nodes, brand_of):
    """Code checks an agent answer (SPEC §4 step 6; Pedia judge.py). Returns (ok, why)."""
    a = decision.get("action")
    nid = decision.get("node_id")
    allowed = {c["id"] for c in item["candidates"]}
    if a == "park":
        return True, "park"
    if nid not in nodes:
        return False, f"unknown node {nid}"
    if nid not in allowed:
        return False, "node not among this listing's candidates"
    if a == "place":
        return True, "place"
    if a in ("brand_only", "new_product") and nodes[nid]["level"] != "brand":
        return False, f"{a} needs a brand node"
    if a == "new_product":
        name = decision.get("new_product") or ""
        if len(alnum(name)) < 3 or alnum(name) not in alnum(item["title"]):
            return False, "new product name is not written in the title"
    if item.get("brand_id") and nid != item["brand_id"] and a != "place":
        return False, "agent changed the resolved brand"
    return True, a
