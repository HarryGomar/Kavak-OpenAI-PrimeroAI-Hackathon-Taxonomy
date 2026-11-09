"""Which leaf words make food placements wrong or deeper: for each word, the rows where it is the ONLY extra leaf word
(dropping it would make the row right), the rows where it is one of several, and how often it sits in right leaves."""
import yaml
from collections import Counter, defaultdict
from taxo import evaluator
from taxo.lattice.vocab import tokens
from taxo.propose import Bench
b = Bench("food")
ev = b.evaluate(yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")), evaluator.load(*b.rule_dirs))
only, some, ok_leaf, brands_of = Counter(), Counter(), Counter(), defaultdict(set)
for g, it, j in ev["judged"]:
    if j.cls in ("wrong", "deeper"):
        for w in j.extra:
            some[w] += 1; brands_of[w].add(g.brand)
        if len(j.extra) == 1:
            only[next(iter(j.extra))] += 1
    elif j.cls in ("exact", "shallower") and len(it.path) > 1:
        for w in tokens(it.path[-1]):
            ok_leaf[w] += 1
print("word: only-extra rows / extra rows / in right leaves / brands with it as extra / title spread (dev brands)")
for w, n in only.most_common(45):
    print(f"  {w:14s} {n:4d} {some[w]:5d} {ok_leaf[w]:5d} {len(brands_of[w]):4d} {b.spread(w):4d}")
