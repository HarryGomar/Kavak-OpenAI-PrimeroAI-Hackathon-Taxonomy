"""Food Loop A candidates scored on DEV gold only (no sealed read). One load, many runs.
    uv run python experiments/dev_try.py
"""
import copy, json, sys, time
from pathlib import Path
import yaml
from taxo import evaluator
from taxo.core.config import DOMAINS_DIR, ROOT
from taxo import gold as goldmod
from taxo.lattice import vocab as vocabmod
from taxo.parse import Brands
from taxo.pipeline import load_gold, load_items, run, score_rows, shares

D = "food"
t0 = time.time()
rows, human, names = load_gold("drive", D)
items = load_items("drive", rows, human, D)
by_gold = {gid: it for it in items for gid in it.gold}
dev = [g for g in rows if not goldmod.is_sealed(g.brand)]
subset = [it for it in items if not it.id.startswith("gold:")]
base_doc = yaml.safe_load((DOMAINS_DIR / D / "vocab.yaml").read_text(encoding="utf-8"))
base_rules = evaluator.load(ROOT / "rules" / D, ROOT / "rules" / "global")
tmp = ROOT / "runs" / D / "vocab-dev-try.yaml"
tmp.parent.mkdir(parents=True, exist_ok=True)
print(f"loaded {len(items)} items, {len(dev)} dev rows in {time.time()-t0:.0f}s", flush=True)

def shadowed(rules, rid):
    return [evaluator.Rule(**{**r.__dict__, "status": "shadow"}) if r.id == rid else r for r in rules]

def score(doc, rules, suffixes=()):
    tmp.write_text(yaml.safe_dump(doc), encoding="utf-8")
    brands = Brands(names, tuple(suffixes))
    run(items, brands, vocabmod.load(tmp), rules)
    s = score_rows(dev, by_gold, brands)[0].summary()
    sh = shares(subset)
    return {"exact": s["exact"], "ros": s["exact"] + s["shallower"], "harm": s["deeper"] + s["wrong"] + s["wrong_brand"],
            "no_brand": s["no_brand"], "exact_rate": s["exact_rate"], "ros_rate": s["right_or_shallower"],
            "harm_rate": s["harm_rate"], "brand_acc": s["levels"][0]["acc"], "to_agent": sh["to_agent"][1]}

def with_settings(doc, **kw):
    d = copy.deepcopy(doc); d.setdefault("settings", {}).update(kw); return d

def with_strip(doc, *words):
    d = copy.deepcopy(doc); d["strip"] = list(d.get("strip") or []) + [w for w in words if w not in (d.get("strip") or [])]; return d

SUFFIXES = ["candy", "candies", "snacks", "snack", "foods", "food", "co", "company", "inc", "brands", "brand", "usa"]
CANDS = {
    "whole_name": lambda: (with_settings(base_doc, whole_name=True), base_rules, ()),
    "variant_field": lambda: (with_settings(base_doc, variant_field=True), base_rules, ()),
    "variant_field + whole_name": lambda: (with_settings(base_doc, variant_field=True, whole_name=True), base_rules, ()),
    "veto/set-conflict -> shadow (food)": lambda: (base_doc, shadowed(base_rules, "veto/set-conflict"), ()),
    "brand drop suffixes": lambda: (base_doc, base_rules, SUFFIXES),
    "strip += flavored, swedish": lambda: (with_strip(base_doc, "flavored", "swedish"), base_rules, ()),
    "settle/single-name -> shadow (food)": lambda: (base_doc, shadowed(base_rules, "settle/single-name"), ()),
}
only = sys.argv[1:]
b = score(base_doc, base_rules)
print("baseline", json.dumps(b), flush=True)
res = {}
for lbl, mk in CANDS.items():
    if only and lbl not in only:
        continue
    r = score(*mk())
    res[lbl] = r
    print(f"{lbl:40s} d_exact {r['exact']-b['exact']:+5d}  d_ros {r['ros']-b['ros']:+5d}  d_harm {r['harm']-b['harm']:+5d}  "
          f"d_nobrand {r['no_brand']-b['no_brand']:+5d}  exact {r['exact_rate']}  ros {r['ros_rate']}  harm {r['harm_rate']}  "
          f"brand {r['brand_acc']}  to_agent {b['to_agent']}->{r['to_agent']}", flush=True)
Path(ROOT / "runs" / D / "dev_try.json").write_text(json.dumps({"baseline": b, "cands": res}, indent=1), encoding="utf-8")
