"""Cars pipeline: SPEC §4 steps over the Mexico used-car scrape, scored on gold when gold exists.

    uv run python -m domains.cars.pipeline                    rules only; routed listings are counted, not sent
    uv run python -m domains.cars.pipeline --agent-calls 5    5 Codex CLI placer calls (20 routed listings each)
    uv run python -m domains.cars.pipeline --sealed           also ONE logged read of sealed gold

Steps (the step that decides a listing's settled node is recorded):
  1 parse     source fields, title, year, trim, km, price, VIN; non-listings (promo cards, placeholders) stop here
  2 brand     make from the structured field and the title (aliases, "General Motors", "Chrysler" as parent company)
  3 registry  catalogue lookup (Autocosmos + brand sites): model, model year and version (unique trim match, gearbox
              tie-break) backed by the catalogue
  4 lattice   marketplace agreement: a model, year or listing-stated version that two independent marketplaces state
  5 route     whatever is stated deeper than steps 2-4 support, or has no make, goes to an agent route
  6 agent     the Codex CLI placer (domains/cars/codex_agents.py), only with --agent-calls > 0; code checks every answer

Tree: make > model > year > version (year before version, as the current adapter orders it; DATA-SPEC §4.1 leaves the
order to the cars owner). Body type is a separate category node (CLASSIFIED_AS), never in an id.
Data: TAXO_DATA_DIR/cars/{listings,taxonomy}.jsonl, gold in TAXO_DATA_DIR/cars/gold/*.yaml. Output: runs/cars/.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from taxo import gold as goldmod, score
from taxo.core import config
from taxo.core.config import RUNS_DIR
from taxo.core.io import read_jsonl

from domains.cars import resolve
from domains.cars.adapter import listing_id   # the same id the adapter gives, so gold joins on it

DOMAIN = "cars"
LEVELS = ["make", "model", "year", "version"]
OURS = {"brand": "make", "model": "model", "model_year": "year", "version": "version"}   # resolver level -> tree level
CHANGED_BY_0_3 = ("make_from_group_title_via_catalogue", "make_rebranded_by_year")
DEFAULT_COST_PER_CALL = 0.004   # USD, an assumption for a placer call with tool use; override with TAXO_COST_PER_CALL




def slug(s) -> str:
    return re.sub(r"[^a-z0-9]+", "-", resolve.fold(str(s or ""))).strip("-") or "x"


def node_ids(r: dict) -> dict[str, tuple[str, list[str]]]:
    """tree level -> (id, path) down to the listing's deepest stated level. Ids come from identity keys only."""
    out = {}
    lvl = r["proposed_level"]
    if lvl not in OURS:
        return out
    make = r["brand"]
    i, path = f"cars/{slug(make)}", [make]
    out["make"] = (i, list(path))
    if lvl in ("model", "model_year", "version"):
        i, path = f"{i}/{slug(r['nameplate'])}", path + [r.get("nameplate_label") or r["nameplate"]]
        out["model"] = (i, list(path))
    if lvl in ("model_year", "version"):
        i, path = f"{i}/{r['model_year']}", path + [str(r["model_year"])]
        out["year"] = (i, list(path))
    if lvl == "version":
        if (r.get("version_support") or "") == "catalogue":
            vk = next(e["normalized"] for e in r["evidence"] if e["claim"] == "version" and e["field"] == "catalogue")
            i = f"{i}/c-{slug(vk)}"
        else:
            i = f"{i}/l-{slug(r['version_key'])}"
        out["version"] = (i, path + [r["version"]])
    return out


def status_of(r: dict, our_level: str) -> str:
    return (r.get("level_support") or {}).get(our_level, "stated").split(":")[0]


