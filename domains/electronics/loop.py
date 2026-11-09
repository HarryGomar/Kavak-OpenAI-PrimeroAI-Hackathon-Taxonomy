"""Electronics loop rounds (SPEC §5): validator, disagreements for a person, and scoring on gold.

    uv run python -m domains.electronics.loop validate --round 1 [--fresh 100]
        Codex validator labels, blind, (a) the gold sample and (b) fresh random in-scope listings. It never sees the
        pipeline's answer: its candidate page comes from brands named in the title and rare shared words only.
        Writes runs/electronics/loop-rNN/: validator.jsonl, review.json, review.html (disagreements + a 10% spot
        check of agreements). The page exports gold/review-rNN.yaml (provenance: review) for TAXO_DATA_DIR.
    uv run python -m domains.electronics.loop score --round 1
        Pipeline and validator on dev gold (taxo/score.py), validator agreement and the precision of its flags.

Run `python -m domains.electronics.pipeline` first: the loop reads runs/electronics/{placements,nodes}.jsonl.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json

import yaml

from domains.electronics.pipeline import OUT, _words, add_type, brand_of, candidates_for, load
from taxo import gold as goldmod, score
from taxo.core import config
from taxo.lattice.vocab import tokens as vtokens
from taxo.roles import codex_placer
from taxo.core.ledger import Ledger
import time
from domains.electronics.classify import Categories

CATS = Categories()

DOMAIN = "electronics"


def read_jsonl(path):
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def norm(path):
    return [codex_placer.alnum(x) for x in path]


def answer_path(d, tnodes, category):
    """Brand / product type / model / variant. A brand-level answer gets the listing's product type."""
    a = d.get("action")
    if a == "park" or d.get("node_id") not in tnodes:
        return []
    n = tnodes[d["node_id"]]
    if n["level"] == "brand":
        n = tnodes[add_type(tnodes, n["id"], category, CATS)]
    return n["path"] + [d["new_product"].strip()] if a == "new_product" and d.get("new_product") else n["path"]


def relation(p, v):
    a, b = norm(p), norm(v)
    if a == b:
        return "same"
    if not a or not b:
        return "one_parks"
    if a[0] != b[0]:
        return "different_brand"
    k = min(len(a), len(b))
    return "depth" if a[:k] == b[:k] else "different_product"


def vdir(rnd, ver):
    return OUT / (f"loop-r{rnd:02}" if ver == 1 else f"loop-r{rnd:02}-v{ver}")


