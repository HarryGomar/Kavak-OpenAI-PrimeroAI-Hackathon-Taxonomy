# Electronics round 04: first full cycle of the shared loop (`python -m taxo.loop electronics --cycles 1`)

Gold: the owner's 50 random listings (AI pre-labels checked by the owner, 6 changed) + 9 reviewed rows; dev 50, sealed 8.

| Step | Result |
|---|---|
| 1. Loop A, rule phase (Codex proposer -> gate) | 1 proposal (`recognize_singleton_title_brands`): dropped, recall 0.807 -> 0.817 but precision 0.940 -> 0.938. Then the proposer found nothing safe to change. Rules stay at identity v0.5.0. |
| 2. Checkpoint, owner dev gold (n=50) | pipeline (rules + Codex placer): exact 0.78 [0.65-0.87], right or shallower 0.84, harm 0.12 [0.06-0.24] |
| 3. Loop B, shared validator (agent + tools over MCP, card v1), owner gold as reviewer | on 25 gold listings: exact 0.64, harm 0.32; agreement with pipeline 0.72; flag precision 0.29; it found 3 pipeline errors |
| 4. Shared improver | proposed a `model`-kind change (series name vs part number), which the shared A/B only applies for `question` changes: nothing tested |
| Final, one logged sealed read (n=8) | exact 0.75 [0.41-0.93] |

Finding: the shared validator (card v1, seeded from v1-v4 lessons) is weaker on electronics than the earlier batch
validator v4 (exact 0.80, harm 0.12 on the same gold). Next: let the improver's change be expressed as a question,
or seed the card's questions with v4's checklist lines, and A/B it on the owner gold.