def run_steps(results: list[dict], records: list[dict]) -> list[dict]:
    """Turn resolver results into placements with the deciding step and a route."""
    rows = []
    for r, raw in zip(results, records):
        ids = node_ids(r)
        p = {"listing_id": listing_id(raw), "source": r["source"], "title": r["title"], "node_id": None, "path": [],
             "level": "none", "step": "parse", "route": None, "reason": ";".join(r["reason_codes"]),
             "rule_ids": sorted({e["rule"] for e in r["evidence"] if e.get("rule")}),
             "candidate": None, "body_category": r.get("body_category"), "vin": bool(r["dimensions"].get("vin"))}
        if r["outcome"] == "out_of_scope":
            p["reason"] = p["reason"] or "not_a_vehicle_listing"
        elif r["outcome"] in ("conflict", "unmatched") and not ids:
            p.update(step="brand", route="agent_evidence" if r["outcome"] == "conflict" else "agent_search")
        else:
            sup = r["supported_level"]
            tree = OURS[sup]
            p["node_id"], p["path"] = ids[tree]
            p["level"] = tree
            st = status_of(r, sup)
            p["step"] = "brand" if sup == "brand" else "registry" if st == "catalogue" else "lattice"
            prop = r["proposed_level"]
            if prop != sup:
                cid, cpath = ids[OURS[prop]]
                p["candidate"] = {"node_id": cid, "path": cpath, "level": OURS[prop], "status": status_of(r, prop)}
                # model not in the catalogue and not agreed on -> the agent needs a search; otherwise the title
                p["route"] = "agent_search" if status_of(r, "model") == "listing_only" else "agent_title"
            elif "year_conflict" in r["reason_codes"]:
                p["route"] = "agent_evidence"
        rows.append(p)
    return rows


def one_per_listing(results, placements):
    """A Kavak car can appear as a search card and as a feed record with the same Kavak id: one listing, one placement.
    Keep the record that resolves deepest (then the one with more evidence); note the other."""
    order = {lvl: i for i, lvl in enumerate(["none", "make", "model", "year", "version"])}
    best = {}
    for r, p in zip(results, placements):
        k = p["listing_id"]
        score_ = (order[(p["candidate"] or p)["level"]], len(r["evidence"]))
        if k not in best or score_ > best[k][0]:
            best[k] = (score_, r, p, best.get(k, (None, None, None, 0))[3] + (1 if k in best else 0))
        else:
            best[k] = best[k][:3] + (best[k][3] + 1,)
    keep = sorted(best.values(), key=lambda x: x[1]["row"])
    for _, _, p, extra in keep:
        if extra:
            p["also_seen_as"] = extra
    return [x[1] for x in keep], [x[2] for x in keep], sum(x[3] for x in keep)


def build_graph(results: list[dict], placements: list[dict], pack) -> tuple[dict, list[dict]]:
    nodes, edges = {}, []
    for cid, c in pack.cats.items():
        nodes[f"cat/{cid}"] = {"id": f"cat/{cid}", "kind": "category", "level": "category", "name": c["label"],
                               "path": pack.cat_path(cid).split(" / "), "parent_id": f"cat/{c['parent']}" if c["parent"] else None}
    stat = defaultdict(lambda: {"status": Counter(), "families": set(), "names": Counter(), "settled": 0, "candidate": 0,
                                "catalogue": None})
    classified = Counter()
    for r, p in zip(results, placements):
        ids = node_ids(r)
        parent = None
        for lvl in LEVELS:
            if lvl not in ids:
                break
            i, path = ids[lvl]
            ours = {v: k for k, v in OURS.items()}[lvl]
            s = stat[i]
            s["status"][status_of(r, ours)] += 1
            s["families"].add(r["family"])
            s["names"][path[-1]] += 1
            if lvl == "version" and r.get("version_ref"):
                s["catalogue"] = r["version_ref"]
            if i not in nodes:
                nodes[i] = {"id": i, "kind": "identity", "level": lvl, "parent_id": parent}
                if parent:
                    edges.append({"type": f"HAS_{lvl.upper()}", "from": parent, "to": i})
            parent = i
        if p["node_id"]:
            stat[p["node_id"]]["settled"] += 1
            edges.append({"type": "DESCRIBES", "from": p["listing_id"], "to": p["node_id"], "step": p["step"]})
        if p["candidate"]:
            stat[p["candidate"]["node_id"]]["candidate"] += 1
            edges.append({"type": "CANDIDATE_DESCRIBES", "from": p["listing_id"], "to": p["candidate"]["node_id"],
                          "status": p["candidate"]["status"]})
        if ids and r.get("body_category"):
            deepest = ids[OURS[r["proposed_level"]]][0]
            classified[(deepest, r["body_category"])] += 1
    rank = {"catalogue": 3, "marketplace_agreement": 2, "stated": 2, "listing_only": 1}
    for i, s in stat.items():
        best = max(s["status"], key=lambda k: (rank[k], k))
        n = nodes[i]
        n.update({"name": s["names"].most_common(1)[0][0], "status": "candidate" if best == "listing_only" else "supported",
                  "evidence": best, "source_families": sorted(s["families"]), "listings_settled_here": s["settled"],
                  "candidate_listings_here": s["candidate"]})
        if s["catalogue"]:
            n["catalogue_ref"] = s["catalogue"]
    for i, n in nodes.items():
        if n["kind"] == "identity":
            n["path"] = (nodes[n["parent_id"]]["path"] if n["parent_id"] else []) + [n["name"]]
    for (i, cid), c in sorted(classified.items()):
        edges.append({"type": "CLASSIFIED_AS", "from": i, "to": f"cat/{cid}", "listings": c})
    return nodes, edges