def validate(rnd, fresh_n, ver=1):
    t_start = time.time()
    ledger = Ledger(OUT / "ledger.jsonl")
    rows, _ = load()
    placements = {p["listing_id"]: p for p in read_jsonl(OUT / "placements.jsonl")}
    tnodes = {n["id"]: n for n in read_jsonl(OUT / "nodes.jsonl")}
    by_brand = {}
    for n in tnodes.values():
        if n["level"] != "brand":
            by_brand.setdefault(brand_of(n, tnodes), []).append(n)
    gold_sample = json.loads((OUT / "gold-round-01" / "sample.json").read_text())["cases"]
    gold_ids = [c["listing_id"] for c in gold_sample]
    seen_path = config.data_dir() / DOMAIN / "seen.txt"
    seen = set(seen_path.read_text().split()) if seen_path.exists() else set()
    frame = [k for k, p in placements.items() if p["category"] and k not in seen and k not in gold_ids]
    fresh = sorted(frame, key=lambda k: hashlib.sha256(f"loop-r{rnd}|{k}".encode()).hexdigest())[:fresh_n]
    items, kind = [], {}
    for k in gold_ids + fresh:
        r = rows[k]
        blind = {"node_id": None, "title": r["title"]}          # never the pipeline's node
        if ver >= 2 and r.get("brand_manufacturer"):            # v2: the listing's own brand field is evidence
            bk = codex_placer.alnum(r["brand_manufacturer"])
            hit = next((n for n in tnodes.values() if n["level"] == "brand" and codex_placer.alnum(n["name"]) == bk), None)
            if hit:
                blind = {"node_id": hit["id"], "title": r["title"]}
        ev = " | ".join(f"{f}: {r[f]}" for f in ("title", "brand_manufacturer", "manufacturer_model", "source_category",
                                                  "price_raw") if r.get(f))
        evidence = r["title"] + " " + (r.get("manufacturer_model") or "")
        if ver >= 3:                                            # v3: rank candidates on title + model field
            blind = {**blind, "title": evidence}
        items.append({"listing_id": k, "title": r["title"], "evidence": evidence if ver >= 3 else r["title"],
                      "brand_id": None, "text": ev, "candidates": candidates_for(blind, tnodes, by_brand)})
        kind[k] = "gold_sample" if k in gold_ids else "fresh"
    pack = yaml.safe_load((config.DOMAINS_DIR / DOMAIN / "pack.yaml").read_text(encoding="utf-8"))
    answers, stats = codex_placer.run_batches(DOMAIN, pack.get("conventions", ""), items, OUT / "codex-cache",
                                              batch_size=30, workers=6, prompt=codex_placer.VALIDATOR_PROMPTS[ver],
                                              ledger=ledger, role=f"validator_v{ver}")
    out_dir = vdir(rnd, ver)
    out_dir.mkdir(parents=True, exist_ok=True)
    log, review = [], []
    rel_counts = Counter()
    for it in items:
        k = it["listing_id"]
        d = answers.get(k)
        if not d:
            continue
        ok, why = codex_placer.place_checked(d, it, tnodes, None)
        vpath = answer_path(d, tnodes, placements[k]["category"]) if ok else []
        ppath = placements[k]["path"]
        rel = relation(ppath, vpath) if ok else "validator_rejected"
        rel_counts[(kind[k], rel)] += 1
        rec = {"listing_id": k, "set": kind[k], "title": it["title"], "pipeline_path": ppath,
               "pipeline_step": placements[k]["step"], "validator": d, "validator_path": vpath, "check": why,
               "relation": rel}
        log.append(rec)
        spot = int(hashlib.sha256(f"spot|{rnd}|{k}".encode()).hexdigest(), 16) % 10 == 0
        if kind[k] == "fresh" and (rel != "same" or spot):
            r = rows[k]
            cat = placements[k]["category"]
            review.append({**rec, "spot_check": rel == "same", "category_path": CATS.path(cat) if cat else "",
                           "fields": {f: r[f] for f in (
                "brand_manufacturer", "manufacturer_model", "source_category", "price_raw", "merchant") if r.get(f)}})
    (out_dir / "validator.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in log))
    (out_dir / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=1))
    page = REVIEW_PAGE.replace("__DATA__", json.dumps({"round": rnd, "cases": review}).replace("</", "<\\/"))
    (out_dir / "review.html").write_text(page, encoding="utf-8")
    summary = {"round": rnd, "validator": ver, **stats, "labelled": len(log), "seconds_total": round(time.time() - t_start, 1),
               "relations": {f"{a}:{b}": n for (a, b), n in sorted(rel_counts.items())},
               "to_review": len(review), "spot_checks": sum(r["spot_check"] for r in review)}
    (out_dir / "validate-summary.json").write_text(json.dumps(summary, indent=2))
    ledger.append("validate_run", domain=DOMAIN, **{k: v for k, v in summary.items()})
    print(json.dumps(summary, indent=1))
    print("review page:", out_dir / "review.html")


def gold_rows():
    gdir = config.data_dir() / DOMAIN / "gold"
    files = sorted(gdir.glob("*.yaml")) if gdir.exists() else []
    lid = {}
    for f in files:
        for r in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
            lid[r["id"]] = r["listing_id"]
    rows = [r for r in goldmod.read_fixtures(files) if r.expected_path and r.brand != "(none)"
            and not (len(r.expected_path) == 1 and len(r.expected_path[0].split()) > 2)]   # a note, not a path
    return rows, lid, files


