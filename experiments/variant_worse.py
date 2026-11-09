import copy, random, yaml
from collections import Counter
from taxo import evaluator
from taxo.gate import RANK
from taxo.propose import Bench
b = Bench("food")
doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")); rules = evaluator.load(*b.rule_dirs)
cur = b.evaluate(doc, rules)
d2 = copy.deepcopy(doc); d2.setdefault("settings", {})["variant_field"] = True
new = b.evaluate(d2, rules)
trans = Counter((cur["cls"][k], new["cls"][k]) for k in cur["cls"] if cur["cls"][k] != new["cls"][k])
print(trans.most_common())
better = sum(RANK[new["cls"][k]] > RANK[c] for k, c in cur["cls"].items()); worse = sum(RANK[new["cls"][k]] < RANK[c] for k, c in cur["cls"].items())
print("better", better, "worse", worse)
gold = {g.id: g for g in b.dev}
worse_rows = [k for k, c in cur["cls"].items() if RANK[new["cls"][k]] < RANK[c]]
lv = Counter(gold[k].extra.get("level") for k in worse_rows); print("gold level of worse rows", lv.most_common())
lvb = Counter(gold[k].extra.get("level") for k, c in cur["cls"].items() if RANK[new["cls"][k]] > RANK[c]); print("gold level of better rows", lvb.most_common())
src = Counter(b.by_gold[k].source for k in worse_rows); print("sources worse", src.most_common(6))
srcb = Counter(b.by_gold[k].source for k, c in cur["cls"].items() if RANK[new["cls"][k]] > RANK[c]); print("sources better", srcb.most_common(6))
for k in random.Random(3).sample(worse_rows, 12):
    it = b.by_gold[k]; print(f"  {it.title[:60]!r} | var={it.variant_field!r} | ours={' > '.join(new['placed'][k]['path'])} | gold={' > '.join(gold[k].expected_path)} | {cur['cls'][k]}->{new['cls'][k]}")