def checks(nodes: dict, edges: list[dict], placements: list[dict], results: list[dict]) -> list[dict]:
    out = []

    def check(name, ok, detail=""):
        out.append({"check": name, "ok": bool(ok), "detail": str(detail)})

    lids = [p["listing_id"] for p in placements]
    check("listing ids unique (adapter scheme)", len(lids) == len(set(lids)), f"{len(lids) - len(set(lids))} repeats")
    keys = defaultdict(set)
    for r in results:
        for lvl, (i, _) in node_ids(r).items():
            k = (lvl, r["brand"], r.get("nameplate") if lvl != "make" else None,
                 r.get("model_year") if lvl in ("year", "version") else None,
                 (r.get("version_support") == "catalogue", r.get("version") if r.get("version_support") == "catalogue" else r.get("version_key")) if lvl == "version" else None)
            keys[i].add(k)
    check("no two identity keys share a node id", all(len(v) == 1 for v in keys.values()),
          sum(len(v) > 1 for v in keys.values()))
    want = {"model": "make", "year": "model", "version": "year"}
    bad = [n for n in nodes.values() if n["kind"] == "identity" and n["level"] in want
           and (not n["parent_id"] or nodes[n["parent_id"]]["level"] != want[n["level"]])]
    check("each node's parent is one level up", not bad, len(bad))
    bad = [n for n in nodes.values() if n["kind"] == "identity" and n["parent_id"] and n["status"] == "supported"
           and nodes[n["parent_id"]]["status"] != "supported"]
    check("no supported node under a candidate node", not bad, len(bad))
    dangling = [e for e in edges if e["type"] not in ("DESCRIBES", "CANDIDATE_DESCRIBES") and (e["from"] not in nodes or e["to"] not in nodes)]
    dangling += [e for e in edges if e["type"] in ("DESCRIBES", "CANDIDATE_DESCRIBES") and e["to"] not in nodes]
    check("every edge points at an existing node", not dangling, len(dangling))
    check("settled placements sit on supported nodes (or were placed by a checked agent answer)",
          all(nodes[p["node_id"]]["status"] == "supported" or p["step"] == "agent" for p in placements if p["node_id"]))
    check("candidates are strictly deeper than the settled node",
          all(LEVELS.index(p["candidate"]["level"]) > LEVELS.index(p["level"]) for p in placements if p["candidate"]))
    check("every routed listing names a route and nothing else is routed",
          all((p["route"] is not None) == bool(p["candidate"] or (not p["node_id"] and p["step"] != "parse")
                                               or "year_conflict" in p["reason"]) for p in placements))
    check("no category in any identity id", not any(n["id"].startswith("cars/") and "/vehicles" in n["id"] for n in nodes.values()))
    check("CLASSIFIED_AS goes identity -> category", all(e["to"].startswith("cat/") and e["from"].startswith("cars/")
                                                        for e in edges if e["type"] == "CLASSIFIED_AS"))
    return out


