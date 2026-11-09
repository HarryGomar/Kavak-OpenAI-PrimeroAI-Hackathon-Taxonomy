"""Dev only: 'a shop whose branded listings mostly name one brand sells that brand'. The shop's brand comes from the
pipeline's own brand ladder over ALL listings (no gold); unbranded listings of that shop get it. Scored on dev rows."""
import yaml
from collections import Counter, defaultdict
from taxo import evaluator
from taxo.propose import Bench
b = Bench("food")
ev = b.evaluate(yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")), evaluator.load(*b.rule_dirs))
found = defaultdict(Counter); total = Counter()
for it in b.items:
    if it.id.startswith("gold:"): continue
    total[it.source] += 1
    if it.brand: found[it.source][it.brand] += 1
for MINN, SHARE in ((5, 0.8), (5, 0.9), (10, 0.9), (3, 0.95)):
    shop_brand = {}
    for s, c in found.items():
        (top, n), branded = c.most_common(1)[0], sum(c.values())
        if branded >= MINN and n / branded >= SHARE:
            shop_brand[s] = top
    r = w = 0; wex = Counter()
    for g in b.dev:
        if ev["cls"][g.id] != "no_brand": continue
        it = b.by_gold[g.id]; sb = shop_brand.get(it.source)
        if sb is None: continue
        if sb == g.brand: r += 1
        else: w += 1; wex[(it.source, b.names[sb], b.names[g.brand])] += 1
    print(f"min {MINN} share {SHARE}: shops {len(shop_brand)}, right {r}, wrong {w}  {wex.most_common(5)}")