def score_round(rnd, ver=1):
    ledger = Ledger(OUT / "ledger.jsonl")
    rows, lid, files = gold_rows()
    if not rows:
        print("no gold yet: label gold-round-01 and/or the review page, save the YAML in", config.data_dir() / DOMAIN / "gold")
        return
    g = goldmod.Gold(rows, OUT / "sealed-reads.jsonl")
    placements = {p["listing_id"]: p for p in read_jsonl(OUT / "placements.jsonl")}
    vlog = {x["listing_id"]: x for x in read_jsonl(vdir(rnd, ver) / "validator.jsonl")}
    tl = type_labels()
    ppaths = {k: p["path"] for k, p in placements.items()}
    vpaths = {k: x["validator_path"] for k, x in vlog.items()}
    dev = [r for r in g.dev if r.expect == "accept"]
    reps = {"pipeline": judge_rows(dev, lid, ppaths, tl),
            "validator": judge_rows([r for r in dev if lid[r.id] in vlog], lid, vpaths, tl)}
    flags = Counter()
    for r in dev:
        k = lid[r.id]
        if k in vlog:
            pipeline_ok = ejudge(ppaths.get(k, []), r.expected_path, tl) in ("exact", "shallower")
            disagree = vlog[k]["relation"] != "same"
            flags[("flag" if disagree else "agree", "pipeline_ok" if pipeline_ok else "pipeline_wrong")] += 1
    fl = flags[("flag", "pipeline_wrong")]
    res = {"round": rnd, "validator": ver, "gold_files": [f.name for f in files], "dev_rows": len(g.dev),
           "sealed_brands": len(g.sealed_brands()),
           "pipeline": reps["pipeline"], "validator": reps["validator"],
           "validator_flags": {f"{a}/{b}": n for (a, b), n in flags.items()},
           "validator_flag_precision": round(fl / max(1, fl + flags[("flag", "pipeline_ok")]), 3),
           "validator_missed_errors": flags[("agree", "pipeline_wrong")]}
    (vdir(rnd, ver) / "score.json").write_text(json.dumps(res, indent=2))
    ledger.append("score", domain=DOMAIN, **res)
    print(json.dumps(res, indent=1))


def gold_page(rnd):
    """One-click gold page for the blind random sample: each listing gets 3-6 candidate paths in a shuffled order with
    no source shown (pipeline, validator, their brand-only prefixes, other candidates of the named brand), plus
    "can't tell" and a free-text fallback. Exports gold/round-NN.yaml (provenance: blind_random_choice)."""
    rows, _ = load()
    placements = {p["listing_id"]: p for p in read_jsonl(OUT / "placements.jsonl")}
    tnodes = {n["id"]: n for n in read_jsonl(OUT / "nodes.jsonl")}
    vlog = {x["listing_id"]: x for x in read_jsonl(OUT / f"loop-r{rnd:02}" / "validator.jsonl")}
    by_brand = {}
    for n in tnodes.values():
        if n["level"] != "brand":
            by_brand.setdefault(brand_of(n, tnodes), []).append(n)
    sample = json.loads((OUT / f"gold-round-{rnd:02}" / "sample.json").read_text())
    cases = []
    for c in sample["cases"]:
        k = c["listing_id"]
        opts = [placements[k]["path"], vlog.get(k, {}).get("validator_path") or []]
        opts += [o[:1] for o in opts if len(o) > 1]
        for n in candidates_for({"node_id": None, "title": c["title"]}, tnodes, by_brand, k=6)[:6]:
            opts.append(n["path"])
        seen, uniq = set(), []
        for o in opts:
            key = tuple(norm(o))
            if o and key not in seen:
                seen.add(key)
                uniq.append(o)
        uniq = uniq[:6]
        uniq.sort(key=lambda o: hashlib.sha256(f"opt|{k}|{'/'.join(o)}".encode()).hexdigest())
        cases.append({**c, "options": uniq})
    out = OUT / f"gold-round-{rnd:02}" / "labeling-quick.html"
    out.write_text(QUICK_PAGE.replace("__DATA__", json.dumps({"round": rnd, "seed": sample["seed"], "frame": sample["frame"],
                                                              "cases": cases}).replace("</", "<\\/")), encoding="utf-8")
    print("quick gold page:", out, "| options per case:", Counter(len(c["options"]) for c in cases))


