import random, yaml
from collections import Counter
from taxo import evaluator
from taxo.propose import Bench
b = Bench("food")
doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")); ev = b.evaluate(doc, evaluator.load(*b.rule_dirs))
nb = [(g, b.by_gold[g.id]) for g in b.dev if ev["cls"][g.id] == "no_brand"]
print(len(nb), "dev rows with no brand")
print("sources:", Counter(it.source for g, it in nb).most_common(12))
print("brand field present:", sum(bool(it.brand_field) for g, it in nb))
by_src = Counter((it.source, b.names[g.brand]) for g, it in nb)
print("top (shop, gold brand):", by_src.most_common(15))
for g, it in random.Random(2).sample(nb, 12):
    print(f"  {it.source:24s} bf={it.brand_field!r:22.22} | {it.title[:60]!r} | gold brand={b.names[g.brand]!r}")
