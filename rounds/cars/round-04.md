# Cars round 04: Loop A on silver: validator v2 froze 500 fresh labels; 3 proposals, none kept; dev-gold checkpoint unchanged

Loop A on SILVER (main's design): the frozen validator v2 labelled 500 fresh listings (never gold, never
sampled, never labelled before). The Codex proposer read rules-vs-silver disagreements and proposed one whitelisted edit
at a time; each was kept only if, on silver, more listings agree exactly, none more are harmful, and catalogue-level
precision (listings the rules put on a catalogue version that agree with silver) does not fall. After the phase, ONE
checkpoint on dev gold: the phase is rolled back if gold right falls or gold harm rises. Then one logged sealed read.

## Before / after

| Measure | Before | 95% CI | After | 95% CI |
|---|---:|---|---:|---|
| silver agreement, rules only (exact vs validator v2) | 434/500 (87%) | 84%–89% | 434/500 (87%) | 84%–89% |
| random gold right, rules only | 88/100 (88%) | 80%–93% | 88/100 (88%) | 80%–93% |
| random gold not harmful, rules only | 98/100 (98%) | 93%–99% | 98/100 (98%) | 93%–99% |
| random gold right, rules + placer | 88/100 (88%) | 80%–93% | 88/100 (88%) | 80%–93% |
| dev gold checkpoint (all gold sets, gate rows) | 170/194 (88%) | 82%–92% | 170/194 (88%) | 82%–92% |

Silver harm: 7 → 7. Catalogue precision on silver: 0.077 → 0.077.
Dev gold harm: 10 → 10. Phase rolled back: **False**. Sealed after the phase:
{"holds": 23, "n": 34, "harm": 6} (sealed reads so far: 7).
"Random gold" = the 100 random rows (round-01 + round-02), scored with the cars judge.

## Decisions (every proposal)

| Edit | Verdict | Silver listings touched | Silver agree | Silver harm | Catalogue precision | Ops | Why (one line) |
|---|---|---:|---|---|---|---|---|
| Normalize Nissan NV350 Urvan to Urvan | dropped on silver | 1 | 434 → 434 | 7 → 7 | 0.077 → 0.077 | `[{"op": "add_alias", "path": "models.aliases.nissan", "value": "nv350 urvan=urvan"}]` | The listing explicitly names Urvan; a make-scoped alias consolidates the NV350-prefixed name under the supported nameplate. |
| Normalize Mini Cooper Convertible to Cooper | dropped on silver | 1 | 434 → 434 | 7 → 7 | 0.077 → 0.077 | `[{"op": "add_alias", "path": "models.aliases.mini", "value": "cooper convertible=cooper"}]` | The listing explicitly identifies Convertible as its body style, supporting Cooper as the nameplate |
| Treat generic Pick Up model values as placeholders | dropped on silver | 1 | 434 → 434 | 7 → 7 | 0.077 → 0.077 | `[{"op": "append", "path": "models.placeholders", "value": "pick up"}]` | The Nissan listing repeats its Pickup body type as the model and supplies no distinct nameplate |

Kept edits are in `domains/cars/identity-learned.yaml` with `status`, a one-line `why` and their evidence counts
(silver agree/harm before→after, silver touched, catalogue precision, the gold dev checkpoint).

## Cost (ledger since the phase started)

| Role | Codex calls | Cache hits | Seconds (sum of calls) | Listings | Tokens |
|---|---:|---:|---:|---:|---|
| proposer_silver | 4 | 0 | 50.1 | 0 | 82,262 in (30,720 cached) / 874 out |
| validator_v2 | 34 | 0 | 1033.3 | 500 | 618,583 in (528,000 cached) / 57,320 out |

Ledger events: {"codex_call": 38, "codex_batch": 1, "silver_labelled": 1, "phase_start": 1, "phase_decision": 3, "phase_end": 1}. Phase wall time 60.9 s (rules evaluations are about 1 s each).

## Reading

- Silver is not saturated: rules agree exactly with validator v2 on 434/500 (87%), but the proposer's three edits each
  fixed a single listing's spelling (NV350 Urvan, Cooper Convertible, "Pick Up" placeholder) and did not raise
  agreement under the exact judge, so the silver gate dropped them; the proposer then had nothing more in the whitelist.
- Most remaining silver disagreements are version wording (the validator writes the full stated trim with gearbox and
  engine; the rules' catalogue versions use the catalogue's short names). Catalogue-level precision against silver is
  0.077 for that reason: it measures wording, not wrong cars, and is a weak guard until versions are compared by
  catalogue identity rather than words.
- Next distillable lever is outside the current whitelist: a version-equivalence rule (catalogue short name = stated
  trim when the catalogue version's words are a subset and engine/gearbox agree).
- Loop C: 21 round records in memory/rounds/cars/ (counts and rates only), tagged with shared lesson ids where the shape
  matches electronics (reference-brand-is-not-the-maker, sibling-part-numbers-stay-apart, short-model-codes,
  spec-tokens-are-not-model-names, validator-reads-structured-fields).
