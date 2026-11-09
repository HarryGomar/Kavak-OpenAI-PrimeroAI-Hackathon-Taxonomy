# Final numbers (2026-11-09): electronics and cars

All rates on the owner's gold (AI pre-labels checked by the owner, random samples, dev split), 95% Wilson intervals.
"Right" = exactly the owner's path. "Not harmful" = right or correctly shallower (never a wrong brand, model or
deeper-than-supported node).

## Electronics (133 dev gold listings; 23 more sealed)

### Rules (Loop A)
| Rules version | Round | Right | Not harmful |
|---|---|---|---|
| v0.4.0 baseline | 00 | 101/133 = 76% [68-82] | 121/133 = 91% [85-95] |
| v0.5.0 (+ model-field part number after "with ...") | 02 | 101/133 = 76% [68-82] | 122/133 = 92% [86-95] |
| v0.6.0 (+ compatibility brand after "for ..."; lens focal range is not a model) | 05 | 102/133 = 77% [69-83] | 124/133 = 93% [88-96] |
| **v0.6.0 + Codex placer (full pipeline)** | 05 | **109/133 = 82% [75-88]** | 123/133 = 92% [87-96] |

Gate decisions: 3 rule changes kept, 6 dropped (4 Codex proposals, 2 by hand), each on dev gold + benchmark train
pairs, then one logged sealed read. Benchmark same-product pairs (validation): precision 0.95, recall 0.75.

### Validator (Loop B, shared validator agent with tools on the Codex runner)
| Setup | On 50 gold (round 05 A/B) | On 133 gold (final re-check) |
|---|---|---|
| v1 (maker, product type, model-number questions) | right 34/50 = 68%, not harmful 76% | right 99/133 = 74% [66-81], not harmful 83% |
| **v2** (+ bundle/pack question, reuse existing products) | right 38/50 = 76%, not harmful 78% | **right 100/133 = 75% [67-82], not harmful 83% [76-89]** |
v2 stays (not worse). Honest reading: v2's gain on 50 rows shrank to 1 row on 133, so it is not proven; the earlier
batch validator (v4, round 03) reached 80% on 50 rows but was not re-run on 133.

## Cars (100 random gold listings; from the cars session, rounds/cars/round-03.md on branch cars-pipeline)
| System | Right | Not harmful |
|---|---|---|
| Rules 0.1.0 (start) | 13/100 [8-21] | 97 |
| Rules 0.2.0 (after the first 20 owner reviews) | 84/100 [76-90] | 96 |
| Rules now (0.3.0 + 4 learned edits) | 88/100 [80-93] | 98 |
| Rules + placer now | 88/100 [80-93] | 99 |
| Validator v2 | 90/100 [83-94] | 98 |
Codex proposer kept 2 of 6 edits in round 03; validator v3 was rejected (more right, but more harmful).

## What is and is not proven
- Proven by the gold: cars rules improved hugely from the start (13% -> 88% right); electronics rules are 76-77% right
  alone and 82% with the Codex placer, with harm low (7-9%).
- Not proven: the late, small rule and validator changes in both domains (1-4 rows) sit inside the intervals.
- Gold caveat: rows are AI pre-labels the owner checked (electronics: 9 of 150 changed; cars round 02: 0 of 50
  changed), so they measure agreement with owner-confirmed labels, not fully independent blind labels.
