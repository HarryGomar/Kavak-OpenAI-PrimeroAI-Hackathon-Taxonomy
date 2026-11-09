import random, yaml
from collections import Counter
from taxo import evaluator, gold as goldmod
from taxo.propose import Bench
b = Bench("food")
doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8"))
ev = b.evaluate(doc, evaluator.load(*b.rule_dirs))
rows = [(g, b.by_gold[g.id]) for g in b.dev if ev["cls"][g.id] == "shallower" and b.by_gold[g.id].step == "lattice"]
print(len(rows), "shallower lattice placements on dev")
for g, it in random.Random(5).sample(rows, 18):
    resid = [w for w in it.key.split() if w not in (it.cluster or "").split()]
    print(f"{it.title[:80]!r}\n    key={it.key!r} cluster={it.cluster!r} resid={resid}\n    gold={' > '.join(g.expected_path)}")
