"""Offline check of the proposer's bundle step: replay round 14's fragrance proposals (no Codex call, no sealed
read: sealed_left=0) as round 999, then move the round-999 files to the given folder."""
import json, shutil, sys, yaml
from pathlib import Path
from taxo import evaluator, propose
from taxo.propose import Bench, round_
b = Bench("fragrance")
r14 = json.loads((b.out / "r014.json").read_text(encoding="utf-8"))
props = [{k: x.get(k) for k in ("kind", "label", "shape", "why", "patch")} for x in r14["proposals"]]
propose.ask = lambda b_, text, tag: (props, {"tokens": 0, "secs": 0})
doc = yaml.safe_load(b.vocab_path.read_text(encoding="utf-8")); rules = evaluator.load(*b.rule_dirs)
cur = b.evaluate(doc, rules)
round_(b, 999, doc, rules, cur, [], sealed_left=0)
rec = json.loads((b.out / "r999.json").read_text(encoding="utf-8"))
print("note:", rec.get("note")); print([(x["label"][:60], (x.get("dev") or {}).get("better"), (x.get("dev") or {}).get("worse")) for x in rec["proposals"]])
dest = Path(sys.argv[1]); dest.mkdir(parents=True, exist_ok=True)
for f in b.out.glob("r999*"):
    shutil.move(str(f), dest / f.name)
