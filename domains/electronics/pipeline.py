"""Electronics pipeline (SPEC §4), from the raw listings to a brand > product > variant tree and one placement each.

    uv run python -m domains.electronics.pipeline                    rules only; routed listings are counted
    uv run python -m domains.electronics.pipeline --agent-calls 20   also send routed listings to the placer agent,
                                                                     via the local Codex CLI (20 calls x 40 listings);
                                                                     --agent openai uses the Agents SDK + OPENAI_API_KEY

Steps, cheapest first. Each placement records the step that decided it:
  1 parse     own-product text vs "for <device>" reference text; capacity, colour, pack, condition, bundle
              + category (browse field, never a level): domains/electronics/categories/
  2 brand     brand field, title prefix, title over an absent field brand, alias table   (identity.yaml)
  3 registry  none: electronics has no official catalogue yet (recorded, skipped)
  4 lattice   own identifiers grouped inside each brand (shared id, merchant/series prefix, colour-code suffix),
              guarded against different part numbers; variants only for evidenced colour/capacity axes
  5 route     brand without a model number -> agent_title; no brand -> agent_evidence
  6 agent     taxo/roles/placer.py on the routed listings, only with --agent-calls and a key

Data (never in Git): TAXO_DATA_DIR/electronics/listings/products.csv (+ public_match_labels.csv),
TAXO_DATA_DIR/electronics/gold/*.yaml. Output: runs/electronics/.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
import re
import time

import yaml

from domains.electronics import adapter, graph
from domains.electronics.classify import Categories

CATS = Categories()
from taxo import gold as goldmod, score
from taxo.core import config
from taxo.core.config import RUNS_DIR
from taxo.core.schemas import Node
from taxo.lattice.vocab import tokens as vtokens

DOMAIN = "electronics"
OUT = RUNS_DIR / DOMAIN
LEVEL = {"Brand": "brand", "ProductModel": "product", "ProductVariant": "variant"}


def load():
    rows, listings = {}, []
    for l in adapter.load_listings():
        f = l.fields
        rows[l.id] = {"record_key": l.id, "title": l.title, "merchant": l.source or "", "brand_manufacturer": l.brand or "",
                      "manufacturer_model": f.get("manufacturer_model", ""), "source_category": f.get("source_category", ""),
                      "dataset": f.get("dataset", ""), "price_raw": f.get("price_raw", "")}
        listings.append(l)
    return rows, listings


def type_id(brand_id, cat):
    return "ty_" + hashlib.sha256(f"type|{brand_id}|{cat}".encode()).hexdigest()[:12]


def brand_of(n, tnodes):
    while n["level"] != "brand":
        n = tnodes[n["parent_id"]]
    return n["id"]


def add_type(out, brand_id, cat, cats):
    """Browse level Brand > product type (owner convention, review r01). Never part of a product's id."""
    tid = type_id(brand_id, cat)
    if tid not in out:
        b = out[brand_id]
        label = cats.categories[cat]["label"]
        out[tid] = {"id": tid, "level": "type", "name": label, "parent_id": brand_id, "path": b["path"] + [label],
                    "status": b["status"], "category": cat}
    return tid


def tree(nodes, edges, cats):
    """Scaffold tree: brand > product type > product > variant, paths of labels. Trade items stay off the tree.
    The type level is the product's category (CLASSIFIED_AS); ids of products and variants never include it."""
    cat_of = {e["from"]: e["to"][len("cat:"):] for e in edges if e["type"] == "CLASSIFIED_AS"}
    out = {}
    for n in nodes.values():
        if n["type"] == "Brand":
            out[n["id"]] = {"id": n["id"], "level": "brand", "name": n["label"], "parent_id": None, "path": [n["label"]],
                            "status": n["status"]}
    for n in nodes.values():
        if n["type"] == "ProductModel":
            t = out[add_type(out, n["brand"], cat_of[n["id"]], cats)]
            out[n["id"]] = {"id": n["id"], "level": "product", "name": n["label"], "parent_id": t["id"],
                            "path": t["path"] + [n["label"]], "status": n["status"], "listings": n["listing_count"],
                            "category": cat_of[n["id"]],
                            "identifier_keys": n["identifier_keys"], "variant_axes": n.get("variant_axes", [])}
    for n in nodes.values():
        if n["type"] == "ProductVariant":
            m = out[n["model"]]
            out[n["id"]] = {"id": n["id"], "level": "variant", "name": n["label"], "parent_id": n["model"],
                            "path": m["path"] + [n["label"]], "status": n["status"], "axes": n["axes"]}
    return out


