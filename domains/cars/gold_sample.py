"""Draw the cars gold round sample (DATA-SPEC §2.3, §5) and build a blind labeling page that exports gold YAML.

    uv run python -m domains.cars.gold_sample                    round 1: 50 listings, seed 20261109 -> runs/cars/gold-r01/
    open -a Safari runs/cars/gold-r01/labeling.html              label, then "Export round-01.yaml"

Random, not hand-picked: a fixed seed draws up to --per-source listings uniformly from each source (10 x 5 sources = 50),
then the order is shuffled so sources are mixed. The page is BLIND: it shows the raw listing and the catalogue tree
(suggestions), never the pipeline's answer. The first 25 rows are the second labeller's set
(round-01-second.yaml). Nothing is pre-filled and nothing writes gold except the person exporting it.
Save the export in TAXO_DATA_DIR/cars/gold/ (on Drive: meta-pedia-data/cars/gold/), where the pipeline scores it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from collections import defaultdict
from datetime import date
from pathlib import Path

from taxo.core import config
from taxo.core.config import RUNS_DIR
from taxo.core.io import read_jsonl

from domains.cars.adapter import listing_id

DOMAIN = "cars"
HIDE = {"image", "imageUrl", "analytics", "_scraped_at", "gallery", "_thumbnail_id", "_joinchat", "price_validity"}


def build_title(r: dict) -> str:
    make = r.get("make") or r.get("maker") or r.get("brand") or r.get("slice_brand")
    parts = [make, r.get("model"), r.get("version") if r.get("version") != "$undefined" else None, r.get("year")]
    return r.get("title") or " ".join(str(p) for p in parts if p)


def shown_fields(r: dict) -> dict:
    out = {}
    for k, v in r.items():
        if k in HIDE or v in (None, "", [], {}, "$undefined"):
            continue
        if k == "meta" and isinstance(v, dict):
            v = {mk: mv for mk, mv in v.items() if mk not in HIDE and mv not in (None, "", [], {})
                 and not mk.startswith(("stm_", "_", "certified", "special", "video", "gallery", "alignment",
                                        "title", "breadcrumbs", "car_brochure", "footnotes"))}
        out[k] = v
    return out


def catalogue_tree(path: Path) -> dict:
    """make -> model -> year -> [versions], from the catalogue as it came (the tree labellers may consult).
    Autocosmos and the brand sites spell one model differently ("Versa" vs "versa"); they are merged by a key."""
    rows = [r for r in read_jsonl(path) if r.get("brand") and r.get("model")]
    label: dict = {}
    for r in rows:
        make = r["brand"].replace("-", " ").title()
        k = (r["brand"], re.sub(r"[^a-z0-9]", "", str(r["model"]).lower()))
        shown = r.get("model_title") or r.get("model_display")
        if shown:
            shown = re.sub(r"\s+", " ", re.sub(rf"(?i)^{re.escape(make)}\s*", "", str(shown))).strip()
            shown = re.sub(r"\s+20\d\d$", "", shown)
        if shown and k not in label:
            label[k] = shown
    tree: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
    for r in rows:
        make = r["brand"].replace("-", " ").title()
        k = (r["brand"], re.sub(r"[^a-z0-9]", "", str(r["model"]).lower()))
        model = label.get(k) or str(r["model"]).replace("-", " ").title()
        y = str(r.get("year") or "")
        if y:
            tree[make][model][y]
            if r.get("version"):
                tree[make][model][y].add(str(r["version"]).strip())
        else:
            tree[make][model]
    return {mk: {md: {y: sorted(v) for y, v in ys.items()} for md, ys in mds.items()} for mk, mds in tree.items()}


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cars Gold Labels</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#deddd8;--accent:#2f5fd0;--ok:#1f7a4a;--warn:#a86400;--chip:#efeee9}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecebe6;--muted:#a09f99;--line:#34342f;--accent:#7ea0ff;--ok:#5fc58f;--warn:#e3a34a;--chip:#2a2a27}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif}
header{position:sticky;top:0;z-index:2;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;flex-wrap:wrap;gap:10px;align-items:center}
header h1{font-size:16px;margin:0 8px 0 0}.meta{color:var(--muted);font-size:12px}.progress{font-weight:600;font-variant-numeric:tabular-nums}
button{font:inherit;border:1px solid var(--line);background:var(--chip);color:var(--ink);border-radius:6px;padding:5px 10px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
input,select,textarea{font:inherit;font-size:14px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 7px;width:100%}
main{max-width:1100px;margin:0 auto;padding:16px}.warnbar{background:color-mix(in srgb,var(--warn) 18%,transparent);padding:8px 16px;font-size:13px}
.case{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:14px;display:grid;grid-template-columns:1fr 1fr;gap:16px}
.case.done{border-left:4px solid var(--ok)}@media(max-width:780px){.case{grid-template-columns:1fr}}
.title{font-size:16px;font-weight:600;margin:4px 0 8px;overflow-wrap:anywhere}.chip{background:var(--chip);border-radius:999px;padding:1px 8px;font-size:12px;color:var(--muted)}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:var(--bg);padding:8px;border-radius:6px;max-height:220px;overflow:auto}
.row4{display:grid;grid-template-columns:1fr 1fr 90px 1fr;gap:8px}@media(max-width:520px){.row4{grid-template-columns:1fr 1fr}}
label.f{display:flex;flex-direction:column;gap:3px;margin-bottom:8px;font-size:12px;color:var(--muted)}
.opts{display:flex;flex-wrap:wrap;gap:12px;font-size:13px;margin:4px 0 8px}.opts label{display:flex;gap:4px;align-items:center}.opts input{width:auto}
.hidden{display:none}.top{display:flex;gap:8px;align-items:center}.top input{width:140px}
</style></head><body>
<header><h1>Cars gold · round __ROUND__</h1><span class="progress" id="progress"></span>
<span class="top"><span class="meta">Labeller</span><input id="who" placeholder="your name"></span>
<label class="meta"><input type="checkbox" id="second" style="width:auto"> second labeller (rows 1–25 only)</label>
<span style="flex:1"></span><button class="primary" id="export">Export YAML</button><button id="clear">Clear all</button></header>
<div class="warnbar hidden" id="nostore">This view cannot save. Open the file in Safari or Chrome, or export before closing.</div>
<main>
<p class="meta" id="intro"></p>
<p class="meta">Path = <b>Make › Model › Year › Version</b>. Write the deepest path you are sure of (compare <b>prefix</b>).
Use <b>exact</b> when the depth matters (e.g. "stop at the make: no model named"). Year = model year. Body type is not part of the path.
Suggestions come from the catalogue (the tree), not from the system. Every row needs a one-sentence <b>why</b>.</p>
<div id="cases"></div></main>
<script id="data" type="application/json">__DATA__</script>
<script>
(()=>{const D=JSON.parse(document.getElementById('data').textContent);
const KEY=`cars-gold:${D.round}:${D.sample_sha.slice(0,12)}`;let ok=true,st={};
try{st=JSON.parse(localStorage.getItem(KEY)||'{}')||{};localStorage.setItem(KEY+':p','1');localStorage.removeItem(KEY+':p')}catch(e){ok=false;st={}}
if(!ok)document.getElementById('nostore').classList.remove('hidden');
st._rows=st._rows||{};const R=st._rows;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const save=()=>{if(ok)try{localStorage.setItem(KEY,JSON.stringify(st))}catch(e){}prog()};
const who=document.getElementById('who'),sec=document.getElementById('second');who.value=st.who||'';sec.checked=!!st.second;
who.oninput=()=>{st.who=who.value;save()};sec.onchange=()=>{st.second=sec.checked;show();save()};
document.getElementById('intro').textContent=D.intro;
const T=D.tree,makes=Object.keys(T).sort();
document.body.insertAdjacentHTML('beforeend',`<datalist id="mk">${makes.map(m=>`<option value="${esc(m)}">`).join('')}</datalist>`);
const done=r=>{const v=R[r.gid]||{};return !!(v.ood||(v.why&&v.make))};
const rows=()=>sec.checked?D.rows.slice(0,25):D.rows;
function prog(){const rs=rows();document.getElementById('progress').textContent=`${rs.filter(done).length} / ${rs.length} labelled`;
 D.rows.forEach(r=>document.getElementById('c-'+r.gid).classList.toggle('done',done(r)))}
const findMake=v=>makes.find(m=>m.toLowerCase()===String(v||'').trim().toLowerCase());
function lists(el,r){const v=R[r.gid]||{};const mk=findMake(v.make);const models=mk?Object.keys(T[mk]).sort():[];
 el.querySelector('.dl-model').innerHTML=models.map(m=>`<option value="${esc(m)}">`).join('');
 const md=mk&&Object.keys(T[mk]).find(m=>m.toLowerCase()===String(v.model||'').trim().toLowerCase());
 const ys=md?T[mk][md]:{};el.querySelector('.dl-year').innerHTML=Object.keys(ys).sort().map(y=>`<option value="${esc(y)}">`).join('');
 const vs=md&&ys[String(v.year||'').trim()]||[];el.querySelector('.dl-ver').innerHTML=vs.map(x=>`<option value="${esc(x)}">`).join('');
 el.querySelector('.cat').textContent=md?`Catalogue years for ${mk} ${md}: ${Object.keys(ys).filter(Boolean).sort().join(', ')||'none'}`:(mk?'Model not in the catalogue (you can still type it).':'')}
const root=document.getElementById('cases');
D.rows.forEach((r,i)=>{const el=document.createElement('section');el.className='case';el.id='c-'+r.gid;
 el.innerHTML=`<div><div class="meta">${i+1}. ${esc(r.gid)} <span class="chip">${esc(r.source)}</span>${i<25?' <span class="chip">second-labeller set</span>':''}</div>
 <div class="title">${esc(r.title)}</div><div class="meta">${r.url?`<a href="${esc(r.url)}" target="_blank" rel="noopener">open the listing</a> · `:''}${esc(r.listing_id)}</div>
 <pre>${esc(JSON.stringify(r.fields,null,1))}</pre></div>
 <div><div class="row4"><label class="f">Make<input data-f="make" list="mk"></label>
 <label class="f">Model<input data-f="model" list="m-${r.gid}"><datalist class="dl-model" id="m-${r.gid}"></datalist></label>
 <label class="f">Year<input data-f="year" inputmode="numeric" list="y-${r.gid}"><datalist class="dl-year" id="y-${r.gid}"></datalist></label>
 <label class="f">Version<input data-f="version" list="v-${r.gid}"><datalist class="dl-ver" id="v-${r.gid}"></datalist></label></div>
 <div class="meta cat"></div>
 <div class="opts"><label><input type="radio" name="cmp-${r.gid}" value="prefix" checked>prefix (deepest I'm sure of)</label>
 <label><input type="radio" name="cmp-${r.gid}" value="exact">exact (depth matters)</label>
 <label><input type="checkbox" data-f="ood">not a car listing (out of domain)</label></div>
 <label class="f">Why (one sentence)<textarea data-f="why" rows="2"></textarea></label></div>`;
 root.appendChild(el);
 const fill=()=>{const v=R[r.gid]||{};el.querySelectorAll('[data-f]').forEach(x=>x.type==='checkbox'?x.checked=!!v[x.dataset.f]:x.value=v[x.dataset.f]||'');
  el.querySelectorAll(`[name="cmp-${r.gid}"]`).forEach(x=>x.checked=x.value===(v.compare||'prefix'));lists(el,r)};
 el.addEventListener('input',e=>{const t=e.target,v=(R[r.gid]||={});if(t.name===`cmp-${r.gid}`)v.compare=t.value;else if(t.dataset.f)v[t.dataset.f]=t.type==='checkbox'?t.checked:t.value;lists(el,r);save()});
 el._fill=fill;fill()});
function show(){D.rows.forEach((r,i)=>document.getElementById('c-'+r.gid).classList.toggle('hidden',sec.checked&&i>=25));prog()}
show();
const q=s=>JSON.stringify(String(s));
document.getElementById('export').onclick=()=>{const name=(who.value||'').trim();if(!name){alert('Write your name first (labelled_by).');return}
 const rs=rows(),miss=rs.filter(r=>!done(r));if(miss.length&&!confirm(`${miss.length} rows are not labelled (they are left out). Export anyway?`))return;
 const today=new Date().toISOString().slice(0,10);let y=`# Cars gold round ${D.round}${sec.checked?' (second labeller)':''}. Blind labels by ${name}. Written by a person; never edited by an agent.\n# sample: ${D.sample_file} (seed ${D.seed}, sha256 ${D.sample_sha})\n`;
 for(const r of rs){if(!done(r))continue;const v=R[r.gid];let path=[],cmp=v.compare||'prefix',brand;
  if(v.ood){brand='none'}else{path=[v.make,v.model,v.year,v.version].map(x=>String(x||'').trim());const k=path.indexOf('');if(k>=0)path=path.slice(0,k);brand=path[0].toLowerCase()}
  y+=`\n- id: ${r.gid}\n  listing_id: ${q(r.listing_id)}\n  title: ${q(r.title)}\n  source: ${r.source}\n  brand: ${q(brand)}\n  expected_path: [${path.map(q).join(', ')}]\n  compare: ${cmp}\n  expect: accept\n  why: ${q(v.ood&&!v.why?'out of domain':v.why)}\n  labelled_by: ${q(name)}\n  labelled_at: ${today}\n  provenance: blind_random\n`}
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([y],{type:'text/yaml'}));a.download=`round-${String(D.round).padStart(2,'0')}${sec.checked?'-second':''}.yaml`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)};
document.getElementById('clear').onclick=()=>{if(confirm('Clear every label on this page? Export first to keep them.')){st={_rows:{}};Object.assign(R,{});for(const k in R)delete R[k];save();D.rows.forEach(r=>document.getElementById('c-'+r.gid)._fill())}};
prog()})();
</script></body></html>"""


