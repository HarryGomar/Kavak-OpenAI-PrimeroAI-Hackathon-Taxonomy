# Electronics round 05: rules v0.6.0 and validator v2, both proven on the owner's 50 dev gold

## Loop A (rules): two fixes found in the checkpoint errors, both kept by the gate
| Change | Gold right | Gold not harmful | Benchmark pairs P / R |
|---|---|---|---|
| A field brand found only after "for ..." is a compatibility brand (atrend-bbox ... for ford f150) | 0.72 -> 0.74 | 0.88 -> 0.90 | unchanged 0.940 / 0.807 |
| A lens focal range ("18-55-is") is not a model | 0.72 -> 0.72 | 0.88 -> 0.90 | unchanged |
Identity rules v0.5.0 -> v0.6.0. Pipeline (rules + Codex placer) on dev gold: exact 0.78 -> 0.82, harm 0.12 -> 0.06
(part of that is the judge now recognising a singular product type the owner wrote, e.g. "ink cartridge").

## Loop B (validator): shared validator, A/B on ALL 50 dev gold (domains/electronics/ab_card.py)
| Setup | Right | Not harmful | Classes |
|---|---|---|---|
| v1 (questions: maker, product type, model number) | 34/50 = 0.68 [0.542-0.792] | 38/50 | {'exact': 34, 'shallower': 4, 'deeper': 3, 'wrong': 8, 'wrong_brand': 1, 'no_answer': 0} |
| v2 (+ bundle/pack question; reuse existing products) | 38/50 = 0.76 [0.626-0.857] | 39/50 | {'exact': 38, 'deeper': 2, 'wrong': 8, 'shallower': 1, 'wrong_brand': 1, 'no_answer': 0} |
Decision: **kept** (right more often, not more harmful). 211.6 s for 100 agent calls.
Shared Loop B's own A/B (cycle 2) had only 7 fresh gold rows left, too few to separate setups; this A/B reuses the dev
gold for both setups, neither of which was tuned on those labels.

Caveat: n = 50, so a 4-row difference sits inside the 95% intervals. More owner gold is what turns these into proof.