QUICK_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Electronics Gold</title><style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#deddd8;--accent:#2f5fd0;--ok:#1f7a4a}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecebe6;--muted:#a09f99;--line:#34342f;--accent:#7ea0ff;--ok:#5fc58f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;z-index:2}
header h1{font-size:16px;margin:0 8px 0 0}.meta{color:var(--muted);font-size:12px}
button{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:6px;padding:5px 10px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}main{max-width:900px;margin:0 auto;padding:16px}
.case{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:10px}.case.done{border-left:4px solid var(--ok)}
.title{font-weight:600;overflow-wrap:anywhere}.opts{display:flex;flex-direction:column;gap:4px;margin-top:8px}
.opts label{border:1px solid var(--line);border-radius:6px;padding:5px 9px;cursor:pointer;font-size:14px}
.opts label:has(input:checked){border-color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,transparent)}
input[type=text]{font:inherit;width:100%;padding:5px 7px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);margin-top:4px}
</style></head><body>
<header><h1>Electronics gold: one click each</h1><span id="prog" class="meta"></span><span style="flex:1"></span>
<label class="meta">Name <input id="who" type="text" style="width:100px;margin:0"></label><button id="export" class="primary">Export gold YAML</button></header>
<main><p class="meta">Random listings. Click the path that matches what the listing itself sells, as deep as its words support (Brand / product model / colour or capacity). Options come from several sources in a shuffled order; none is marked as the answer. If none fits, pick "Other" and type the path.</p><div id="cases"></div></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);const KEY='quickgold:electronics:r'+D.round;let S={};try{S=JSON.parse(localStorage.getItem(KEY)||'{}')||{}}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}prog()};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function prog(){const n=D.cases.filter(c=>(S[c.listing_id]||{}).v!=null).length;document.getElementById('prog').textContent=n+' / '+D.cases.length+' done';D.cases.forEach((c,i)=>document.getElementById('c'+i).classList.toggle('done',(S[c.listing_id]||{}).v!=null));}
D.cases.forEach((c,i)=>{const el=document.createElement('section');el.className='case';el.id='c'+i;
 const f=[c.source,c.brand_field&&('brand: '+c.brand_field),c.model_field&&('model: '+c.model_field),c.source_category].filter(Boolean).map(esc).join(' · ');
 el.innerHTML=`<div class="meta">#${c.n} · ${f}</div><div class="title">${esc(c.title)}</div><div class="opts">${c.options.map((o,j)=>`<label><input type="radio" name="o${i}" value="${j}"> ${esc(o.join(' / '))}</label>`).join('')}
 <label><input type="radio" name="o${i}" value="none"> Can't tell / not an electronics product</label><label><input type="radio" name="o${i}" value="other"> Other: <input type="text" data-f="other" placeholder="Brand / product / variant"></label></div>`;
 document.getElementById('cases').appendChild(el);const s=S[c.listing_id]||{};
 el.querySelectorAll('input[type=radio]').forEach(r=>r.checked=r.value===s.v);const t=el.querySelector('[data-f]');t.value=s.other||'';
 el.addEventListener('input',e=>{const st=(S[c.listing_id]||={});if(e.target.type==='radio')st.v=e.target.value;else{st.other=e.target.value;st.v='other';el.querySelector('input[value=other]').checked=true;}save();});});