QUICK = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cars Gold Quick</title><style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#deddd8;--accent:#2f5fd0;--ok:#1f7a4a}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecebe6;--muted:#a09f99;--line:#34342f;--accent:#7ea0ff;--ok:#5fc58f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;z-index:2}
header h1{font-size:16px;margin:0 8px 0 0}.meta{color:var(--muted);font-size:12px}
button{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:6px;padding:5px 10px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}main{max-width:900px;margin:0 auto;padding:16px}
.case{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:10px}.case.done{border-left:4px solid var(--ok)}
.case.hidden{display:none}.title{font-weight:600;overflow-wrap:anywhere}.opts{display:flex;flex-direction:column;gap:4px;margin-top:8px}
.opts label{border:1px solid var(--line);border-radius:6px;padding:5px 9px;cursor:pointer;font-size:14px}
.opts label:has(input:checked){border-color:var(--accent);background:color-mix(in srgb,var(--accent) 14%,transparent)}
input[type=text]{font:inherit;width:100%;padding:5px 7px;border:1px solid var(--line);border-radius:6px;background:var(--bg);color:var(--ink);margin-top:4px}
details{font-size:12px;color:var(--muted);margin-top:4px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
</style></head><body>
<header><h1>Cars gold: one click each</h1><span id="prog" class="meta"></span>
<label class="meta"><input type="checkbox" id="second"> second labeller (rows 1-25)</label><span style="flex:1"></span>
<label class="meta">Name <input id="who" type="text" style="width:100px;margin:0"></label><button id="export" class="primary">Export gold YAML</button></header>
<main><p class="meta">Random listings (seed __SEED__, 10 per source). Click the path that matches the car the listing sells, as deep as
its own words support: Make › Model › Year › Version. Options come from several sources in a shuffled order; none is
marked as the answer. If none fits, pick "Other" and type the path with › or &gt; between levels.</p><div id="cases"></div></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);const KEY='quickgold:cars:r'+D.round;let S={};try{S=JSON.parse(localStorage.getItem(KEY)||'{}')||{}}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}prog()};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sec=document.getElementById('second'),who=document.getElementById('who');sec.checked=!!S._second;who.value=S._who||'';
const rows=()=>sec.checked?D.cases.slice(0,25):D.cases;
function prog(){const rs=rows();document.getElementById('prog').textContent=rs.filter(c=>(S[c.gid]||{}).v!=null).length+' / '+rs.length+' done';
 D.cases.forEach((c,i)=>{const el=document.getElementById('c'+i);el.classList.toggle('done',(S[c.gid]||{}).v!=null);el.classList.toggle('hidden',sec.checked&&i>=25)})}
