"""Cars loop rounds (SPEC §5): blind validator, disagreements for a person, scoring on gold, round record.

    uv run python -m domains.cars.loop validate --round 1 [--fresh 100]
        The Codex validator (domains/cars/codex_agents.py) labels BLIND make > model > year > version from the listing's
        full fields only: no candidate page, no pipeline answer. Sets: (a) the blind random gold sample
        (runs/cars/gold-r01/sample-r01.jsonl) and (b) --fresh random listings outside that sample and earlier reviews.
        Compared with the pipeline's final answer (runs/cars/placements.jsonl). Writes runs/cars/loop-rNN/:
        validator.jsonl, review.json and review.html (every disagreement + a random 10% of agreements, answers shown
        as A/B in random order). The page exports review-rNN.yaml (provenance: review) for TAXO_DATA_DIR/cars/gold/.
    uv run python -m domains.cars.loop score --round 1
        Pipeline and validator on dev gold (taxo/score.py, plus the DATA-SPEC prefix and model-year checks),
        validator agreement with the pipeline, and the precision of its flags where gold exists.
    uv run python -m domains.cars.loop record --round 1
        rounds/cars/round-NN.md, rounds/cars/round-NN-decisions.csv (no titles, URLs or prices: the repo is public)
        and one memory/record.jsonl line.

Run `python -m domains.cars.pipeline --agent-calls N` first.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import random

import yaml

from taxo import gold as goldmod, score
from taxo.core import config
from taxo.core.config import ROOT, RUNS_DIR
from taxo.core.io import read_jsonl

from domains.cars import codex_agents, resolve
from domains.cars.adapter import listing_id

DOMAIN = "cars"
OUT = RUNS_DIR / DOMAIN


def load_raw() -> dict:
    raw = {}
    for r in read_jsonl(config.data_dir() / DOMAIN / "listings.jsonl"):
        raw.setdefault(listing_id(r), r)
    return raw


def gold_rows() -> tuple[list, dict]:
    gdir = config.data_dir() / DOMAIN / "gold"
    files = sorted(f for f in gdir.glob("*.yaml") if not f.stem.endswith("-second")) if gdir.exists() else []
    raw = {}
    for f in files:
        for g in yaml.safe_load(f.read_text(encoding="utf-8")) or []:
            raw[g["id"]] = g | {"_file": f.name}
    return files, raw


def final_path(p: dict) -> list[str]:
    """The pipeline's answer as it stands: the agent's node, or the deepest stated candidate, else the settled node."""
    if p.get("candidate"):
        return p["candidate"]["path"]
    return p["path"]


def val_path(v: dict) -> list[str]:
    if not v or v.get("out_of_domain"):
        return []
    out = []
    for x in (v.get("make"), v.get("model"), v.get("year"), v.get("version")):
        if x in (None, ""):
            break
        out.append(str(x))
    return out


def display_path(path: list[str]) -> list[str]:
    """Display form for the A/B page: one canonical make name, so neither answer gives its source away."""
    if not path:
        return []
    mk = codex_agents.canon_make(path[0])
    name = {"mg": "MG", "bmw": "BMW", "gmc": "GMC", "byd": "BYD", "jac": "JAC", "gwm": "GWM", "mini": "MINI"}.get(mk)
    return [name or str(path[0]).replace("-", " ").title() if codex_agents.canon_make(str(path[0]).replace("-", " ").title()) == mk
            else str(path[0])] + [str(x) for x in path[1:]]


def disagrees(v: dict, path: list[str]) -> bool:
    if not v:
        return False
    if v.get("out_of_domain") or not path:
        return bool(v.get("out_of_domain")) != (not path)
    return "disagree" in codex_agents.compare(v, path).values()


# ------------------------------------------------------------------ validate

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cars Review Round</title><style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#deddd8;--accent:#2f5fd0;--ok:#1f7a4a;--chip:#efeee9}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecebe6;--muted:#a09f99;--line:#34342f;--accent:#7ea0ff;--ok:#5fc58f;--chip:#2a2a27}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;z-index:2}
header h1{font-size:16px;margin:0}.meta{color:var(--muted);font-size:12px}main{max-width:1050px;margin:0 auto;padding:16px}
button{font:inherit;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:6px;padding:5px 10px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
input,textarea{font:inherit;font-size:14px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 7px;width:100%}
.case{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:14px}.case.done{border-left:4px solid var(--ok)}
.title{font-size:16px;font-weight:600;overflow-wrap:anywhere}.chip{background:var(--chip);border-radius:999px;padding:1px 8px;font-size:12px;color:var(--muted)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:var(--bg);padding:8px;border-radius:6px;max-height:180px;overflow:auto}
.ab{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:8px 0}.ab div{border:1px solid var(--line);border-radius:6px;padding:8px}
.v{display:flex;flex-wrap:wrap;gap:8px;margin:6px 0}.v label{border:1px solid var(--line);border-radius:6px;padding:4px 9px;cursor:pointer;font-size:13px}
.v label:has(input:checked){border-color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,transparent)}.v input{width:auto;margin-right:4px}
.hidden{display:none}@media(max-width:640px){.ab{grid-template-columns:1fr}}</style></head><body>
<header><h1>Cars review · round __ROUND__</h1><span class="meta" id="prog"></span><span class="meta">Reviewer</span>
<input id="who" style="width:130px"><span style="flex:1"></span><button class="primary" id="export">Export review YAML</button></header>
<main><p class="meta" id="intro"></p><div id="cases"></div></main>
<script id="data" type="application/json">__DATA__</script><script>
(()=>{const D=JSON.parse(document.getElementById('data').textContent),KEY='cars-review:'+D.round+':'+D.sha.slice(0,12);
let st={};try{st=JSON.parse(localStorage.getItem(KEY)||'{}')||{}}catch(e){}st.r=st.r||{};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}prog()};
const who=document.getElementById('who');who.value=st.who||'';who.oninput=()=>{st.who=who.value;save()};
document.getElementById('intro').textContent=D.intro;
const show=p=>p.length?p.map(esc).join(' › '):'<i>not a car listing / nothing placeable</i>';
const prog=()=>{document.getElementById('prog').textContent=Object.values(st.r).filter(v=>v.verdict).length+' / '+D.items.length+' reviewed';
 D.items.forEach(it=>document.getElementById('c-'+it.rid).classList.toggle('done',!!(st.r[it.rid]||{}).verdict))};
const root=document.getElementById('cases');
D.items.forEach((it,i)=>{const el=document.createElement('section');el.className='case';el.id='c-'+it.rid;
 el.innerHTML=`<div class="meta">${i+1}. ${esc(it.rid)} <span class="chip">${esc(it.source)}</span> <span class="chip">${it.kind==='spot'?'spot check':'disagreement'}</span></div>
 <div class="title">${esc(it.title)}</div><div class="meta">${it.url?`<a href="${esc(it.url)}" target="_blank" rel="noopener">open the listing</a> · `:''}${esc(it.listing_id)}</div>
 <pre>${esc(JSON.stringify(it.fields,null,1))}</pre>
 <div class="ab"><div><b>A</b><br>${show(it.A)}</div><div><b>B</b><br>${show(it.B)}</div></div>
 <div class="v">${['A right','B right','both right','both wrong','unclear'].map(x=>`<label><input type="radio" name="v-${it.rid}" value="${x}">${x}</label>`).join('')}</div>
 <input class="hidden fix" data-f="fix" placeholder="correct path: Make > Model > Year > Version (stop where you are sure; empty = not a car listing)">
 <input data-f="why" placeholder="why (one sentence)" style="margin-top:6px">`;root.appendChild(el);
 const fill=()=>{const v=st.r[it.rid]||{};el.querySelectorAll(`[name=v-${it.rid}]`).forEach(x=>x.checked=x.value===v.verdict);
  el.querySelectorAll('[data-f]').forEach(x=>x.value=v[x.dataset.f]||'');el.querySelector('.fix').classList.toggle('hidden',v.verdict!=='both wrong')};
 el.addEventListener('input',e=>{const v=(st.r[it.rid]||={});if(e.target.name===`v-${it.rid}`)v.verdict=e.target.value;else if(e.target.dataset.f)v[e.target.dataset.f]=e.target.value;fill();save()});fill()});
prog();
const q=s=>JSON.stringify(String(s));
document.getElementById('export').onclick=()=>{const name=who.value.trim();if(!name){alert('Write your name first.');return}
 const today=new Date().toISOString().slice(0,10);let y=`# Cars review round ${D.round} by ${name}: verdicts on validator vs pipeline disagreements and a spot check.\n# Written by a person. provenance: review. Source: ${D.file} (sha256 ${D.sha})\n`,n=0;
 const row=(it,path,expect,cmp,why,tag)=>{n++;const brand=path.length?path[0].toLowerCase():'none';
  y+=`\n- id: gold-cars-rev${String(D.round).padStart(2,'0')}-${it.rid}${tag}\n  listing_id: ${q(it.listing_id)}\n  title: ${q(it.title)}\n  source: ${it.source}\n  brand: ${q(brand)}\n  expected_path: [${path.map(q).join(', ')}]\n  compare: ${cmp}\n  expect: ${expect}\n  why: ${q(why)}\n  labelled_by: ${q(name)}\n  labelled_at: ${today}\n  provenance: review\n`};
 for(const it of D.items){const v=st.r[it.rid];if(!v||!v.verdict||v.verdict==='unclear')continue;const why=v.why||v.verdict;
  if(v.verdict==='A right'||v.verdict==='B right'){const good=v.verdict[0]==='A'?it.A:it.B,bad=v.verdict[0]==='A'?it.B:it.A;
   row(it,good,'accept','prefix',why,'');const nz=p=>p.map(x=>String(x).toLowerCase().replace(/[^a-z0-9]/g,'')).join('|');if(bad.length&&nz(bad)!==nz(good))row(it,bad,'reject','exact',why+' (the other answer)','-r')}
  else if(v.verdict==='both right'){const deeper=it.A.length>=it.B.length?it.A:it.B;row(it,deeper,'accept','prefix',why,'')}
  else if(v.verdict==='both wrong'){const fix=(v.fix||'').split('>').map(s=>s.trim()).filter(Boolean);row(it,fix,'accept','prefix',why,'');
   if(it.A.length)row(it,it.A,'reject','exact',why+' (answer A)','-ra');if(it.B.length)row(it,it.B,'reject','exact',why+' (answer B)','-rb')}}
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([y],{type:'text/yaml'}));a.download=`review-r${String(D.round).padStart(2,'0')}.yaml`;a.click();
 setTimeout(()=>URL.revokeObjectURL(a.href),1000);alert(n+' gold rows exported. Save the file in TAXO_DATA_DIR/cars/gold/.')};
})();</script></body></html>"""