def agent_step(results, placements, nodes, edges, max_calls: int, raw_by_lid: dict, effort: str = "medium") -> dict:
    """SPEC step 6 through the Codex CLI (domains/cars/codex_agents.py): each call takes 20 routed listings, gold-linked
    ones first. Code checks every answer; refused or unanswered listings stay routed. With 0 calls it only counts."""
    routed = [p for p in placements if p["route"]]
    info = {"routed": len(routed), "by_route": dict(Counter(p["route"] for p in routed)), "calls": 0, "accepted": 0}
    if max_calls <= 0:
        info["skipped"] = "--agent-calls 0"
        return info
    from domains.cars import codex_agents
    children = defaultdict(list)
    for e in edges:
        if e["type"].startswith("HAS_"):
            children[e["from"]].append(e["to"])
    for k in children:
        children[k].sort(key=lambda c: (nodes[c].get("status") != "supported", -nodes[c].get("listings_settled_here", 0), c))
    gdir = config.data_dir() / DOMAIN / "gold"
    gold_ids = {g.get("listing_id") for f in sorted(gdir.glob("*.yaml")) for g in (yaml.safe_load(f.read_text(encoding="utf-8")) or [])} if gdir.exists() else set()
    sample = RUNS_DIR / DOMAIN / "gold-r01" / "sample-r01.jsonl"   # the random 50 go next, so silver can be compared
    if sample.exists():
        gold_ids |= {json.loads(l)["listing_id"] for l in sample.read_text(encoding="utf-8").splitlines() if l.strip()}
    # Reuse earlier checked answers where the placer's input is unchanged (same settled node, same candidate):
    # a rule change elsewhere must not re-buy answers that cannot differ.
    reused = {}
    prev = RUNS_DIR / DOMAIN / "placements-r01-placer-rules020.jsonl"
    if prev.exists():
        cur = {p["listing_id"]: p for p in placements if p["route"]}
        for q in read_jsonl(prev):
            p = cur.get(q["listing_id"])
            a = q.get("agent")
            if not p:
                continue
            same = (q.get("agent_input") == [p["node_id"], (p["candidate"] or {}).get("node_id")] if q.get("agent_input")
                    else not any(rc in p["reason"] for rc in CHANGED_BY_0_3))   # 0.2.0 run: only the make fixes moved inputs
            if not (p and a and same):
                continue
            if a["answer"] == "node" and q["node_id"] in nodes:
                reused[p["listing_id"]] = ("node", {"node": nodes[q["node_id"]], "node_id": q["node_id"],
                                                    "confidence": a["confidence"], "reason": a["reason"]})
            elif a["answer"] == "stop":
                reused[p["listing_id"]] = ("stop", {"confidence": a["confidence"], "reason": a["reason"]})
            elif a["answer"] == "new_version" and q["level"] == "version":
                reused[p["listing_id"]] = ("new_version", {"new_version": q["path"][-1], "confidence": a["confidence"],
                                                           "reason": a["reason"]})
    todo = [p for p in placements if p["listing_id"] not in reused]
    res = codex_agents.placer(todo, raw_by_lid, nodes, children, max_calls, effort=effort, gold_first=gold_ids)
    res["answers"].update(reused)
    info.update(res["info"])
    info["reused_unchanged"] = len(reused)
    by_lid = {p["listing_id"]: p for p in placements}
    for lid, (kind, d) in res["answers"].items():
        p = by_lid[lid]
        p["agent_input"] = [p["node_id"], (p["candidate"] or {}).get("node_id")]
        p["agent"] = {"answer": kind, "confidence": d and d.get("confidence"), "reason": d and d.get("reason"),
                      "reused": lid in reused}
        if kind == "stop":
            p.update(route=None, candidate=None, reason=p["reason"] + ";agent:stop")
        elif kind == "node":
            n = d["node"]
            p.update(node_id=d["node_id"], path=n["path"], level=n["level"], step="agent", route=None, candidate=None)
        elif kind == "new_version" and p["level"] == "year":
            nid = f"{p['node_id']}/a-{slug(d['new_version'])}"
            if nid not in nodes:
                nodes[nid] = {"id": nid, "kind": "identity", "level": "version", "parent_id": p["node_id"],
                              "name": d["new_version"], "path": p["path"] + [d["new_version"]], "status": "candidate",
                              "evidence": "agent", "source_families": [p["source"]], "listings_settled_here": 0,
                              "candidate_listings_here": 0}
                edges.append({"type": "HAS_VERSION", "from": p["node_id"], "to": nid})
            nodes[nid]["listings_settled_here"] += 1
            p.update(node_id=nid, path=nodes[nid]["path"], level="version", step="agent", route=None, candidate=None)
        else:
            continue
        info["accepted"] += 1
    # DESCRIBES / CANDIDATE edges follow the final placement
    edges[:] = [e for e in edges if e["type"] not in ("DESCRIBES", "CANDIDATE_DESCRIBES")]
    for p in placements:
        if p["node_id"]:
            edges.append({"type": "DESCRIBES", "from": p["listing_id"], "to": p["node_id"], "step": p["step"]})
        if p["candidate"]:
            edges.append({"type": "CANDIDATE_DESCRIBES", "from": p["listing_id"], "to": p["candidate"]["node_id"],
                          "status": p["candidate"]["status"]})
    return info