sec.onchange=()=>{S._second=sec.checked;save()};who.oninput=()=>{S._who=who.value;save()};
D.cases.forEach((c,i)=>{const el=document.createElement('section');el.className='case';el.id='c'+i;
 const opts=c.options.map((o,j)=>`<label><input type="radio" name="o${i}" value="${j}"> ${esc(o.join(' › '))}</label>`).join('')+
  `<label><input type="radio" name="o${i}" value="cant"> Can't tell</label><label><input type="radio" name="o${i}" value="ood"> Not a car listing</label>`+
  `<label><input type="radio" name="o${i}" value="other"> Other: <input type="text" class="oth" placeholder="Make › Model › Year › Version"></label>`;
 el.innerHTML=`<div class="meta">${i+1}. ${esc(c.source)}${i<25?' · second-labeller set':''} · ${c.url?`<a href="${esc(c.url)}" target="_blank" rel="noopener">open</a>`:''}</div>
 <div class="title">${esc(c.title)}</div><details><summary>all listing fields</summary><pre>${esc(JSON.stringify(c.fields,null,1))}</pre></details><div class="opts">${opts}</div>`;
 document.getElementById('cases').appendChild(el);
 const st=S[c.gid]||{};if(st.v!=null){const r=el.querySelector(`input[value="${st.v}"]`);if(r)r.checked=true}el.querySelector('.oth').value=st.t||'';
 el.addEventListener('input',e=>{const x=(S[c.gid]||={});if(e.target.type==='radio')x.v=e.target.value;if(e.target.classList.contains('oth')){x.t=e.target.value;x.v='other';el.querySelector('input[value=other]').checked=true}save()})});
