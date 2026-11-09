"""Where food's dev errors come from after rounds 7-8: class x step x reason, depth of ours vs gold, and examples."""
import random, yaml
from collections import Counter
from taxo import evaluator
from taxo.propose import Bench
b = Bench("food")
ev = b.evaluate(yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")), evaluator.load(*b.rule_dirs))
print("dev", {k: ev["dev"][k] for k in ("accept_rows", "exact", "shallower", "deeper", "wrong", "wrong_brand", "no_brand")})
c = Counter(); depth = Counter(); ex = {}
for g in b.dev:
    it = b.by_gold[g.id]; cls = ev["cls"][g.id]
    key = (cls, it.step, (it.reason or "-").split(":")[0], "routed" if it.route else "")
    c[key] += 1
    if cls in ("wrong", "deeper", "exact", "shallower"):
        depth[(cls, len(it.path) - 1, len(g.expected_path) - 1)] += 1
    ex.setdefault(key, []).append((it.title, it.path, g.expected_path, it.variant_field))
for k, n in c.most_common(18):
    print(f"{n:5d}  {k}")
print("\n(class, our depth, gold depth):", depth.most_common(16))
rng = random.Random(4)
for key in [k for k, _ in c.most_common(18) if k[0] in ("wrong", "deeper")][:5]:
    print(f"\n== {key}")
    for t, p, gp, v in rng.sample(ex[key], min(7, len(ex[key]))):
        print(f"  {t[:70]!r}\n      ours {p}  gold {gp}  var={v!r}")
