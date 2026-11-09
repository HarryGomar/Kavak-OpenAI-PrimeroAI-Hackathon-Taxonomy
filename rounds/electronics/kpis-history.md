# Electronics KPI history: the two headline metrics per round (owner dev gold, 9 rows; 95% Wilson intervals)


| loop/round | label | rules | rules right (exact) | rules not harmful | validator | validator exact | validator not harmful | flag precision |
|---|---|---|---|---|---|---|---|---|
| A/0 | baseline rules | 0.4.0 | 8/9 = 0.89 [0.56-0.98] | 8/9 = 0.89 [0.56-0.98] | - | - | - | - |
| B/1 | validator v1 | 0.4.0 | 8/9 = 0.89 [0.56-0.98] | 8/9 = 0.89 [0.56-0.98] | v1 | 2/9 = 0.22 [0.06-0.55] | 9/9 = 1.00 [0.70-1.00] | 1/7 = 0.14 [0.03-0.51] |
| B/2 | validator v3 (query fix) | 0.4.0 | 8/9 = 0.89 [0.56-0.98] | 8/9 = 0.89 [0.56-0.98] | v3 | 6/9 = 0.67 [0.35-0.88] | 8/9 = 0.89 [0.56-0.98] | 1/3 = 0.33 [0.06-0.79] |
| A/2 | rule kept: field part in own text | 0.5.0 | 8/9 = 0.89 [0.56-0.98] | 9/9 = 1.00 [0.70-1.00] | v3 | 6/9 = 0.67 [0.35-0.88] | 8/9 = 0.89 [0.56-0.98] | 0/3 = 0.00 [0.00-0.56] |
| A/3 | auto: 3 proposals dropped | 0.5.0 | 8/9 = 0.89 [0.56-0.98] | 9/9 = 1.00 [0.70-1.00] | v3 | 6/9 = 0.67 [0.35-0.88] | 8/9 = 0.89 [0.56-0.98] | 0/3 = 0.00 [0.00-0.56] |
| B/3 | auto: validator v4 kept | 0.5.0 | 8/9 = 0.89 [0.56-0.98] | 9/9 = 1.00 [0.70-1.00] | v4 | 8/9 = 0.89 [0.56-0.98] | 8/9 = 0.89 [0.56-0.98] | 0/2 = 0.00 [0.00-0.66] |

Rules = steps 1-5 only (no agent). Validator = its own blind label on the same gold listings. Flag precision = when the
validator disagrees with the rules, how often the rules were actually wrong (falls as the rules get fixed).
Gold is 9 reviewed listings (hand-picked disagreements), so intervals are wide; the 50 random owner-checked rows replace it.
Regenerate: `uv run python -m domains.electronics.kpis history` (rows in runs/electronics/kpis.jsonl, taxo.kpis format).