def tree_node(nodes, nid):
    """The tree node a graph target sits on (a trade item sits on its base product or variant)."""
    trade = None
    while nid and nodes[nid]["type"] == "TradeItem":
        trade = trade or {"kind": nodes[nid]["kind"], "id": nid, "status": nodes[nid]["status"]}
        nid = nodes[nid]["base"]
    return nid, trade


def place(rows, previews, nodes, gplacements, cats, tnodes):
    by_key = {p["mention_id"]: p for p in gplacements}
    out = []
    for k, prev in sorted(previews.items()):
        p = by_key.get(k)
        rec = {"listing_id": k, "title": rows[k]["title"], "source": rows[k]["merchant"],
               "category": prev["proposed_category"], "category_status": prev["status"],
               "category_rules": [h["rule_id"] for h in prev["rule_hits"]], "node_id": None, "path": [], "level": "none",
               "trade_item": None, "step": None, "route": None, "rule_ids": [], "reason": "", "by": "rules",
               "outcome": None, "confidence": None}
        if not prev["proposed_category"]:
            rec.update(step="parse", route="park", reason=f"no electronics category ({prev['status']})")
        elif not p["target_node_id"]:
            rec.update(step="brand", route="agent_evidence", reason="brand unresolved", outcome="unmatched")
        else:
            nid, trade = tree_node(nodes, p["target_node_id"])
            if tnodes[nid]["level"] == "brand":
                nid = add_type(tnodes, nid, prev["proposed_category"], cats)
            t = tnodes[nid]
            rec.update(node_id=nid, path=t["path"], level=t["level"], trade_item=trade, rule_ids=p["rule_ids"],
                       reason="; ".join(p["reason_codes"]), outcome=p["outcome"],
                       confidence=1.0 if p["outcome"] == "matched" else 0.6)
            if t["level"] == "type":
                rec.update(step="brand", route="agent_title", confidence=0.5)
            else:
                rec.update(step="lattice")
        out.append(rec)
    return out


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").casefold()) if len(w) >= 2}


_IDF = {}


def _idf(tnodes):
    if not _IDF:
        import math
        docs = [_words(" ".join(n["path"]) + " " + " ".join(n.get("identifier_keys", []))) for n in tnodes.values()]
        df = Counter(w for d in docs for w in d)
        _IDF.update({w: math.log(len(docs) / c) for w, c in df.items()})
    return _IDF


def candidates_for(p, tnodes, by_brand, k=25):
    """A listing's page of candidate nodes. With a resolved brand: the brand and its products/variants ranked by shared
    rare title words. Without one: brands whose name is written in the title (and their products), then the
    best-matching products anywhere with their brands."""
    idf = _idf(tnodes)
    tw = _words(p["title"])
    title_key = " " + " ".join(re.findall(r"[a-z0-9]+", p["title"].casefold())) + " "

    def rank(pool, floor=0.0):
        sc = []
        for n in pool:
            shared = tw & _words(" ".join(n["path"][1:]) + " " + " ".join(n.get("identifier_keys", [])))
            s = sum(idf.get(w, 0) for w in shared)
            if s > floor:
                sc.append((round(s, 6), n["id"]))
        return [tnodes[i] for _, i in sorted(sc, reverse=True)[:k]]

    if p["node_id"] and tnodes[p["node_id"]]["level"] in ("brand", "type"):
        bid = brand_of(tnodes[p["node_id"]], tnodes)
        head, picked = [tnodes[bid]], rank([n for n in by_brand.get(bid, []) if n["level"] != "type"])
    else:
        named = [n for n in tnodes.values() if n["level"] == "brand" and len(n["name"]) >= 2
                 and f" {' '.join(re.findall(r'[a-z0-9]+', n['name'].casefold()))} " in title_key]
        named.sort(key=lambda n: -len(n["name"]))
        head = named[:3]
        picked = rank([x for b in head for x in by_brand.get(b["id"], []) if x["level"] != "type"])
        if len(picked) < k:
            # Anywhere in the tree only on a rare shared word (e.g. a model number), never on "series" or "black".
            extra = [n for n in rank([n for n in tnodes.values() if n["level"] not in ("brand", "type")], floor=5.0)
                     if n not in picked]
            picked += extra[:k - len(picked)]
            for n in extra[:k]:
                bid = brand_of(n, tnodes)
                if tnodes[bid] not in head and len(head) < 6:
                    head.append(tnodes[bid])
    return [{"id": n["id"], "path": n["path"], "level": n["level"]} for n in head + picked]


