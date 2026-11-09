"""Dev only: on the agent-baseline sample, rows where the agent alone is right and the rules are not (and the reverse),
by the rules' class and step, with examples. Uses the cached agent answers; reads no sealed gold."""
import json, random, sys, yaml
from collections import Counter
from taxo import evaluator, score
from taxo.core.config import RUNS_DIR
from taxo.lattice.vocab import tokens
from taxo.propose import Bench
d = sys.argv[1]
b = Bench(d)
ev = b.evaluate(yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")), evaluator.load(*b.rule_dirs))
cache = {json.loads(x)["id"]: json.loads(x) for x in open(RUNS_DIR / d / "agent_baseline" / "answers.jsonl", encoding="utf-8")}
brands = b.score_brands
wins, losses, ex = Counter(), Counter(), {}
for g in b.dev:
    it = b.by_gold[g.id]
    ans = cache.get(it.id)
    if not ans: continue
    bt = {t for r in brands.runs(g.brand) for t in r}
    slug = brands.exact(ans["brand"]) or brands.lead(tokens(ans["brand"])) or "?"
    at, gt = tokens(ans["brand"]), tokens(brands.names[g.brand])
    if slug != g.brand and at and (gt[:len(at)] == at or at[:len(gt)] == gt): slug = g.brand
    aj = score.judge(slug, [brands.names.get(slug, ans["brand"])] + ans["path"], g.brand, g.expected_path, bt)
    rj = score.judge(it.brand, it.path, g.brand, g.expected_path, bt)
    key = (rj.cls, it.step, (it.reason or "-").split(":")[0], "routed" if it.route else "")
    if aj.cls == "exact" and rj.cls != "exact":
        wins[key] += 1; ex.setdefault(key, []).append((it.title, it.path, ans["path"], g.expected_path))
    if rj.cls == "exact" and aj.cls != "exact":
        losses[(aj.cls,)] += 1
print("agent exact, rules not:", sum(wins.values())); [print(f"  {n:3d} {k}") for k, n in wins.most_common(10)]
print("rules exact, agent not:", sum(losses.values()), dict(losses))
for k, _ in wins.most_common(4):
    print("==", k)
    for t, p, ap, gp in ex[k][:6]:
        print(f"  {t[:70]!r}\n     rules {p}  agent {ap}  gold {gp}")
