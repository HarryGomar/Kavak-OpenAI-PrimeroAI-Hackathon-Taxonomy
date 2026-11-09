"""Draw the electronics blind random gold sample (DATA-SPEC §2, §5) and write a labelling page for it.

    uv run python -m domains.electronics.gold_sample [--n 50] [--round 1]

Frame: the listings the pipeline's category step puts in scope (storage, cameras, printing, audio, video). Random
with a fixed seed, at least --per-source listings from each source where the frame allows. Listings a person has
already seen with a proposed answer (earlier review batches) are excluded so labels stay blind. The page shows only
what the listing says; the pipeline's answer is never shown. Its export is gold/round-NN.yaml in the scaffold format
(docs/templates/gold.example.yaml), which a person saves into TAXO_DATA_DIR/electronics/gold/. No label is written
by code.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json

from domains.electronics.pipeline import OUT, load
from domains.electronics.classify import Categories
from taxo.core import config

DOMAIN = "electronics"
SEED = "taxo-electronics-gold"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--per-source", type=int, default=10)
    ap.add_argument("--round", type=int, default=1)
    ap.add_argument("--exclude", default="seen.txt", help="file under TAXO_DATA_DIR/electronics/ listing ids already seen")
    args = ap.parse_args()
    rows, _ = load()
    cats = Categories()
    seen_path = config.data_dir() / DOMAIN / args.exclude
    seen = set(seen_path.read_text().split()) if seen_path.exists() else set()
    frame = [k for k, r in rows.items() if k not in seen and cats.categorize(r)["proposed_category"]]
    order = sorted(frame, key=lambda k: hashlib.sha256(f"{SEED}|r{args.round}|{k}".encode()).hexdigest())
    by_src = defaultdict(list)
    for k in order:
        by_src[rows[k]["merchant"]].append(k)
    pick = []
    for src in sorted(by_src):
        pick += by_src[src][:args.per_source]
    for k in order:
        if len(pick) >= args.n:
            break
        if k not in pick:
            pick.append(k)
    pick = sorted(pick[:args.n], key=lambda k: hashlib.sha256(f"{SEED}|show|{k}".encode()).hexdigest())
    out = OUT / f"gold-round-{args.round:02}"
    out.mkdir(parents=True, exist_ok=True)
    cases = [{"n": i + 1, "listing_id": k, "title": rows[k]["title"], "source": rows[k]["merchant"],
              "dataset": rows[k]["dataset"], "brand_field": rows[k]["brand_manufacturer"],
              "model_field": rows[k]["manufacturer_model"], "source_category": rows[k]["source_category"],
              "price_raw": rows[k]["price_raw"]} for i, k in enumerate(pick)]
    (out / "sample.json").write_text(json.dumps({"round": args.round, "seed": SEED, "frame": len(frame),
                                                  "excluded_seen": len(seen), "cases": cases}, indent=2), encoding="utf-8")
    meta = {"round": args.round, "domain": DOMAIN, "frame": len(frame), "seed": SEED}
    page = PAGE.replace("__DATA__", json.dumps({"meta": meta, "cases": cases}).replace("</", "<\\/"))
    (out / "labeling.html").write_text(page, encoding="utf-8")
    counts = defaultdict(int)
    for c in cases:
        counts[c["source"]] += 1
    print(f"{len(cases)} cases from a frame of {len(frame)} (excluded {len(seen)} seen): {dict(counts)}")
    print(f"open {out / 'labeling.html'}; save the export as {config.data_dir() / DOMAIN / 'gold' / f'round-{args.round:02}.yaml'}")


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Electronics Gold</title><style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#deddd8;--accent:#2f5fd0;--ok:#1f7a4a}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--panel:#1f1f1d;--ink:#ecebe6;--muted:#a09f99;--line:#34342f;--accent:#7ea0ff;--ok:#5fc58f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 -apple-system,system-ui,sans-serif}
header{position:sticky;top:0;background:var(--panel);border-bottom:1px solid var(--line);padding:10px 16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center;z-index:2}
header h1{font-size:16px;margin:0 8px 0 0}.meta{color:var(--muted);font-size:12px}
button{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:6px;padding:5px 10px;cursor:pointer}
button.primary{background:var(--accent);border-color:var(--accent);color:#fff}
main{max-width:980px;margin:0 auto;padding:16px}
.case{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;margin-bottom:12px;display:grid;grid-template-columns:1fr 1fr;gap:14px}
.case.done{border-left:4px solid var(--ok)}@media (max-width:760px){.case{grid-template-columns:1fr}}
.title{font-weight:600;margin:4px 0 8px;overflow-wrap:anywhere}dl{display:grid;grid-template-columns:max-content 1fr;gap:2px 10px;margin:0;font-size:13px}
dt{color:var(--muted)}dd{margin:0;overflow-wrap:anywhere}
label.f{display:flex;flex-direction:column;gap:3px;font-size:12px;color:var(--muted);margin-bottom:7px}
label.f input,label.f textarea,label.f select{font:inherit;font-size:14px;color:var(--ink);background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 7px}
.row{display:flex;gap:12px;flex-wrap:wrap;font-size:13px;margin:4px 0 8px}
pre{white-space:pre-wrap;background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px;font-size:12px}
</style></head><body>
<header><h1>Electronics gold, blind</h1><span id="prog" class="meta"></span><span style="flex:1"></span>
<label class="meta">Your name <input id="who" style="font:inherit;width:110px"></label>
<button id="export" class="primary">Export gold YAML</button><button id="clear">Clear</button></header>
<main><p class="meta">Random sample. Say what the listing itself sells, as deep as its own words support: Brand, then product (the manufacturer model), then variant (colour or capacity, only if that model comes in several). Leave product empty to stop at the brand. Packs, bundles and refurbished items still get the product they contain. Nothing here shows the pipeline's answer.</p>
<div id="cases"></div><h3>Export preview</h3><pre id="yaml"></pre></main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D=JSON.parse(document.getElementById('data').textContent);const KEY='gold:electronics:r'+D.meta.round;
let S={};try{S=JSON.parse(localStorage.getItem(KEY)||'{}')||{}}catch(e){}
const save=()=>{try{localStorage.setItem(KEY,JSON.stringify(S))}catch(e){}prog();};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const done=c=>{const v=S[c.listing_id]||{};return v.skip||v.brand};
function prog(){document.getElementById('prog').textContent=D.cases.filter(done).length+' / '+D.cases.length+' labelled';
 D.cases.forEach(c=>document.getElementById('c'+c.n).classList.toggle('done',!!done(c)));document.getElementById('yaml').textContent=yaml();}
const root=document.getElementById('cases');
for(const c of D.cases){const el=document.createElement('section');el.className='case';el.id='c'+c.n;
 const r=(k,v)=>v?`<dt>${k}</dt><dd>${esc(v)}</dd>`:'';
 el.innerHTML=`<div><div class="meta">#${c.n} · ${esc(c.listing_id)}</div><div class="title">${esc(c.title)}</div><dl>${r('Source',c.source)}${r('Brand field',c.brand_field)}${r('Model field',c.model_field)}${r('Source category',c.source_category)}${r('Price (currency unknown)',c.price_raw)}</dl></div>
 <div><label class="f">Brand<input data-f="brand"></label><label class="f">Product (manufacturer model; empty = stop at brand)<input data-f="product"></label>
 <label class="f">Variant (colour or capacity, optional)<input data-f="variant"></label>
 <div class="row"><label><input type="checkbox" data-f="prefix"> deeper is also fine (prefix)</label><label><input type="checkbox" data-f="skip"> not an electronics product / can't tell</label></div>
 <label class="f">Why (one line)<input data-f="why"></label></div>`;
 root.appendChild(el);const v=S[c.listing_id]||{};
 el.querySelectorAll('[data-f]').forEach(i=>{const f=i.dataset.f;if(i.type==='checkbox')i.checked=!!v[f];else i.value=v[f]||'';});
 el.addEventListener('input',e=>{const f=e.target.dataset.f;if(!f)return;(S[c.listing_id]||={})[f]=e.target.type==='checkbox'?e.target.checked:e.target.value;save();});}
const q=s=>JSON.stringify(String(s));
function yaml(){const who=document.getElementById('who').value.trim()||'diego';const today=new Date().toISOString().slice(0,10);let out='# Electronics gold round '+String(D.meta.round).padStart(2,'0')+': blind random sample (seed '+D.meta.seed+', frame '+D.meta.frame+'). Written by a person.\n';let i=0;
 for(const c of D.cases){const v=S[c.listing_id]||{};if(!(v.brand||v.skip))continue;i++;
  const id='gold-electronics-r'+String(D.meta.round).padStart(2,'0')+'-'+String(i).padStart(4,'0');
  const path=v.skip?[]:[v.brand,v.product,v.variant].map(x=>(x||'').trim()).filter(Boolean);
  const cut=path.length&&!v.variant?path:path;
  out+=`\n- id: ${id}\n  listing_id: ${q(c.listing_id)}\n  title: ${q(c.title)}\n  source: ${q(c.source)}\n  brand: ${q(v.skip?'(none)':(v.brand||'').trim().toLowerCase())}\n  expected_path: [${cut.map(q).join(', ')}]\n  compare: ${v.prefix?'prefix':'exact'}\n  expect: accept\n  why: ${q(v.skip?'Not an electronics product or cannot tell. '+(v.why||''):(v.why||''))}\n  labelled_by: ${q(who)}\n  labelled_at: ${today}\n  provenance: blind_random\n`;}
 return out;}
document.getElementById('who').addEventListener('input',prog);
document.getElementById('export').addEventListener('click',()=>{const b=new Blob([yaml()],{type:'text/yaml'});const a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='round-'+String(D.meta.round).padStart(2,'0')+'.yaml';a.click();});
document.getElementById('clear').addEventListener('click',()=>{if(confirm('Clear all labels on this page?')){S={};save();location.reload();}});
prog();
</script></body></html>"""


if __name__ == "__main__":
    main()