def codex_step(placements, tnodes, max_calls, model=None):
    from taxo.roles import codex_placer
    pack = yaml.safe_load((config.DOMAINS_DIR / DOMAIN / "pack.yaml").read_text(encoding="utf-8"))
    routed = [p for p in placements if p["route"] in ("agent_title", "agent_evidence")]
    by_brand = {}
    for n in tnodes.values():
        if n["level"] != "brand":
            by_brand.setdefault(brand_of(n, tnodes), []).append(n)
    items = []
    for p in sorted(routed, key=lambda p: hashlib.sha256(p["listing_id"].encode()).hexdigest()):
        items.append({"listing_id": p["listing_id"], "title": p["title"],
                      "brand_id": brand_of(tnodes[p["node_id"]], tnodes) if p["node_id"] else None, "category": p["category"],
                      "text": f"title: {p['title']} | source: {p['source']} | category: {p['category']}",
                      "candidates": candidates_for(p, tnodes, by_brand)})
    from taxo.core.ledger import Ledger
    answers, stats = codex_placer.run_batches(DOMAIN, pack.get("conventions", ""), items, OUT / "codex-cache",
                                              max_calls=max_calls, model=model, workers=6,
                                              ledger=Ledger(OUT / "ledger.jsonl"), role="placer")
    by_id = {p["listing_id"]: p for p in placements}
    log, outcome = [], Counter()
    for it in items:
        d = answers.get(it["listing_id"])
        if not d:
            continue
        ok, why = codex_placer.place_checked(d, it, tnodes, None)
        p = by_id[it["listing_id"]]
        log.append({"listing_id": it["listing_id"], "route": p["route"], "title": it["title"], "decision": d,
                    "accepted": ok, "check": why})
        if not ok:
            outcome["rejected_by_check"] += 1
            p["reason"] += f"; agent answer rejected: {why}"
            continue
        a = d["action"]
        outcome[a] += 1
        if a == "place":
            n = tnodes[d["node_id"]]
            p.update(node_id=n["id"], path=n["path"], level=n["level"], step="agent", route=None)
        elif a == "new_product":
            b = tnodes[add_type(tnodes, d["node_id"], it["category"], CATS)]
            name = d["new_product"].strip()
            nid = f"pa_{hashlib.sha256(('agent-product|' + b['id'] + '|' + codex_placer.alnum(name)).encode()).hexdigest()[:12]}"
            tnodes.setdefault(nid, {"id": nid, "level": "product", "name": name, "parent_id": b["id"],
                                    "path": b["path"] + [name], "status": "candidate", "proposed_by": "agent",
                                    "listings": 0, "identifier_keys": [codex_placer.alnum(name)], "variant_axes": []})
            tnodes[nid]["listings"] += 1
            p.update(node_id=nid, path=tnodes[nid]["path"], level="product", step="agent", route=None)
        elif a == "brand_only":
            n = tnodes[add_type(tnodes, d["node_id"], it["category"], CATS)]
            p.update(node_id=n["id"], path=n["path"], level="type", step="agent", route=None)
        else:
            p.update(step="agent", route="park")
        p.update(by="codex", confidence=d["confidence"], reason=f"agent {a}: {d['reason']}", outcome="agent")
    write_jsonl(OUT / "agent-decisions.jsonl", log)
    return {"backend": "codex", "routed": len(routed), **stats, "answers": len(answers), "outcomes": dict(outcome)}


