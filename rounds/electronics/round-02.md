# Electronics round 02: validator v1 -> v3, first gated rule change

Owner feedback (review r01): the product type belongs in the path, so paths are now Brand / type / model / variant
(type = the category step, a browse level; product ids unchanged). The manufacturer part number is the product name.

## Validator versions (same 150 listings; scored on the owner's review gold, dev split, 9 rows)

| Version | What changed | Exact on gold | Harm | Flag precision | Agrees with pipeline (100 fresh) | Wall s | Input tokens | Output tokens |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| v1 | baseline prompt | 2/9 | 0.0 | 0.143 | 83 | 119.96 | 174,760 | 24,395 |
| v2 | reads the model field as evidence; seeded with the listing brand | 3/9 | 0.0 | 0.143 | 80 | 102.11 | 146,967 | 24,896 |
| v3 | v2 + candidates ranked on title + model field; check accepts model-field names | 6/9 | 0.111 | 0.333 | 89 | 120.06 | 159,593 | 24,818 |

The v1 failures were a query problem, not the model: the validator never saw the existing product for a part number that
was only in the model field, and the code check rejected names not written in the title. Flag precision is still low
(few rows; measured against the pipeline's previous placements), so v3's silver is not trusted yet (SPEC §8).

Scorer fix: the team's fragrance scorer drops tokens that start with a digit (sizes), which erased part numbers;
electronics now scores with `loop.ejudge` (segments after the brand compared as one string; product type scored apart).

## Rule gates (rules only, no agent; dev = owner gold dev + benchmark train pairs; sealed read once only if dev passes)

| Change | Decision | Listings changed | Dev gold harm | Dev pairs precision / recall |
|---|---|---:|---|---|
| field-part-capacity-and-own-text | **drop (dev)** | 55 | 0.111 -> 0.111 | 0.94/0.8057 -> 0.9342/0.8068 |
| field- | **drop (dev)** | 33 | 0.111 -> 0.0 | 0.94/0.8057 -> 0.9338/0.8057 |
| field- | **drop (dev)** | 33 | 0.111 -> 0.0 | 0.94/0.8057 -> 0.9338/0.8057 |
| field- | **drop (dev)** | 33 | 0.111 -> 0.0 | 0.94/0.8057 -> 0.9338/0.8057 |
| field-spec-only | **drop (dev)** | 33 | 0.111 -> 0.0 | 0.94/0.8057 -> 0.9338/0.8057 |
| field-own-text-only | **drop (dev)** | 24 | 0.111 -> 0.0 | 0.94/0.8057 -> 0.9404/0.8068 |
| field-both | **drop (dev)** | 55 | 0.111 -> 0.0 | 0.94/0.8057 -> 0.9342/0.8068 |
| field-own-text-when-model-field-agrees | **keep** | 24 | 0.111 -> 0.0 | 0.94/0.8057 -> 0.9404/0.8068 |

Kept: identity rules v0.5.0 `field_confirm_in_own_text` (a model-field part number found after "with ..." counts when the
merchant's model field states the same code; the whole-graph check was narrowed to exactly that case).
Dropped: `field_reject_spec_tokens` (lowered pair precision 0.940 -> 0.934). Earlier gate rows tested broken variants
of the same switch while the scorer and check were being fixed; only the last row decided.

## Cost so far (all Codex calls in the ledger)

| Role | Calls | Cached | Seconds (sum) | Input tokens | Cached input | Output | Reasoning |
|---|---:|---:|---:|---:|---:|---:|---:|
| validator_v1 | 5 | 0 | 417 | 174,760 | 76,800 | 24,395 | 12,921 |
| validator_v2 | 5 | 0 | 389 | 146,967 | 59,136 | 24,896 | 12,801 |
| validator_v3 | 5 | 0 | 455 | 159,593 | 84,480 | 24,818 | 12,655 |

Full hash-chained ledger: [`round-02-ledger.json`](round-02-ledger.json). Gold is still thin (9 dev rows from one review);
the 50 + 50 checked gold rows are pending from the owner.