const q=s=>JSON.stringify(String(s));
document.getElementById('export').addEventListener('click',()=>{const who=document.getElementById('who').value.trim()||'diego';const today=new Date().toISOString().slice(0,10);
 let y='# Electronics gold round '+String(D.round).padStart(2,'0')+': random sample (seed '+D.seed+', frame '+D.frame+'), labelled by a person choosing among unlabelled shuffled options.\n';let i=0;
 D.cases.forEach(c=>{const s=S[c.listing_id]||{};if(s.v==null)return;i++;const id='gold-electronics-r'+String(D.round).padStart(2,'0')+'-'+String(i).padStart(4,'0');
  const path=s.v==='none'?[]:s.v==='other'?(s.other||'').split('/').map(x=>x.trim()).filter(Boolean):c.options[+s.v];
  y+=`\n- id: ${id}\n  listing_id: ${q(c.listing_id)}\n  title: ${q(c.title)}\n  source: ${q(c.source)}\n  brand: ${q(path.length?path[0].toLowerCase():'(none)')}\n  expected_path: [${path.map(q).join(', ')}]\n  compare: exact\n  expect: accept\n  why: ""\n  labelled_by: ${q(who)}\n  labelled_at: ${today}\n  provenance: blind_random_choice\n`;});
 const b=new Blob([y],{type:'text/yaml'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='round-'+String(D.round).padStart(2,'0')+'.yaml';a.click();});
prog();
</script></body></html>"""


def ejudge(pred, gold, type_labels):
    """Electronics judge. Paths compared as normalised segments; the product-type level is scored apart (gold from the
    review page may lack it). Classes: exact | shallower (pred is a prefix) | deeper | wrong | wrong_brand | no_brand."""
    def strip(p):
        p = [codex_placer.alnum(x) for x in p]
        return [x for i, x in enumerate(p) if not (i == 1 and x in type_labels)]
    P, G = strip(pred), strip(gold)
    if not P:
        return "no_brand" if G else "exact"
    if not G:
        return "wrong"
    if P[0] != G[0]:
        return "wrong_brand"
    if P == G or "".join(P[1:]) == "".join(G[1:]):      # same product, boundary between levels may differ
        return "exact"
    jp, jg = "".join(P[1:]), "".join(G[1:])
    if jg.startswith(jp):
        return "shallower"
    if jp.startswith(jg):
        return "deeper"
    return "wrong"


def judge_rows(rows, lid, paths, type_labels):
    c = Counter()
    for r in rows:
        if r.expect != "accept":
            continue
        c[ejudge(paths.get(lid[r.id], []), r.expected_path, type_labels)] += 1
    n = sum(c.values()) or 1
    return {"rows": sum(c.values()), **dict(c), "exact_rate": round(c["exact"] / n, 3),
            "right_or_shallower": round((c["exact"] + c["shallower"]) / n, 3),
            "harm_rate": round((c["deeper"] + c["wrong"] + c["wrong_brand"]) / n, 3)}


def type_labels():
    return {codex_placer.alnum(c["label"]) for c in CATS.categories.values()}


def rules_only(cfg):
    """Steps 1-5 with an identity config; no agent. Returns ({listing_id: path}, graph placements, nodes)."""
    from domains.electronics import graph
    from domains.electronics.pipeline import place, tree
    rows, _ = load()
    prev = {k: CATS.categorize(r) for k, r in rows.items()}
    nodes, edges, gp, _, _, checks = graph.construct(rows, list(prev.values()), CATS, cfg)
    t = tree(nodes, edges, CATS)
    pl = place(rows, prev, nodes, gp, CATS, t)
    return {p["listing_id"]: p["path"] for p in pl}, gp, nodes, checks


def gate(change, base_ref="HEAD"):
    """Keep a rule change only if, rules-only, it does not lose on dev (gold dev + benchmark train pairs) and wins on
    something; then ONE logged read of sealed (gold sealed brands + benchmark validation pairs) must agree."""
    import subprocess
    from domains.electronics import graph
    ledger = Ledger(OUT / "ledger.jsonl")
    t0 = time.time()
    base_cfg = yaml.safe_load(subprocess.run(["git", "show", f"{base_ref}:domains/electronics/identity.yaml"],
                                             capture_output=True, text=True, check=True).stdout)
    new_cfg = graph.read_yaml(graph.CONFIG_PATH)
    rows, lid, _ = gold_rows()
    g = goldmod.Gold(rows, OUT / "sealed-reads.jsonl")
    tl = type_labels()
    labels = config.data_dir() / DOMAIN / "listings" / "public_match_labels.csv"
    res = {}
    for name, cfg in (("base", base_cfg), ("new", new_cfg)):
        paths, gp, nodes, checks = rules_only(cfg)
        pairs = graph.evaluate(labels, {p["mention_id"]: p for p in gp}, nodes)
        res[name] = {"identity_version": cfg["version"], "checks_pass": checks["all_passed"], "paths": paths,
                     "dev_gold": judge_rows(g.dev, lid, paths, tl),
                     "dev_pairs": {k: pairs["train"][k] for k in ("config_precision", "config_recall_resolved",
                                                                  "recall_all_in_scope_matches")},
                     "_pairs": pairs}
    b, n = res["base"], res["new"]
    changed = sum(1 for k in n["paths"] if n["paths"][k] != b["paths"].get(k))

    def better(x, y, gk, pk):
        no_loss = (x[gk]["exact_rate"] >= y[gk]["exact_rate"] and x[gk]["harm_rate"] <= y[gk]["harm_rate"]
                   and (x[pk]["config_precision"] or 0) >= (y[pk]["config_precision"] or 0) - 0.005)
        win = (x[gk]["exact_rate"] > y[gk]["exact_rate"] or x[gk]["harm_rate"] < y[gk]["harm_rate"]
               or (x[pk]["config_recall_resolved"] or 0) > (y[pk]["config_recall_resolved"] or 0) + 0.002
               or (x[pk]["recall_all_in_scope_matches"] or 0) > (y[pk]["recall_all_in_scope_matches"] or 0) + 0.002)
        return no_loss, win

    dev_ok, dev_win = better(n, b, "dev_gold", "dev_pairs")
    decision, sealed = "drop (dev)", None
    if dev_ok and dev_win and n["checks_pass"]:
        srows = g.sealed(purpose=f"gate:{change}")
        for x in (b, n):
            x["sealed_gold"] = judge_rows(srows, lid, x["paths"], tl)
            x["sealed_pairs"] = {k: x["_pairs"]["validation"][k] for k in ("config_precision", "config_recall_resolved",
                                                                          "recall_all_in_scope_matches")}
        s_ok, _ = better(n, b, "sealed_gold", "sealed_pairs")
        decision = "keep" if s_ok else "drop (sealed)"
        sealed = {"rows": len(srows), "base_gold": b["sealed_gold"], "new_gold": n["sealed_gold"],
                  "base_pairs": b["sealed_pairs"], "new_pairs": n["sealed_pairs"]}
    out = {"change": change, "decision": decision, "listings_changed": changed, "seconds": round(time.time() - t0, 1),
           "base": {k: v for k, v in b.items() if not k.startswith("_") and k != "paths"},
           "new": {k: v for k, v in n.items() if not k.startswith("_") and k != "paths"},
           "sealed": sealed, "sealed_reads_total": g.reads()}
    ledger.append("gate", domain=DOMAIN, **out)
    (OUT / "gates").mkdir(exist_ok=True)
    (OUT / "gates" / f"{int(time.time())}-{change}.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out, indent=1))


REVIEW_PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Electronics Review</title><style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#deddd8;--accent:#2f5fd0;--ok:#1f7a4a}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecebe6;--muted:#a09f99;--line:#34342f;--accent:#7ea0ff;--ok:#5fc58f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;z-index:2}
header h1{font-size:16px;margin:0 8px 0 0}.meta{color:var(--muted);font-size:12px}
button{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:6px;padding:5px 10px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
main{max-width:980px;margin:0 auto;padding:16px}
.case{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:12px}
.case.done{border-left:4px solid var(--ok)}.title{font-weight:600;overflow-wrap:anywhere}
.ans{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0}@media (max-width:700px){.ans{grid-template-columns:1fr}}
.box{border:1px solid var(--line);border-radius:6px;padding:8px}.box b{display:block;font-size:12px;color:var(--muted)}
.row{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0}.cat{font-size:13px;margin-top:4px}.lv{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}.row label{border:1px solid var(--line);border-radius:6px;padding:4px 9px;cursor:pointer;font-size:13px}
input[type=text]{font:inherit;width:100%;padding:5px 7px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink)}
</style></head><body>
<header><h1>Review: two answers disagree</h1><span id="prog" class="meta"></span><span style="flex:1"></span>
<label class="meta">Your name <input id="who" type="text" style="width:110px"></label><button id="export" class="primary">Export gold YAML</button></header>
<main><p class="meta">For each listing, two independent answers (A and B, in random order). Pick the right one, or type the right path if both are wrong. A path is Brand › Model (the manufacturer's model or part number, which identifies the exact product) › Variant (colour or capacity, only if that model comes in several). The product type is shown separately: it is a browse category, not part of the path. Stop where the listing's own words stop. Some cases are random checks where A and B agree.</p><div id="cases"></div></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);const KEY='review:electronics:r'+D.round;let S={};try{S=JSON.parse(localStorage.getItem(KEY)||'{}')||{}}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}prog()};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const h=s=>{let x=0;for(const c of s)x=(x*31+c.charCodeAt(0))>>>0;return x};
const LV=['Brand','Model','Variant'];const P=p=>p&&p.length?p.map((x,j)=>`<span class="lv">${LV[j]||''}</span> ${esc(x)}`).join(' &rsaquo; '):'(no placement: can\'t tell)';
function prog(){const n=D.cases.filter(c=>(S[c.listing_id]||{}).v).length;document.getElementById('prog').textContent=n+' / '+D.cases.length+' reviewed';D.cases.forEach((c,i)=>document.getElementById('c'+i).classList.toggle('done',!!(S[c.listing_id]||{}).v));}
D.cases.forEach((c,i)=>{const flip=h(c.listing_id)%2===1;c.A=flip?'validator':'pipeline';c.B=flip?'pipeline':'validator';
 const path=w=>w==='pipeline'?c.pipeline_path:c.validator_path;const el=document.createElement('section');el.className='case';el.id='c'+i;
 const f=Object.entries(c.fields||{}).map(([k,v])=>`${esc(k)}: ${esc(v)}`).join(' · ');
 el.innerHTML=`<div class="meta">${esc(c.listing_id)}</div><div class="title">${esc(c.title)}</div><div class="meta">${f}</div>
 <div class="cat">Product type: <b>${esc((c.category_path||'').replace(/^Electronics \/ /,''))}</b></div>
 <div class="ans"><div class="box"><b>Answer A</b>${P(path(c.A))}</div><div class="box"><b>Answer B</b>${P(path(c.B))}</div></div>
 <div class="row">${[['A','A is right'],['B','B is right'],['both','Both wrong'],['unclear','Can\'t tell']].map(([v,l])=>`<label><input type="radio" name="v${i}" value="${v}"> ${l}</label>`).join('')}</div>
 <input type="text" data-f="path" placeholder="If both wrong: Brand / product / variant"><input type="text" data-f="why" placeholder="Why (optional)" style="margin-top:6px">`;
 document.getElementById('cases').appendChild(el);const s=S[c.listing_id]||{};
 el.querySelectorAll('input[type=radio]').forEach(r=>{r.checked=r.value===s.v;});el.querySelectorAll('[data-f]').forEach(x=>x.value=s[x.dataset.f]||'');
 el.addEventListener('input',e=>{const t=e.target;const st=(S[c.listing_id]||={});if(t.type==='radio')st.v=t.value;else st[t.dataset.f]=t.value;save();});});
const q=s=>JSON.stringify(String(s));
document.getElementById('export').addEventListener('click',()=>{const who=document.getElementById('who').value.trim()||'diego';const today=new Date().toISOString().slice(0,10);
 let y='# Electronics review round '+D.round+': a person settled disagreements between the pipeline and the validator.\n';let i=0;
 D.cases.forEach(c=>{const s=S[c.listing_id]||{};if(!s.v)return;const right=s.v==='A'?c.A:s.v==='B'?c.B:null;
  const verdict=s.v==='both'?'both_wrong':s.v==='unclear'?'unclear':(right==='pipeline'?'pipeline_right':'validator_right');
  let path=right==='pipeline'?c.pipeline_path:right==='validator'?c.validator_path:(s.path||'').split('/').map(x=>x.trim()).filter(Boolean);
  if(verdict==='unclear'||!path.length)return;i++;
  y+=`\n- id: gold-electronics-rev${String(D.round).padStart(2,'0')}-${String(i).padStart(4,'0')}\n  listing_id: ${q(c.listing_id)}\n  title: ${q(c.title)}\n  brand: ${q(path[0].toLowerCase())}\n  expected_path: [${path.map(q).join(', ')}]\n  compare: exact\n  expect: accept\n  why: ${q(s.why||'')}\n  review_verdict: ${verdict}\n  spot_check: ${c.spot_check}\n  labelled_by: ${q(who)}\n  labelled_at: ${today}\n  provenance: review\n`;});
 const b=new Blob([y],{type:'text/yaml'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='review-r'+String(D.round).padStart(2,'0')+'.yaml';a.click();});
prog();
</script></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--round", type=int, default=1)
    v.add_argument("--fresh", type=int, default=100)
    v.add_argument("--validator", type=int, default=1, help="validator prompt version (codex_placer.VALIDATOR_PROMPTS)")
    s = sub.add_parser("score")
    s.add_argument("--round", type=int, default=1)
    s.add_argument("--validator", type=int, default=1)
    gt = sub.add_parser("gate")
    gt.add_argument("change", help="short name of the rule change being gated")
    gt.add_argument("--base", default="HEAD")
    gp = sub.add_parser("gold-page")
    gp.add_argument("--round", type=int, default=1)
    a = ap.parse_args()
    {"validate": lambda: validate(a.round, a.fresh, a.validator), "score": lambda: score_round(a.round, a.validator),
     "gold-page": lambda: gold_page(a.round), "gate": lambda: gate(a.change, a.base)}[a.cmd]()