def agent_step(placements, tnodes, max_calls, backend="openai", model=None):
    routed = [p for p in placements if p["route"] in ("agent_title", "agent_evidence")]
    if backend == "codex" and max_calls > 0:
        return codex_step(placements, tnodes, max_calls, model)
    if max_calls <= 0 or not os.environ.get("OPENAI_API_KEY"):
        return {"routed": len(routed), "calls": 0, "note": "agent off (no --agent-calls, or --agent openai without OPENAI_API_KEY)"}
    from agents import Runner
    from taxo import memory
    from taxo.roles.placer import PlaceContext, make_placer
    pack = yaml.safe_load((config.DOMAINS_DIR / DOMAIN / "pack.yaml").read_text(encoding="utf-8"))
    nodes = {i: Node(id=i, domain=DOMAIN, name=n["name"], parent_id=n["parent_id"], level=n["level"], path=n["path"])
             for i, n in tnodes.items()}
    for n in nodes.values():
        if n.parent_id in nodes:
            nodes[n.parent_id].children.append(n.id)
    ctx = PlaceContext(DOMAIN, nodes, memory.rules_for(DOMAIN, tuple(pack.get("families", []))))
    agent = make_placer(DOMAIN, pack.get("conventions", ""))
    calls = 0
    for p in sorted(routed, key=lambda p: hashlib.sha256(p["listing_id"].encode()).hexdigest())[:max_calls]:
        res = Runner.run_sync(agent, f"Listing title: {p['title']}\nSource: {p['source']}\nCategory: {p['category']}",
                              context=ctx).final_output
        calls += 1
        if res.node_id in nodes:
            p.update(node_id=res.node_id, path=nodes[res.node_id].path, level=nodes[res.node_id].level, step="agent",
                     by=agent.name, confidence=res.confidence, reason=res.reason, outcome="agent")
        else:
            p.update(step="agent", by=agent.name, reason=f"agent abstained: {res.reason}")
    return {"routed": len(routed), "calls": calls}


def score_gold(placements):
    """Gold rows in the scaffold format (docs/templates/gold.example.yaml), matched by listing_id. Dev split only;
    the sealed split is read by the gate, never here."""
    gdir = config.data_dir() / DOMAIN / "gold"
    files = sorted(gdir.glob("*.yaml")) if gdir.exists() else []
    if not files:
        return {"note": "no gold yet: label a blind random sample (gold/round-01.yaml)"}
    lid = {}
    for f in files:
        for r in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
            lid[r["id"]] = r["listing_id"]
    rows = goldmod.read_fixtures(files)
    g = goldmod.Gold(rows, OUT / "sealed-reads.jsonl")
    by_id = {p["listing_id"]: p for p in placements}
    rep = score.Report()
    for r in g.dev:
        p = by_id.get(lid[r.id])
        pred_brand = p["path"][0].casefold() if p and p["path"] else None
        j = score.judge(pred_brand, p["path"] if p else [], r.brand, r.expected_path, set(vtokens(r.brand)),
                        r.compare, r.expect)
        rep.add(j, r.expect)
    return {"files": [f.name for f in files], "dev": rep.summary(), "sealed_brands": len(g.sealed_brands())}