def cmd_validate(rnd: int, fresh: int, effort: str, vver: int = 2) -> None:
    from domains.cars.gold_sample import build_title, shown_fields
    raw = load_raw()
    pl = {p["listing_id"]: p for p in read_jsonl(OUT / "placements.jsonl")}
    sample = [json.loads(l)["listing_id"] for l in (OUT / "gold-r01" / "sample-r01.jsonl").read_text().splitlines() if l.strip()]
    _, gold = gold_rows()
    earlier = {g.get("listing_id") for g in gold.values()} | set(sample)
    pool = sorted(l for l in pl if l not in earlier and pl[l]["step"] != "parse")   # parse = not car listings
    fresh_ids = random.Random(f"cars-loop-r{rnd}").sample(pool, fresh)
    imported = sorted({g.get("listing_id") for g in gold.values() if g.get("listing_id") in pl})
    sets = [("gold_sample", sample), ("fresh", fresh_ids), ("gold_imported", imported)]
    labels = codex_agents.validate([(i, raw[i]) for _, ids in sets for i in ids], effort=effort, version=vver)
    stats = labels.pop("_stats")
    out = OUT / f"loop-r{rnd:02d}"
    out.mkdir(parents=True, exist_ok=True)
    rows, items = [], []
    rng = random.Random(f"cars-review-r{rnd}")
    for which, ids in sets:
        for i in ids:
            v, p = labels.get(i), pl[i]
            pp, vp = final_path(p), val_path(labels.get(i))
            dis = disagrees(v, pp) if v else None
            rows.append({"listing_id": i, "set": which, "validator": v, "validator_path": vp, "pipeline_path": pp,
                         "pipeline_step": p["step"], "disagree": dis,
                         "levels": codex_agents.compare(v, pp) if v and vp and pp else None})
            if which == "gold_imported":
                continue                     # already gold: scored, not reviewed again
            if dis or (dis is False and rng.random() < 0.10):
                flip = rng.random() < 0.5
                r = raw[i]
                pp, vp = display_path(pp), display_path(vp)     # same make spelling on both sides: the source must not show
                items.append({"rid": hashlib.sha256(i.encode()).hexdigest()[:8], "listing_id": i, "source": r["_source"],
                              "title": build_title(r), "url": r.get("url"), "fields": shown_fields(r),
                              "kind": "disagreement" if dis else "spot", "A": vp if flip else pp, "B": pp if flip else vp,
                              "A_is": "validator" if flip else "pipeline"})
    for name in (f"validator-v{vver}.jsonl", "validator.jsonl"):     # validator.jsonl = the version reviewed now
        with open(out / name, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r | {"validator_version": vver}, ensure_ascii=False) + "\n")
    (out / "review.json").write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")   # keeps A_is
    sha = hashlib.sha256((out / "review.json").read_bytes()).hexdigest()
    shown = [{k: v for k, v in it.items() if k != "A_is"} for it in items]
    n_dis = sum(it["kind"] == "disagreement" for it in items)
    data = {"round": rnd, "sha": sha, "file": "review.json", "items": shown,
            "intro": f"{n_dis} disagreements between two independent answers and {len(items) - n_dis} spot checks of "
                     f"agreed listings, from {len(rows)} listings ({len(sample)} blind gold sample + {len(fresh_ids)} fresh). "
                     "A and B are in random order; which one is the pipeline is hidden."}
    (out / "review.html").write_text(PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
                                     .replace("__ROUND__", str(rnd)), encoding="utf-8")
    summary = {"round": rnd, "validator_version": vver, "validator_codex": stats, "listings": len(rows), "answered": sum(1 for r in rows if r["validator"]),
               "by_set": {w: dict(Counter("disagree" if r["disagree"] else "agree" if r["disagree"] is False else "no_answer"
                                          for r in rows if r["set"] == w)) for w, _ in sets},
               "disagreement_level": dict(Counter(next((k for k, v in (r["levels"] or {}).items() if v == "disagree"), "scope")
                                                  for r in rows if r["disagree"])),
               "review_items": {"disagreements": n_dis, "spot_checks": len(items) - n_dis}}
    (out / f"summary-v{vver}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=1))


# ------------------------------------------------------------------ score

def cmd_score(rnd: int) -> None:
    files, graw = gold_rows()
    out = OUT / f"loop-r{rnd:02d}"
    pl = {p["listing_id"]: p for p in read_jsonl(OUT / "placements.jsonl")}
    vals = {}
    for f in sorted(out.glob("validator-v*.jsonl")):
        vals[int(f.stem.split("-v")[1])] = {r["listing_id"]: r["validator"] for r in read_jsonl(f) if r.get("validator")}
    if not files:
        res = {"status": "no gold yet"}
    else:
        rows = goldmod.read_fixtures(files)
        for g in rows:
            g.brand = codex_agents.canon_make(g.brand)
        gold = goldmod.Gold(rows, OUT / "sealed_reads.jsonl")
        res = {"files": [f.name for f in files], "dev_rows": len(gold.dev),
               "by_provenance": dict(Counter(graw[g.id].get("provenance", "?").split(":")[0] for g in gold.dev))}
        answers = [("pipeline_settled", None, lambda p, v: p["path"]), ("pipeline_final", None, lambda p, v: final_path(p))]
        answers += [(f"validator_v{k}", k, lambda p, v: val_path(v)) for k in sorted(vals)]
        for name, vk, fn in answers:
            val = vals.get(vk, {})
            rep, holds, years, n, missing = score.Report(), 0, [0, 0], 0, 0
            for g in gold.dev:
                lid = graw[g.id].get("listing_id")
                p, v = pl.get(lid), val.get(lid)
                if not p or (vk is not None and not v):
                    missing += 1
                    continue
                path = fn(p, v)
                gp = [str(x) for x in g.expected_path]
                if not gp:
                    continue
                gb = codex_agents.canon_make(gp[0])
                pb = codex_agents.canon_make(path[0]) if path else None
                bt = set(resolve.key(gp[0]).split()) | {gb}
                j = score.judge(pb, [pb] + path[1:] if pb else [], gb, [gb] + gp[1:], bt, g.compare, g.expect)
                rep.add(j, g.expect)
                if g.expect == "accept":
                    n += 1
                    holds += j.cls == "exact" or (g.compare == "prefix" and j.cls == "deeper")
                    if len(gp) >= 3:
                        years[0] += 1
                        years[1] += len(path) >= 3 and str(path[2]) == gp[2]
            s = rep.summary()
            res[name] = {k: s[k] for k in ("accept_rows", "exact", "shallower", "deeper", "wrong", "wrong_brand", "no_brand",
                                           "reject_rows", "rejects_held")} | {"label_holds_dataspec": f"{holds}/{n}",
                                                                              "model_year": f"{years[1]}/{years[0]}",
                                                                              "not_scored": missing}
        # flags: the validator disagrees with the pipeline; precise when gold says the pipeline was wrong there
        for vk, val in sorted(vals.items()):
          flags = right = 0
          for g in gold.dev:
            lid = graw[g.id].get("listing_id")
            p, v = pl.get(lid), val.get(lid)
            if not (p and v and g.expect == "accept") or not disagrees(v, final_path(p)):
                continue
            flags += 1
            gp = [str(x) for x in g.expected_path]
            right += (not gp and bool(final_path(p))) or (bool(gp) and disagrees(
                {"make": gp[0], "model": gp[1] if len(gp) > 1 else None, "year": gp[2] if len(gp) > 2 else None,
                 "version": gp[3] if len(gp) > 3 else None, "out_of_domain": False}, final_path(p)))
          res[f"validator_v{vk}_flags_on_gold"] = {"flags": flags, "pipeline_really_wrong": right,
                                                   "precision": round(right / flags, 3) if flags else None}
    agree = Counter()
    for r in read_jsonl(out / "validator.jsonl") if (out / "validator.jsonl").exists() else []:
        agree["disagree" if r["disagree"] else "agree" if r["disagree"] is False else "no_answer"] += 1
    res["validator_vs_pipeline_this_round"] = dict(agree)
    (out / "score.json").write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(res, indent=1))


