"""Dev only: food rows still without a brand. Does a known brand's name sit in the title (several brands = ambiguous),
in the URL, or nowhere? And would 'the earliest, then longest, brand name in the title' pick the gold brand?"""
import yaml
from collections import Counter
from taxo import evaluator
from taxo.parse import Brands
from taxo.propose import Bench
from taxo.lattice.vocab import tokens
b = Bench("food")
doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8"))
ev = b.evaluate(doc, evaluator.load(*b.rule_dirs))
br = Brands(b.names, tuple(doc.get("brand_drop_suffixes") or ()))
c = Counter(); pick = Counter(); ex = []
for g in b.dev:
    if ev["cls"][g.id] != "no_brand": continue
    it = b.by_gold[g.id]; toks = tokens(it.title)
    hits = {}
    for a in br._by_len:
        for i in range(len(toks) - len(a) + 1):
            if toks[i:i + len(a)] == a:
                s = br.alias[a]
                hits[s] = min(hits.get(s, (99, 0)), (i, -len(a)))
    gold_in = g.brand in hits
    c[("hits", min(len(hits), 3), "gold among them" if gold_in else "gold not in title")] += 1
    if len(hits) >= 2:
        best = min(hits, key=lambda s: hits[s])
        pick[best == g.brand] += 1
        if len(ex) < 8: ex.append((it.title[:70], sorted(b.names[s] for s in hits), b.names[g.brand]))
for k, n in sorted(c.items(), key=lambda kv: -kv[1]): print(n, k)
print("earliest-then-longest picks gold:", dict(pick))
for e in ex: print(" ", e)
