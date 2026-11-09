import time, yaml
from taxo import evaluator
from taxo.propose import Bench, apply, dev_gate, prompt, Refused
t=time.time(); b=Bench("food")
doc=yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")); rules=evaluator.load(*b.rule_dirs)
cur=b.evaluate(doc, rules); print("load+eval", round(time.time()-t), "s; dev exact", cur["dev"]["exact"], "agent", cur["to_agent"])
txt=prompt(b, doc, rules, cur, []); print("prompt chars", len(txt))
tests=[
 {"kind":"vocab","label":"strip flavored","patch":"strip_add: [flavored]"},
 {"kind":"vocab","label":"strip a product name","patch":"strip_add: [skittles]"},
 {"kind":"rule","label":"brand-specific","patch":"id: x\nstage: route\nwhen: [{fact: brand.slug, eq: skittles}]\nthen: {settle: brand}"},
 {"kind":"rule","label":"short under-floor names placed","patch":"id: short-names\nstage: route\nwhen: [{fact: placement.reason, eq: under_floor}, {fact: placement.cluster_units, le: 2}]\nthen: {place: cluster}"},
 {"kind":"rule","label":"variety pack exception","patch":"id: variety-pack-ok\nstage: place\nwhen: [{fact: listing.title, has_any: [variety pack]}, {check: set_conflict}]\nthen: {veto: false}"},
 {"kind":"toggle","label":"set veto off","patch":"id: veto/set-conflict\nstatus: shadow"},
 {"kind":"rule","label":"bad then","patch":"id: y\nstage: route\nwhen: [{fact: placement.level, eq: brand}]\nthen: {place: product}"},
]
for p in tests:
    try:
        d2, r2, ch = apply(b, p, doc, rules)
    except Refused as e:
        print("REFUSED", p["label"], "->", e); continue
    t=time.time(); ev=b.evaluate(d2, r2); ok, info = dev_gate(cur, ev)
    print("PASS" if ok else "fail", p["label"], {k: info[k] for k in ("better","worse","touched","exact","to_agent","wilson","fails")}, round(time.time()-t),"s")
print(txt[:600]); print("...")
