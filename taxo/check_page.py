"""A check page for AI pre-labelled gold: every listing shows its options with the agent's suggestion pre-selected.
A person confirms or changes each one; the export records which rows the person changed.

    uv run python -m taxo.check_page <domain> <cases.json> <prelabels.json> <out.html> [--round 1]

Provenance on export: ai_prelabel_checked. These rows are NOT blind gold (the suggestion anchors the labeller);
score them separately from blind_random rows (SPEC §8: gold is made by people; this is a person's check of an agent).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

LEVELS = {"electronics": "Brand / product type / model / variant", "cars": "Make / Model / Year / Version"}


def build(domain, cases_path, prelabels_path, out, rnd=1, model="fable"):
    cases = json.loads(Path(cases_path).read_text())
    pre = {p["listing_id"]: p for p in json.loads(Path(prelabels_path).read_text())[domain]}
    missing = [c["listing_id"] for c in cases if c["listing_id"] not in pre]
    if missing:
        raise SystemExit(f"{len(missing)} cases have no pre-label: {missing[:3]}")
    for c in cases:
        f = c.get("fields") or {}
        shown = {k: c[k] for k in ("source", "brand_field", "model_field", "source_category", "price_raw") if c.get(k)}
        shown.update({k: v for k, v in f.items() if k in ("version", "year_km", "year", "km", "kilometers", "location",
                                                            "price_mxn", "price", "dealer", "make", "model", "brand")})
        c["shown"] = shown
        p = pre[c["listing_id"]]
        c["pre"] = {"choice": str(p["choice"]), "path": p.get("path") or [], "confidence": p.get("confidence"),
                    "reason": p.get("reason", "")}
    cases.sort(key=lambda c: (c["pre"]["confidence"] if c["pre"]["confidence"] is not None else 0))
    data = {"domain": domain, "round": rnd, "levels": LEVELS.get(domain, ""), "model": model, "cases": cases}
    Path(out).write_text(PAGE.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")),
                         encoding="utf-8")
    low = sum(1 for c in cases if (c["pre"]["confidence"] or 0) < 0.7)
    print(f"{out}: {len(cases)} cases, {low} below 0.7 confidence (shown first)")


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Check Gold</title><style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#deddd8;--accent:#2f5fd0;--ok:#1f7a4a;--warn:#a86400}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecebe6;--muted:#a09f99;--line:#34342f;--accent:#7ea0ff;--ok:#5fc58f;--warn:#e3a34a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;z-index:2}
header h1{font-size:16px;margin:0 8px 0 0}.meta{color:var(--muted);font-size:12px}
button{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:6px;padding:5px 10px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}main{max-width:900px;margin:0 auto;padding:16px}
.case{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:10px}
.case.low{border-left:4px solid var(--warn)}.case.changed{border-left:4px solid var(--accent)}
.title{font-weight:600;overflow-wrap:anywhere}.ai{font-size:12px;color:var(--muted);margin-top:4px}.ai b{color:var(--warn)}
.opts{display:flex;flex-direction:column;gap:4px;margin-top:8px}
.opts label{border:1px solid var(--line);border-radius:6px;padding:5px 9px;cursor:pointer;font-size:14px}
.opts label:has(input:checked){border-color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,transparent)}
input[type=text]{font:inherit;width:100%;padding:5px 7px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);margin-top:4px}
</style></head><body>
<header><h1 id="h"></h1><span id="prog" class="meta"></span><span style="flex:1"></span>
<label class="meta">Name <input id="who" type="text" style="width:100px;margin:0"></label><button id="export" class="primary">Export gold YAML</button></header>
<main><p class="meta" id="intro"></p><div id="cases"></div></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);const KEY='check:'+D.domain+':r'+D.round;let S={};try{S=JSON.parse(localStorage.getItem(KEY)||'{}')||{}}catch(e){}
document.getElementById('h').textContent=D.domain[0].toUpperCase()+D.domain.slice(1)+' gold: check the AI answers';
document.getElementById('intro').textContent='An AI agent ('+D.model+') pre-selected an answer for every listing. Read each one; change it only if it is wrong. Least confident first (orange border). Path: '+D.levels+', as deep as the listing\'s own words support.';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}prog()};
const cur=c=>S[c.listing_id]||{v:c.pre.choice,other:(c.pre.path||[]).join(' / ')};
const changed=c=>{const s=S[c.listing_id];if(!s)return false;return s.v!==c.pre.choice||(s.v==='other'&&s.other!==(c.pre.path||[]).join(' / '))};
function prog(){const n=D.cases.filter(changed).length;document.getElementById('prog').textContent=D.cases.length+' pre-labelled · '+n+' changed by you';D.cases.forEach((c,i)=>document.getElementById('c'+i).classList.toggle('changed',changed(c)));}
const extra=D.domain==='cars'?[['not_listing','Not a car listing']]:[];
D.cases.forEach((c,i)=>{const el=document.createElement('section');el.className='case'+((c.pre.confidence??0)<0.7?' low':'');el.id='c'+i;
 const f=Object.entries(c.shown||{}).map(([k,v])=>esc(k)+': '+esc(v)).join(' · ');const s=cur(c);
 const conf=c.pre.confidence==null?'?':Math.round(c.pre.confidence*100)+'%';
 el.innerHTML=`<div class="meta">${f}</div><div class="title">${esc(c.title)}</div><div class="ai">AI: <b>${conf}</b> · ${esc(c.pre.reason)}</div><div class="opts">${c.options.map((o,j)=>`<label><input type="radio" name="o${i}" value="${j}"> ${esc(o.join(' / '))}</label>`).join('')}
 <label><input type="radio" name="o${i}" value="none"> Can't tell${D.domain==='electronics'?' / not an electronics product':''}</label>${extra.map(([v,l])=>`<label><input type="radio" name="o${i}" value="${v}"> ${l}</label>`).join('')}
 <label><input type="radio" name="o${i}" value="other"> Other: <input type="text" data-f="other" placeholder="${esc(D.levels)}"></label></div>`;
 document.getElementById('cases').appendChild(el);
 el.querySelectorAll('input[type=radio]').forEach(r=>r.checked=r.value===s.v);el.querySelector('[data-f]').value=s.other||'';
 el.addEventListener('input',e=>{const st=(S[c.listing_id]||={...cur(c)});if(e.target.type==='radio')st.v=e.target.value;else{st.other=e.target.value;st.v='other';el.querySelector('input[value=other]').checked=true;}save();});});
const q=s=>JSON.stringify(String(s));
document.getElementById('export').addEventListener('click',()=>{const who=document.getElementById('who').value.trim()||'diego';const today=new Date().toISOString().slice(0,10);
 let y='# '+D.domain+' gold round '+String(D.round).padStart(2,'0')+': AI ('+D.model+') pre-labels checked by a person. NOT blind: score separately from blind_random rows.\n';let i=0;
 D.cases.forEach(c=>{const s=cur(c);i++;const id='gold-'+D.domain+'-r'+String(D.round).padStart(2,'0')+'-'+String(i).padStart(4,'0');
  const path=(s.v==='none'||s.v==='not_listing')?[]:s.v==='other'?(s.other||'').split('/').map(x=>x.trim()).filter(Boolean):c.options[+s.v];
  y+=`\n- id: ${id}\n  listing_id: ${q(c.listing_id)}\n  title: ${q(c.title)}\n  source: ${q(c.source||'')}\n  brand: ${q(path.length?path[0].toLowerCase():'(none)')}\n  expected_path: [${path.map(q).join(', ')}]\n  compare: exact\n  expect: accept\n  why: ${q(s.v==='not_listing'?'not a listing':'')}\n  changed_by_person: ${changed(c)}\n  ai_confidence: ${c.pre.confidence??'null'}\n  labelled_by: ${q(who)}\n  labelled_at: ${today}\n  provenance: ai_prelabel_checked\n`;});
 const b=new Blob([y],{type:'text/yaml'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=D.domain+'-round-'+String(D.round).padStart(2,'0')+'.yaml';a.click();});
prog();
</script></body></html>"""


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("domain")
    ap.add_argument("cases")
    ap.add_argument("prelabels")
    ap.add_argument("out")
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--model", default="fable")
    a = ap.parse_args()
    build(a.domain, a.cases, a.prelabels, a.out, a.round, a.model)