def write_jsonl(path, items):
    path.write_text("".join(json.dumps(i, ensure_ascii=False, sort_keys=True) + "\n" for i in items), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent-calls", type=int, default=0, help="max agent calls (codex: batches of 40 listings)")
    ap.add_argument("--agent", choices=("codex", "openai"), default="codex",
                    help="codex = local Codex CLI (ChatGPT sign-in); openai = Agents SDK with OPENAI_API_KEY")
    ap.add_argument("--model", default=None, help="model override for the agent backend")
    args = ap.parse_args()
    t0 = time.time()
    timings = {}
    rows, _ = load()
    timings["load"] = round(time.time() - t0, 2)
    cats = Categories()
    t = time.time()
    previews = {k: cats.categorize(r) for k, r in rows.items()}                                    # step 1 (category)
    timings["parse_category"] = round(time.time() - t, 2)
    t = time.time()
    cfg = graph.read_yaml(graph.CONFIG_PATH)
    nodes, edges, gplacements, review, _, checks = graph.construct(rows, list(previews.values()), cats, cfg)  # 1, 2, 4
    timings["brand_lattice"] = round(time.time() - t, 2)
    tnodes = tree(nodes, edges, cats)
    placements = place(rows, previews, nodes, gplacements, cats, tnodes)                          # 5 route
    t = time.time()
    agent = agent_step(placements, tnodes, args.agent_calls, args.agent, args.model)                                      # 6
    timings["agent"] = round(time.time() - t, 2)
    labels = config.data_dir() / DOMAIN / "listings" / "public_match_labels.csv"
    pairs = graph.evaluate(labels, {p["mention_id"]: p for p in gplacements}, nodes) if labels.exists() else None

    OUT.mkdir(parents=True, exist_ok=True)
    tree_list = sorted(tnodes.values(), key=lambda n: n["id"])
    write_jsonl(OUT / "nodes.jsonl", tree_list)
    write_jsonl(OUT / "edges.jsonl", sorted(edges, key=lambda e: (e["type"], e["from"], e["to"])))
    write_jsonl(OUT / "graph-nodes.jsonl", sorted(nodes.values(), key=lambda n: n["id"]))
    write_jsonl(OUT / "placements.jsonl", placements)
    write_jsonl(OUT / "review-queue.jsonl", review)
    n = len(placements)
    steps = Counter(p["step"] for p in placements)
    in_scope = [p for p in placements if p["category"]]
    metrics = {
        "domain": DOMAIN, "listings": n, "in_scope": len(in_scope), "parked_out_of_scope": n - len(in_scope),
        "rules_sha256": {"categories": cats.digest,
                         "identity": hashlib.sha256(graph.CONFIG_PATH.read_bytes()).hexdigest()},
        "identity_rules_version": cfg["version"],
        "tree": dict(Counter(t["level"] for t in tnodes.values())),
        "tree_status": {lv: dict(Counter(t["status"] for t in tnodes.values() if t["level"] == lv))
                        for lv in ("brand", "type", "product", "variant")},
        "trade_items": sum(1 for x in nodes.values() if x["type"] == "TradeItem"),
        "placement_levels_in_scope": dict(Counter(p["level"] for p in in_scope)),
        "settled_by_step_in_scope": {s: round(c / max(len(in_scope), 1), 3) for s, c in
                                     Counter((p["step"] if p["route"] not in ("agent_title", "agent_evidence")
                                              else "routed") for p in in_scope).items()},
        "steps_all": dict(steps),
        "registry": "skipped: no official electronics catalogue",
        "agent": agent, "checks": checks,
        "pair_evaluation": pairs, "gold": score_gold(placements),
        "seconds": round(time.time() - t0, 1), "timings": timings,
        "tree_sha256": hashlib.sha256(json.dumps(tree_list, sort_keys=True).encode()).hexdigest(),
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    from taxo.core.ledger import Ledger
    Ledger(OUT / "ledger.jsonl").append("pipeline_run", domain=DOMAIN, **{k: metrics[k] for k in (
        "listings", "in_scope", "rules_sha256", "identity_rules_version", "tree", "placement_levels_in_scope",
        "settled_by_step_in_scope", "agent", "checks", "gold", "seconds", "timings", "tree_sha256")},
        pair_eval=(metrics["pair_evaluation"] or {}).get("validation"))
    print(json.dumps({k: metrics[k] for k in ("listings", "in_scope", "tree", "placement_levels_in_scope",
                                              "settled_by_step_in_scope", "agent", "gold")}, indent=1))
    print("checks all passed:", checks["all_passed"])
    if pairs:
        v = pairs["validation"]
        print("benchmark pairs, validation: precision", v["config_precision"], "recall", v["config_recall_resolved"])


if __name__ == "__main__":
    main()