def gold_scores(results, placements, resolver_brand, sealed: bool) -> dict:
    gdir = config.data_dir() / DOMAIN / "gold"
    files = sorted(f for f in gdir.glob("*.yaml") if not f.stem.endswith("-second")) if gdir.exists() else []
    if not files:
        return {"status": f"no gold yet (looked in {gdir})"}
    rows = goldmod.read_fixtures(files)
    raw = {r["id"]: r for f in files for r in (yaml.safe_load(f.read_text(encoding="utf-8")) or [])}
    for g in rows:  # the sealed split uses the canonical make so spellings do not move a brand across the split
        g.brand = resolver_brand(g.brand) or g.brand
    gold = goldmod.Gold(rows, RUNS_DIR / DOMAIN / "sealed_reads.jsonl")
    by_lid = {p["listing_id"]: (r, p) for r, p in zip(results, placements)}

    def score_set(gs):
        out = {}
        for which in ("settled", "as_specific_as_possible"):
            rep, missing, ood, prefix_ok = score.Report(), 0, Counter(), {"n": 0, "holds": 0}
            years = {"n": 0, "agree": 0, "missing": 0}
            for g in gs:
                hit = by_lid.get(raw[g.id].get("listing_id"))
                if not hit:
                    missing += 1
                    continue
                r, p = hit
                path = p["path"] if which == "settled" or not p["candidate"] else p["candidate"]["path"]
                if not g.expected_path:   # out of domain
                    ood["right" if not p["node_id"] else "wrong"] += 1
                    continue
                gb = resolver_brand(g.expected_path[0]) or g.brand
                pb = r["brand"] if path else None
                bt = set(resolve.key(gb).split()) | set(resolve.key(g.expected_path[0]).split())
                gpath = [gb] + [str(x) for x in g.expected_path[1:]]
                ppath = [pb] + [str(x) for x in path[1:]] if pb else []
                if len(gpath) >= 3 and g.expect == "accept":
                    # taxo/score.py drops all-digit segments, so the model year is never compared there
                    years["n"] += 1
                    years["agree"] += len(ppath) >= 3 and str(ppath[2]) == str(gpath[2])
                    years["missing"] += len(ppath) < 3
                j = score.judge(pb, ppath, gb, gpath, bt, g.compare, g.expect)
                rep.add(j, g.expect)
                if g.expect == "accept":
                    # DATA-SPEC §5: under compare=prefix anything deeper than the label is not checked, so
                    # "deeper" holds there; taxo/score.py counts it as harm (shared fix requested)
                    ok = j.cls == "exact" or (g.compare == "prefix" and j.cls == "deeper")
                    prefix_ok["n"] += 1
                    prefix_ok["holds"] += ok
            out[which] = {**rep.summary(), "label_holds_dataspec": prefix_ok, "model_year": years, "not_in_run": missing,
                          "out_of_domain": dict(ood)}
        return out

    res = {"files": [f.name for f in files], "rows": len(rows), "dev_rows": len(gold.dev),
           "sealed_brands": len(gold.sealed_brands()), "dev": score_set(gold.dev)}
    if sealed:
        res["sealed"] = score_set(gold.sealed("cars pipeline run"))
        res["sealed_reads_total"] = gold.reads()
    return res


