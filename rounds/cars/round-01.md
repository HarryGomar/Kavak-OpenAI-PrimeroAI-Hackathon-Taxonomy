# Cars round 01: baseline loop: placer, validator v1->v2, owner-directed make fixes, gate

Rules `identity.yaml`+`vocab.yaml` 0.3.0 (`a28e0476223f`) on 8,637 listings
(catalogue `f4067740e8a1`). Agents run through the local Codex CLI (ChatGPT login,
`gpt-6-astra`; placer at medium effort, validator at high). Data stays outside the repo: this file and the CSV carry ids,
levels and tree paths only. Every Codex call, gate decision and sealed read is in `runs/cars/ledger.jsonl` (hash-chained,
outside Git).

## 1. Where listings were settled (SPEC §4)

| Step | Listings | Share |
|---|---:|---:|
| parse | 88 | 1.0% |
| brand | 40 | 0.5% |
| registry | 381 | 4.4% |
| lattice | 2,355 | 27.3% |
| agent | 5,771 | 66.8% |
| still routed | 2 | 0.0% |

Pipeline stage seconds: {"load": 0.029, "parse_brand_registry_lattice": 0.812, "route": 0.083, "graph": 0.12, "agent": 0.07, "checks": 0.068, "gold_and_write": 0.117} (rules, no agent: about 1.2 s for all listings).

## 2. Placer (step 6, Codex)

| Run | Codex calls | Listings sent | Accepted by code | Seconds (sum of calls) | Tokens |
|---|---:|---:|---:|---:|---:|
| full run on rules 0.2.0 | 276 (+15 cached) | 5802 | 5740 | 7870.6 | 3,062,646 (older count: total "tokens used") |
| rerun on rules 0.3.0 | 4 | 71 | 5790 total (5720 reused: input unchanged) | 92.8 | 92,444 (cached input 61,440) |

Answers on rules 0.2.0: {"node": 5709, "new_version": 76, "stop": 17}. The placer mostly confirms the rules' own deeper candidate; that is
why it must be measured on random gold before step 6 is trusted.

## 3. Validator (Loop B), v1 -> v2

| | v1 (raw JSON cut at 700 chars) | v2 (identifying fields, uncut, + catalogue versions of the named model) |
|---|---|---|
| vs pipeline, random gold sample (50) | {"agree": 50} | {"agree": 49, "disagree": 1} |
| vs pipeline, fresh random (100) | {"agree": 98, "disagree": 2} | {"agree": 99, "disagree": 1} |
| vs pipeline, imported gold (39) | {"agree": 38, "disagree": 1} | {"agree": 38, "disagree": 1} |
| on dev gold (taxo/score.py) | {"label_holds_dataspec": "30/36", "exact": 14, "deeper": 16, "wrong": 4, "model_year": "31/32"} | {"label_holds_dataspec": "30/36", "exact": 13, "deeper": 17, "wrong": 4, "model_year": "32/32"} |
| flags on gold (precision) | {"flags": 1, "pipeline_really_wrong": 0, "precision": 0.0} | {"flags": 1, "pipeline_really_wrong": 0, "precision": 0.0} |
| Codex calls / seconds / tokens | 0 fresh in this ledger (earlier v1 calls predate it: 14 calls, 634 s, ~316k "tokens used") | 13 / 436.3 s / 265,843 (cached input 180,992) |

The validator's "wrong" rows on gold are mostly spelling ("Mercedes-Benz GLB" vs gold "Clase GLB"): taxo/score.py
compares words. Its one flag on gold is the Jeep "Rubicon 392 Final Edicion" placed on catalogue version "Rubicon 2.0L
Turbo 4x4": the imported gold calls that Correct, the validator disagrees, and a person must settle it (review item).
Query problem found and fixed in v2: v1 read raw JSON cut at 700 characters, so long Seminuevos/Kavak records lost
version and gearbox fields. v2 needed fewer seconds and tokens for the same 189 listings.

## 4. Rules (Loop A)

Changes made before the gate (owner-directed, "fix make errors first"; 0.2.0 -> 0.3.0, from validator flags):
1. `brand/group-title-model-owner`: "CHRYSLER ATTITUDE" with no make field -> Dodge (catalogue files Attitude under Dodge only), 5 listings.
2. `brand/rebrand-by-year`: "Dodge Ram <model>" of model year 2010+ -> Ram > <model>, 13 listings.

Gate on dev gold (37 rows, rules only), then one logged sealed read (2 rows; sealed reads so far: 2):

| Candidate | Verdict | Gold rows touched | Delta (holds / harm / routed / version nodes) |
|---|---|---:|---|
| trim-noise-colours-stock-codes | untestable: touches no gold row (stays a proposal) | 0 | 0 / 0 / -5 / -12 |
| catalogue-version-number-guard | dropped: gold score falls or nothing improves | 2 | -1 / 1 / 2 / 2 |

Kept: []. Sealed: {"holds": 2, "n": 2, "harm": 0, "exact": 1, "years": [2, 2], "rejects_held": "0/0", "routed": 5792, "version_nodes": 5161}.

## 5. Scores on dev gold (37 rows, all imported reviews: NOT random)

Pipeline (final): {"accept_rows": 36, "exact": 28, "shallower": 1, "deeper": 7, "wrong": 0, "wrong_brand": 0, "no_brand": 0, "reject_rows": 0, "rejects_held": 0, "label_holds_dataspec": "35/36", "model_year": "32/32", "not_scored": 0}

## 6. For a person (review page, gold)

- Review: `runs/cars/loop-r01/review.html` ({"disagreements": 2, "spot_checks": 15}); exports `review-r01.yaml` (provenance: review).
- Blind random gold: `runs/cars/gold-r01/labeling-quick.html` (one click each) exports `round-01.yaml`.

## 7. Rule candidates to distill next

1. Catalogue version needs its distinctive words (the number guard): dropped by this gold, but the gold row it breaks
   is itself in question (Rubicon 392). Re-gate after the review settles that row.
2. Trim noise (colours, stock codes): cuts 5 routed listings and 12 version nodes; untestable until gold touches it.
3. A single trim letter (Kia Rio "L") is a version: today "l" is a generic token and the pipeline stops at the year.
4. Placer rubber-stamping: measure step-6 answers on random gold before trusting them.