prog();
const q=s=>JSON.stringify(String(s));
document.getElementById('export').onclick=()=>{const name=who.value.trim();if(!name){alert('Write your name first.');return}
 const today=new Date().toISOString().slice(0,10);let y=`# Cars gold round ${D.round}${sec.checked?' (second labeller)':''}: one-click blind choices by ${name}. Written by a person.\n# sample ${D.sample_file} sha256 ${D.sample_sha}; options shuffled, sources hidden.\n`,n=0,cant=0;
 for(const c of rows()){const x=S[c.gid];if(!x||x.v==null)continue;let path,cmp='prefix';
  if(x.v==='cant'){cant++;continue}else if(x.v==='ood')path=[];else if(x.v==='other')path=(x.t||'').split(/[›>]/).map(s=>s.trim()).filter(Boolean);else path=c.options[+x.v];
  if(x.v==='other'&&!path.length)continue;n++;
  y+=`\n- id: ${c.gid}\n  listing_id: ${q(c.listing_id)}\n  title: ${q(c.title)}\n  source: ${c.source}\n  brand: ${q(path.length?path[0].toLowerCase():'none')}\n  expected_path: [${path.map(q).join(', ')}]\n  compare: ${cmp}\n  expect: accept\n  why: ${q(x.v==='ood'?'out of domain':x.v==='other'?'typed by the labeller':'one-click choice')}\n  labelled_by: ${q(name)}\n  labelled_at: ${today}\n  provenance: blind_random_choice\n`}
 y+=`\n# can't tell: ${cant} listings (not written as gold)\n`;
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([y],{type:'text/yaml'}));a.download=`round-${String(D.round).padStart(2,'0')}${sec.checked?'-second':''}.yaml`;a.click();
 setTimeout(()=>URL.revokeObjectURL(a.href),1000);alert(n+' rows exported. Save the file in data/taxo-data/cars/gold/.')};