def main() -> None:
    ap = argparse.ArgumentParser(prog="domains.cars.pipeline", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--agent-calls", type=int, default=0, help="Codex CLI placer calls (20 routed listings each)")
    ap.add_argument("--agent-effort", default="medium", help="Codex reasoning effort for the placer")
    ap.add_argument("--sealed", action="store_true", help="also read sealed gold once (logged)")
    ap.add_argument("--out", type=Path, default=RUNS_DIR / DOMAIN)
    a = ap.parse_args()
    t0 = time.time()
    d = config.data_dir() / DOMAIN
    timing = {}
    tick = time.time()

    def lap(name):
        nonlocal tick
        timing[name] = round(time.time() - tick, 3)
        tick = time.time()
    records = list(read_jsonl(d / "listings.jsonl"))
    lap("load")
    results, pack, cat = resolve.resolve_records(records, d / "taxonomy.jsonl")
    lap("parse_brand_registry_lattice")
    placements = run_steps(results, records)
    results, placements, merged = one_per_listing(results, placements)
    lap("route")
    nodes, edges = build_graph(results, placements, pack)
    lap("graph")
    raw_by_lid = {}
    for r in records:
        raw_by_lid.setdefault(listing_id(r), r)
    agent = agent_step(results, placements, nodes, edges, a.agent_calls, raw_by_lid, a.agent_effort)
    lap("agent")
    check_res = checks(nodes, edges, placements, results)
    lap("checks")
    res = resolve.Resolver(pack, cat)

    def canon(b):
        kind, v = res.make_from_value(b)
        return v if kind == "make" else None

    n = len(placements)
    step_c = Counter(p["step"] for p in placements if not p["route"])
    cost = float(os.environ.get("TAXO_COST_PER_CALL", DEFAULT_COST_PER_CALL))
    ident = [x for x in nodes.values() if x["kind"] == "identity"]
    metrics = {
        "domain": DOMAIN, "secs": None, "listings": n, "records": len(records),
        "records_merged": {"n": merged, "why": "same Kavak id seen as a search card and a feed record"},
        "inputs": {"listings_sha256": resolve.sha256_file(d / "listings.jsonl"),
                   "catalogue_sha256": resolve.sha256_file(d / "taxonomy.jsonl"), "rules_sha256": resolve.pack_sha256(),
                   "rules_version": pack.version},
        "settled_by_step": {s: {"n": step_c[s], "share": round(step_c[s] / n, 3)} for s in ("parse", "brand", "registry", "lattice", "agent")},
        "agent_answers_by_step": dict(Counter((p.get("agent") or {}).get("answer") for p in placements if p.get("agent"))),
        "routed": {"n": agent["routed"] - agent["accepted"], "share": round((agent["routed"] - agent["accepted"]) / n, 3),
                   "by_route": agent["by_route"]},
        "deciding_step_incl_routed": dict(Counter(p["step"] for p in placements)),
        "settled_level": dict(Counter(p["level"] for p in placements)),
        "agent": {**agent, "billing": "Codex CLI on the ChatGPT login: no per-call charge; uses plan quota. The USD figure is what API calls would cost at the assumed price.",
                  "cost_per_call_usd_assumed": cost,
                  "cost_estimate_usd": {"this_run": round(agent["calls"] * cost, 2),
                                        "all_routed": round(agent["routed"] * cost, 2),
                                        "per_1k_listings": round(agent["routed"] * cost / n * 1000, 2)}},
        "parse": {"vin_present": sum(p["vin"] for p in placements), "vin_decoded": 0,
                  "note": "VINs are read but not decoded (NHTSA vPIC is a later step)."},
        "nodes": {"by_level": dict(Counter(x["level"] for x in ident)), "by_status": dict(Counter(x["status"] for x in ident)),
                  "categories": sum(1 for x in nodes.values() if x["kind"] == "category")},
        "edges": dict(Counter(e["type"] for e in edges)),
        "checks": f"{sum(c['ok'] for c in check_res)}/{len(check_res)}",
        "gold": gold_scores(results, placements, canon, a.sealed),
    }
    a.out.mkdir(parents=True, exist_ok=True)
    with open(a.out / "placements.jsonl", "w", encoding="utf-8") as f:
        for p in placements:
            f.write(json.dumps(p, ensure_ascii=False, sort_keys=True) + "\n")
    with open(a.out / "nodes.jsonl", "w", encoding="utf-8") as f:
        for i in sorted(nodes):
            f.write(json.dumps(nodes[i], ensure_ascii=False, sort_keys=True) + "\n")
    with open(a.out / "edges.jsonl", "w", encoding="utf-8") as f:
        for e in sorted(edges, key=lambda e: (e["type"], e["from"], e["to"])):
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    (a.out / "checks.json").write_text(json.dumps(check_res, indent=2) + "\n", encoding="utf-8")
    lap("gold_and_write")
    metrics["secs"] = round(time.time() - t0, 1)
    metrics["timing_secs"] = timing
    from taxo.core.ledger import Ledger
    Ledger(RUNS_DIR / DOMAIN / "ledger.jsonl").append(
        "pipeline_run", domain=DOMAIN, rules=metrics["inputs"], timing_secs=timing, secs=metrics["secs"],
        settled_by_step={k: v["n"] for k, v in metrics["settled_by_step"].items()}, routed=metrics["routed"]["n"],
        agent={k: agent.get(k) for k in ("calls", "cached", "sent", "accepted", "reused_unchanged", "tokens", "secs")},
        checks=metrics["checks"])
    (a.out / "metrics.json").write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: metrics[k] for k in ("listings", "settled_by_step", "routed", "settled_level", "nodes", "checks",
                                              "secs")}, indent=1))
    print("agent:", {k: metrics["agent"][k] for k in ("calls", "accepted", "skipped", "cost_estimate_usd") if k in metrics["agent"]})
    print("gold:", json.dumps(metrics["gold"])[:400])
    failed = [c["check"] for c in check_res if not c["ok"]]
    print("checks failed:", failed or "none")


if __name__ == "__main__":
    main()
