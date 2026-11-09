"""Dev only: each candidate strip word alone, then the helpful ones together. Plus: which variant labels go wrong."""
import copy, json, sys, yaml
from collections import Counter
from taxo import evaluator
from taxo.lattice.vocab import tokens
from taxo.propose import Bench, dev_gate
b = Bench("food")
doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")); rules = evaluator.load(*b.rule_dirs)
cur = b.evaluate(doc, rules)
# variant labels on placed+variant rows, by class
vc = Counter(); vbad = Counter()
for g, it, j in cur["judged"]:
    if (it.reason or "").endswith("+variant"):
        lab = " ".join(tokens(it.variant_field))
        vc[(lab, j.cls)] += 1
        if j.cls in ("wrong", "deeper"):
            vbad[lab] += 1
print("variant labels most often wrong/deeper:", [(l, n, vc[(l, 'exact')] + vc[(l, 'shallower')]) for l, n in vbad.most_common(15)])
words = sys.argv[1].split(",")
good = []
for w in words:
    d2 = copy.deepcopy(doc); d2["strip"] = list(d2["strip"]) + [w]
    ok, info = dev_gate(cur, b.evaluate(d2, rules))
    print(f"{w:12s} {'PASS' if ok else 'fail'} better {info['better']:4d} worse {info['worse']:4d} exact {info['exact'][0]}->{info['exact'][1]} harm {info['harm_rate'][0]}->{info['harm_rate'][1]} wilson {info['wilson']}", flush=True)
    if info["better"] > info["worse"] and info["exact"][1] >= info["exact"][0]:
        good.append(w)
d2 = copy.deepcopy(doc); d2["strip"] = list(d2["strip"]) + good
ok, info = dev_gate(cur, b.evaluate(d2, rules))
print("together", good, "PASS" if ok else "fail", json.dumps(info))