</script></body></html>"""


def _norm(path) -> tuple:
    return tuple(re.sub(r"[^a-z0-9]", "", str(x).lower()) for x in path)


def quick_page(rnd: int) -> Path:
    """One-click page: each listing gets 3-6 candidate paths (pipeline final, validator, their shorter prefixes, catalogue
    neighbours of the named model), deduplicated and hash-shuffled with no source shown."""
    out = RUNS_DIR / DOMAIN / f"gold-r{rnd:02d}"
    sample_file = out / f"sample-r{rnd:02d}.jsonl"
    drawn = [json.loads(l) for l in sample_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    pl = {json.loads(l)["listing_id"]: json.loads(l) for l in (RUNS_DIR / DOMAIN / "placements.jsonl").read_text(encoding="utf-8").splitlines()}
    vfile = RUNS_DIR / DOMAIN / f"loop-r{rnd:02d}" / "validator.jsonl"
    val = {json.loads(l)["listing_id"]: json.loads(l) for l in vfile.read_text(encoding="utf-8").splitlines()} if vfile.exists() else {}
    tree = catalogue_tree(config.data_dir() / DOMAIN / "taxonomy.jsonl")
    tkey = {re.sub(r"[^a-z0-9]", "", m.lower()): m for m in tree}
    cases = []
    for i, x in enumerate(drawn, 1):
        lid, r = x["listing_id"], x["record"]
        p = pl[lid]
        pipe = (p.get("candidate") or {}).get("path") or p["path"]
        pipe = [pipe[0].replace("-", " ").title()] + list(pipe[1:]) if pipe else []
        vpath = (val.get(lid) or {}).get("validator_path") or []
        opts = [pipe, vpath]
        opts += [o[:k] for o in (pipe, vpath) for k in (1, 2, 3) if len(o) > k]
        for o in (vpath, pipe):     # catalogue neighbours of the named model: its years, and versions for the stated year
            mk = tkey.get(re.sub(r"[^a-z0-9]", "", str(o[0]).lower())) if o else None
            if not (mk and len(o) > 1):
                continue
            md = next((m for m in tree[mk] if _norm([m]) == _norm([o[1]])), None)
            if not md:
                continue
            ys = tree[mk][md]
            year = str(o[2]) if len(o) > 2 else None
            if year and ys.get(year):
                opts += [[mk, md, year, v] for v in ys[year][:3]]
            opts += [[mk, md, y] for y in sorted(ys) if y and y != year][:2]
            break
        seen, uniq = set(), []
        for o in opts:
            k = _norm(o)
            if o and k not in seen:
                seen.add(k)
                uniq.append([str(s) for s in o])
        uniq = uniq[:6]
        uniq.sort(key=lambda o: hashlib.sha256(f"opt|{lid}|{'/'.join(o)}".encode()).hexdigest())
        title = build_title(r) + (f" · {r['subtitle']}" if r.get("subtitle") else "")
        cases.append({"gid": x["gold_id"], "listing_id": lid, "source": r["_source"], "title": title,
                      "url": r.get("url"), "fields": shown_fields(r), "options": uniq})
    data = {"round": rnd, "sample_file": sample_file.name, "sample_sha": hashlib.sha256(sample_file.read_bytes()).hexdigest(),
            "cases": cases}
    seed = re.search(r"seed (\d+)", (out / f"SOURCE-r{rnd:02d}.md").read_text()).group(1)
    path = out / "labeling-quick.html"
    path.write_text(QUICK.replace("__DATA__", json.dumps(data, ensure_ascii=False).replace("</", "<\\/")).replace("__SEED__", seed),
                    encoding="utf-8")
    from collections import Counter
    print("quick gold page:", path, "| options per case:", dict(Counter(len(c["options"]) for c in cases)))
    return path


def main() -> None:
    ap = argparse.ArgumentParser(prog="domains.cars.gold_sample", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--per-source", type=int, default=10)
    ap.add_argument("--seed", type=int, default=20261109)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--page-only", action="store_true", help="rebuild labeling.html from the existing sample; never redraws")
    ap.add_argument("--quick", action="store_true", help="build the one-click page labeling-quick.html (needs a pipeline run and loop validate)")
    a = ap.parse_args()
    if a.quick:
        quick_page(a.round)
        return
    out = a.out or RUNS_DIR / DOMAIN / f"gold-r{a.round:02d}"
    sample_file = out / f"sample-r{a.round:02d}.jsonl"
    d = config.data_dir() / DOMAIN
    by_id = {}
    for r in read_jsonl(d / "listings.jsonl"):
        by_id.setdefault(listing_id(r), r)       # one row per listing id (5 Kavak cars appear twice)
    by_source = defaultdict(list)
    for lid in sorted(by_id):
        by_source[by_id[lid]["_source"]].append(lid)
    if sample_file.exists():
        if not a.page_only:
            raise SystemExit(f"{sample_file} exists; a drawn sample is never redrawn. Use a new --round (or --page-only).")
        drawn = [json.loads(l) for l in sample_file.read_text(encoding="utf-8").splitlines() if l.strip()]
        picked = [x["listing_id"] for x in drawn]
    else:
        if a.page_only:
            raise SystemExit("no sample yet: run without --page-only first")
        rng = random.Random(a.seed)
        picked = []
        for src in sorted(by_source):
            picked += rng.sample(by_source[src], min(a.per_source, len(by_source[src])))
        rest = sorted(set(by_id) - set(picked))
        if len(picked) < a.n:
            picked += rng.sample(rest, a.n - len(picked))
        picked = picked[:a.n]
        rng.shuffle(picked)
        out.mkdir(parents=True, exist_ok=True)
        with open(sample_file, "w", encoding="utf-8") as f:
            for i, lid in enumerate(picked, 1):
                f.write(json.dumps({"gold_id": f"gold-cars-r{a.round:02d}-{i:04d}", "listing_id": lid,
                                    "record": by_id[lid]}, ensure_ascii=False) + "\n")
    rows = []
    for i, lid in enumerate(picked, 1):
        r = by_id[lid]
        rows.append({"gid": f"gold-cars-r{a.round:02d}-{i:04d}", "listing_id": lid, "source": r["_source"],
                     "title": build_title(r), "url": r.get("url"), "fields": shown_fields(r)})
    sha = hashlib.sha256(sample_file.read_bytes()).hexdigest()
    counts = {s: sum(by_id[l]["_source"] == s for l in picked) for s in sorted(by_source)}
    data = {"round": a.round, "seed": a.seed, "sample_file": sample_file.name, "sample_sha": sha, "rows": rows,
            "tree": catalogue_tree(d / "taxonomy.jsonl"),
            "intro": f"{len(rows)} listings drawn at random (seed {a.seed}, up to {a.per_source} per source: "
                     + ", ".join(f"{s} {n}" for s, n in counts.items()) + "). Blind: the system's answer is not shown."}
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    (out / "labeling.html").write_text(PAGE.replace("__DATA__", payload).replace("__ROUND__", str(a.round)), encoding="utf-8")
    (out / f"SOURCE-r{a.round:02d}.md").write_text(f"""# Cars gold round {a.round:02d}: sample

- Drawn {date.today().isoformat()} by `uv run python -m domains.cars.gold_sample --round {a.round}` (seed {a.seed}).
- Method: uniform random within each source, up to {a.per_source} per source, filled at random to {a.n}, then shuffled
  (DATA-SPEC §2.3, §5.1). One row per listing id (`domains/cars/adapter.py:listing_id`).
- From `TAXO_DATA_DIR/cars/listings.jsonl` ({len(by_id)} unique listing ids).
- Rows per source: {", ".join(f"{s} {n}" for s, n in counts.items())}.
- `{sample_file.name}` sha256 `{sha}`.
- Second labeller: rows 1-25 of the page (gold ids ...-0001 to ...-0025), saved as `round-{a.round:02d}-second.yaml`.
- Labels are blind: the page shows the raw listing and catalogue suggestions, never the pipeline's placement.
""", encoding="utf-8")
    print(json.dumps({"out": str(out), "rows": len(rows), "per_source": counts, "sample_sha256": sha}, indent=1))


if __name__ == "__main__":
    main()
