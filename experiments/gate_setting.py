"""Sealed gate for one boolean vocab setting: dev gate first, then one logged sealed read; kept -> written into the
domain's vocab settings (old text saved under runs/<d>/proposer/). Same tests as taxo.gate / taxo.propose.

    uv run python experiments/gate_setting.py food shop_brand 8 "shop names the brand's own store"
    uv run python experiments/gate_setting.py food strip+=box,bag 9 "buying words leave names"     # a list += words
"""
import copy, json, re, sys, yaml
from taxo import evaluator
from taxo.propose import Bench, dev_gate, gate_compare, decide, _kpi
domain, key, RND, LABEL = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
dev_only = "--dev-only" in sys.argv
b = Bench(domain)
doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")); rules = evaluator.load(*b.rule_dirs)
cur = b.evaluate(doc, rules)
d2 = copy.deepcopy(doc)
field, add = (key.split("+=", 1)[0], key.split("+=", 1)[1].split(",")) if "+=" in key else (None, None)
if field:
    d2[field] = list(d2.get(field) or []) + [w for w in add if w not in (d2.get(field) or [])]
else:
    d2.setdefault("settings", {})[key] = True
new = b.evaluate(d2, rules)
ok, info = dev_gate(cur, new)
print("dev", "PASS" if ok else "fail", json.dumps(info))
print("dev before", {k: cur["dev"][k] for k in ("exact_rate", "right_or_shallower", "harm_rate", "no_brand")},
      "after", {k: new["dev"][k] for k in ("exact_rate", "right_or_shallower", "harm_rate", "no_brand")})
rec = {"round": RND, "label": LABEL, "setting": key, "dev": info, "dev_before": cur["dev"], "dev_after": new["dev"]}
if ok and not dev_only:
    rows = b.gold.sealed(f"setting gate round {RND}: {LABEL}")
    c = gate_compare(rows, cur["placed"], new["placed"], b.score_brands); c.pop("changes")
    kept, why = decide(c, cur["to_agent"], new["to_agent"])
    rec["sealed"] = {"keep": kept, "why": why, "before": c["before"], "after": c["after"], "better": c["better"],
                     "worse": c["worse"], "touched": c["touched"], "reads_total": b.gold.reads()}
    print("SEALED", "KEPT" if kept else "DROPPED", " | ".join(why))
    for k in ("exact_rate", "right_or_shallower", "harm_rate", "no_brand"):
        print(f"  sealed {k}: {c['before'][k]} -> {c['after'][k]}")
    if kept:
        txt = b.vocab_path.read_text(encoding="utf-8")
        (b.out / f"vocab-before-r{RND}.yaml").write_text(txt, encoding="utf-8")
        if field:       # a one-line flow list: "strip: [a, b]" -> "strip: [a, b, c]  # round N added c"
            line = re.compile(rf"^{field}: \[[^\]\n]*\][^\n]*$", re.M)
            if not line.search(txt):
                raise SystemExit(f"{field} is not a one-line list in {b.vocab_path}; write the kept words by hand")
            txt = line.sub(lambda m: f"{field}: [{', '.join(d2[field])}]      # round {RND} added {', '.join(add)} "
                                     f"(kept on sealed: {LABEL})", txt, count=1)
        else:
            txt = re.sub(r"^settings:\n", f"settings:\n  {key}: true      # round {RND}, kept on sealed: {LABEL}\n",
                         txt, count=1, flags=re.M)
        b.vocab_path.write_text(txt, encoding="utf-8")
        again = b.evaluate(yaml.safe_load(txt), rules)
        print("reload dev exact", again["dev"]["exact"], "candidate", new["dev"]["exact"])
        if again["dev"]["exact"] != new["dev"]["exact"]:
            raise SystemExit("the written vocab does not reproduce the candidate: fix it before the next round")
        cur = again
    _kpi(b, cur, c["after"] if kept else c["before"], RND, f"{key} {'KEPT' if kept else 'DROPPED'}: {LABEL}")
(b.out / f"r{RND:03d}-{field or key}.json").write_text(json.dumps(rec, indent=1, default=str), encoding="utf-8")
