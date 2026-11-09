"""Sealed gate for the food variant step (round 7): the shop's variant label becomes a flavour node under the
product. One logged sealed read, the same tests as taxo.gate / taxo.propose."""
import copy, json, re, yaml
from taxo import evaluator, gold as goldmod
from taxo.propose import Bench, dev_gate, gate_compare, decide, _kpi
RND, LABEL = 7, "variant step: shop variant label as flavour node"
b = Bench("food")
doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")); rules = evaluator.load(*b.rule_dirs)
cur = b.evaluate(doc, rules)
d2 = copy.deepcopy(doc); d2.setdefault("settings", {})["variant_field"] = True
new = b.evaluate(d2, rules)
ok, info = dev_gate(cur, new)
print("dev", "PASS" if ok else "fail", json.dumps(info))
rec = {"round": RND, "label": LABEL, "dev": info, "dev_before": cur["dev"], "dev_after": new["dev"]}
if ok:
    rows = b.gold.sealed(f"variant gate round {RND}: {LABEL}")
    c = gate_compare(rows, cur["placed"], new["placed"], b.score_brands); c.pop("changes")
    kept, why = decide(c, cur["to_agent"], new["to_agent"])
    rec["sealed"] = {"keep": kept, "why": why, "before": c["before"], "after": c["after"], "better": c["better"],
                     "worse": c["worse"], "touched": c["touched"], "reads_total": b.gold.reads()}
    print("SEALED", "KEPT" if kept else "DROPPED", " | ".join(why))
    if kept:
        txt = b.vocab_path.read_text(encoding="utf-8")
        (b.out / f"vocab-before-r{RND}.yaml").write_text(txt, encoding="utf-8")
        txt = re.sub(r"^settings:\n", f"settings:\n  variant_field: true      # round {RND}, kept on sealed: {LABEL}\n",
                     txt, count=1, flags=re.M)
        b.vocab_path.write_text(txt, encoding="utf-8")
        again = b.evaluate(yaml.safe_load(txt), rules)
        print("reload dev exact", again["dev"]["exact"], "candidate", new["dev"]["exact"])
        cur = again
    _kpi(b, cur, c["after"] if kept else c["before"], RND, f"variant step {'KEPT' if kept else 'DROPPED'}: {LABEL}")
(b.out / f"r{RND:03d}-variant.json").write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
print(json.dumps(rec.get("sealed"), indent=1, default=str))