# ------------------------------------------------------------------ record

def ledger_totals() -> dict:
    """Per role: fresh Codex calls, cache hits, seconds and token usage, from runs/cars/ledger.jsonl."""
    out = {}
    path = OUT / "ledger.jsonl"
    for e in read_jsonl(path) if path.exists() else []:
        if e["kind"] != "codex_call":
            continue
        t = out.setdefault(e.get("role", "?"), {"calls": 0, "cache_hits": 0, "seconds": 0.0, "listings": 0, "tokens": {}})
        if e.get("cached"):
            t["cache_hits"] += 1
            continue
        t["calls"] += 1
        t["seconds"] = round(t["seconds"] + (e.get("seconds") or 0), 1)
        t["listings"] += e.get("listings") or 0
        for k, v in (e.get("usage") or {}).items():
            t["tokens"][k] = t["tokens"].get(k, 0) + v
    return out


def cmd_record(rnd: int, label: str) -> None:
    m = json.loads((OUT / "metrics.json").read_text())
    out = OUT / f"loop-r{rnd:02d}"
    rd = lambda n: json.loads((out / n).read_text()) if (out / n).exists() else {}
    v1, v2, sc, gate = rd("summary-v1.json"), rd("summary-v2.json"), rd("score.json"), rd("gate.json")
    full = json.loads((OUT / "metrics-r01-placer-rules020.json").read_text()) if (OUT / "metrics-r01-placer-rules020.json").exists() else {}
    led = ledger_totals()
    rdir = ROOT / "rounds" / DOMAIN
    rdir.mkdir(parents=True, exist_ok=True)
    pl = list(read_jsonl(OUT / "placements.jsonl"))
    val = {r["listing_id"]: r for r in read_jsonl(out / "validator.jsonl")} if (out / "validator.jsonl").exists() else {}
    # public repo: ids, levels, node paths (catalogue/make/model words), steps and outcomes only; no titles, URLs, prices
    with open(rdir / f"round-{rnd:02d}-decisions.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["listing_id", "source", "step", "route", "settled_level", "settled_path", "agent_answer",
                    "agent_confidence", "agent_answer_reused", "validator_checked", "validator_disagrees", "reason_codes"])
        for p in pl:
            if not (p.get("agent") or p["route"] or p["listing_id"] in val):
                continue
            v, ag = val.get(p["listing_id"]), p.get("agent") or {}
            w.writerow([p["listing_id"], p["source"], p["step"], p["route"] or "", p["level"], " > ".join(p["path"]),
                        ag.get("answer", ""), ag.get("confidence", ""), ag.get("reused", ""), bool(v),
                        "" if not v else v["disagree"], p["reason"].split(";agent:")[0]])
    shares = m["settled_by_step"]
    fa = full.get("agent", {})
    j = lambda x: json.dumps(x, ensure_ascii=False)
    tok = lambda t: f"{sum(v for k, v in t.items() if k != 'cached_input_tokens'):,} (cached input {t.get('cached_input_tokens', 0):,})" if t else "-"
    gl = gate.get("log", [])
    md = f"""# Cars round {rnd:02d}: {label}

Rules `identity.yaml`+`vocab.yaml` {m['inputs'].get('rules_version')} (`{m['inputs']['rules_sha256'][:12]}`) on {m['listings']:,} listings
(catalogue `{m['inputs']['catalogue_sha256'][:12]}`). Agents run through the local Codex CLI (ChatGPT login,
`gpt-6-astra`; placer at medium effort, validator at high). Data stays outside the repo: this file and the CSV carry ids,
levels and tree paths only. Every Codex call, gate decision and sealed read is in `runs/cars/ledger.jsonl` (hash-chained,
outside Git).

## 1. Where listings were settled (SPEC §4)

| Step | Listings | Share |
|---|---:|---:|
""" + "\n".join(f"| {s_} | {v['n']:,} | {v['share']:.1%} |" for s_, v in shares.items()) + f"""
| still routed | {m['routed']['n']:,} | {m['routed']['share']:.1%} |

Pipeline stage seconds: {j(m.get('timing_secs'))} (rules, no agent: about 1.2 s for all listings).

## 2. Placer (step 6, Codex)

| Run | Codex calls | Listings sent | Accepted by code | Seconds (sum of calls) | Tokens |
|---|---:|---:|---:|---:|---:|
| full run on rules 0.2.0 | {fa.get('calls', '-')} (+{fa.get('cached', 0)} cached) | {fa.get('sent', '-')} | {fa.get('accepted', '-')} | {fa.get('secs', '-')} | {fa.get('tokens', '-'):,} (older count: total "tokens used") |
| rerun on rules 0.3.0 | {led.get('placer', {}).get('calls', '-')} | {led.get('placer', {}).get('listings', '-')} | {m['agent'].get('accepted')} total ({m['agent'].get('reused_unchanged')} reused: input unchanged) | {led.get('placer', {}).get('seconds', '-')} | {tok(led.get('placer', {}).get('tokens', {}))} |

Answers on rules 0.2.0: {j(fa.get('outcome'))}. The placer mostly confirms the rules' own deeper candidate; that is
why it must be measured on random gold before step 6 is trusted.

## 3. Validator (Loop B), v1 -> v2

| | v1 (raw JSON cut at 700 chars) | v2 (identifying fields, uncut, + catalogue versions of the named model) |
|---|---|---|
| vs pipeline, random gold sample (50) | {j(v1.get('by_set', {}).get('gold_sample'))} | {j(v2.get('by_set', {}).get('gold_sample'))} |
| vs pipeline, fresh random (100) | {j(v1.get('by_set', {}).get('fresh'))} | {j(v2.get('by_set', {}).get('fresh'))} |
| vs pipeline, imported gold (39) | {j(v1.get('by_set', {}).get('gold_imported'))} | {j(v2.get('by_set', {}).get('gold_imported'))} |
| on dev gold (taxo/score.py) | {j({k: sc.get('validator_v1', {}).get(k) for k in ('label_holds_dataspec', 'exact', 'deeper', 'wrong', 'model_year')})} | {j({k: sc.get('validator_v2', {}).get(k) for k in ('label_holds_dataspec', 'exact', 'deeper', 'wrong', 'model_year')})} |
| flags on gold (precision) | {j(sc.get('validator_v1_flags_on_gold'))} | {j(sc.get('validator_v2_flags_on_gold'))} |
| Codex calls / seconds / tokens | {led.get('validator_v1', {}).get('calls', 0)} fresh in this ledger (earlier v1 calls predate it: 14 calls, 634 s, ~316k "tokens used") | {led.get('validator_v2', {}).get('calls', '-')} / {led.get('validator_v2', {}).get('seconds', '-')} s / {tok(led.get('validator_v2', {}).get('tokens', {}))} |

The validator's "wrong" rows on gold are mostly spelling ("Mercedes-Benz GLB" vs gold "Clase GLB"): taxo/score.py
compares words. Its one flag on gold is the Jeep "Rubicon 392 Final Edicion" placed on catalogue version "Rubicon 2.0L
Turbo 4x4": the imported gold calls that Correct, the validator disagrees, and a person must settle it (review item).
Query problem found and fixed in v2: v1 read raw JSON cut at 700 characters, so long Seminuevos/Kavak records lost
version and gearbox fields. v2 needed fewer seconds and tokens for the same 189 listings.

## 4. Rules (Loop A)

Changes made before the gate (owner-directed, "fix make errors first"; 0.2.0 -> 0.3.0, from validator flags):
1. `brand/group-title-model-owner`: "CHRYSLER ATTITUDE" with no make field -> Dodge (catalogue files Attitude under Dodge only), 5 listings.
2. `brand/rebrand-by-year`: "Dodge Ram <model>" of model year 2010+ -> Ram > <model>, 13 listings.

Gate on dev gold ({gate.get('dev_rows')} rows, rules only), then one logged sealed read ({gate.get('sealed_rows')} rows; sealed reads so far: {gate.get('sealed_reads_total')}):

| Candidate | Verdict | Gold rows touched | Delta (holds / harm / routed / version nodes) |
|---|---|---:|---|
""" + "\n".join(f"| {e['step']} | {e.get('verdict', e.get('kept'))} | {e['dev_rows_touched']} | {e['delta']['holds']} / {e['delta']['harm']} / {e['delta']['routed']} / {e['delta']['version_nodes']} |" for e in gl[1:]) + f"""

Kept: {j(gate.get('kept'))}. Sealed: {j(gate.get('sealed'))}.

## 5. Scores on dev gold ({sc.get('dev_rows')} rows, all imported reviews: NOT random)

Pipeline (final): {j(sc.get('pipeline_final'))}

## 6. For a person (review page, gold)

- Review: `runs/cars/loop-r{rnd:02d}/review.html` ({j(v2.get('review_items'))}); exports `review-r{rnd:02d}.yaml` (provenance: review).
- Blind random gold: `runs/cars/gold-r01/labeling-quick.html` (one click each) exports `round-01.yaml`.

## 7. Rule candidates to distill next

1. Catalogue version needs its distinctive words (the number guard): dropped by this gold, but the gold row it breaks
   is itself in question (Rubicon 392). Re-gate after the review settles that row.
2. Trim noise (colours, stock codes): cuts 5 routed listings and 12 version nodes; untestable until gold touches it.
3. A single trim letter (Kia Rio "L") is a version: today "l" is a generic token and the pipeline stops at the year.
4. Placer rubber-stamping: measure step-6 answers on random gold before trusting them.
"""
    (rdir / f"round-{rnd:02d}.md").write_text(md, encoding="utf-8")
    rec = {"domain": DOMAIN, "round": rnd, "kind": label, "branch": "cars-pipeline",
           "rules": {"version": m["inputs"].get("rules_version"), "sha256": m["inputs"]["rules_sha256"]},
           "settled_by_step": {k: v["share"] for k, v in shares.items()} | {"routed": m["routed"]["share"]},
           "agent": {"backend": "codex", "full_run_rules_0_2": {k: fa.get(k) for k in ("calls", "sent", "accepted", "secs", "tokens", "outcome")},
                     "rerun_rules_0_3": {"accepted": m["agent"].get("accepted"), "reused": m["agent"].get("reused_unchanged")}},
           "ledger_totals": led,
           "validator": {"v1": v1.get("by_set"), "v2": v2.get("by_set"),
                         "gold_v1": sc.get("validator_v1"), "gold_v2": sc.get("validator_v2"),
                         "flags_v1": sc.get("validator_v1_flags_on_gold"), "flags_v2": sc.get("validator_v2_flags_on_gold")},
           "gold": {"dev_rows": sc.get("dev_rows"), "provenance": sc.get("by_provenance"), "pipeline_final": sc.get("pipeline_final")},
           "changes": {"owner_directed": ["brand/group-title-model-owner", "brand/rebrand-by-year"],
                       "gate_kept": gate.get("kept"), "gate_log": [{k: e.get(k) for k in ("step", "verdict", "dev_rows_touched", "delta")} for e in gl[1:]]},
           "sealed_reads": gate.get("sealed_reads_total"),
           "note": "gold so far is imported owner reviews (not random); the blind random 50 is not labelled yet"}
    with open(ROOT / "memory" / "record.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"wrote rounds/cars/round-{rnd:02d}.md, round-{rnd:02d}-decisions.csv and a memory/record.jsonl line")


def main() -> None:
    ap = argparse.ArgumentParser(prog="domains.cars.loop", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate")
    v.add_argument("--round", type=int, default=1)
    v.add_argument("--fresh", type=int, default=100)
    v.add_argument("--effort", default="high")
    v.add_argument("--validator", type=int, default=2, help="validator prompt version (1 = raw JSON, 2 = evidence + catalogue)")
    s = sub.add_parser("score")
    s.add_argument("--round", type=int, default=1)
    r = sub.add_parser("record")
    r.add_argument("--round", type=int, default=1)
    r.add_argument("--label", default="baseline")
    a = ap.parse_args()
    if a.cmd == "validate":
        cmd_validate(a.round, a.fresh, a.effort, a.validator)
    elif a.cmd == "score":
        cmd_score(a.round)
    else:
        cmd_record(a.round, a.label)


if __name__ == "__main__":
    main()
