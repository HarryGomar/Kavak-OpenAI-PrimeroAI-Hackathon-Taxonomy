# Electronics round 03: Loop A and Loop B run by Codex, decided by the gate

## Loop A (rules): Codex proposer -> gate
| # | Proposal | Decision | Listings changed | Dev gold harm | Dev pairs precision / recall |
|---|---|---|---:|---|---|
| 1 | `prefer_source_model_fields`: XM and Polaroid false splits share identical model fields but select different title identifiers. Requiring ti | **drop (dev)** | 24 | [0.0, 0.111] | [0.9404, 0.94] / [0.8068, 0.8057] |
| 2 | `allow_three_character_models`: The four-character minimum excludes short manufacturer models such as H17, causing identical products to fall  | **drop (dev)** | 99 | [0.0, 0.0] | [0.9404, 0.925] / [0.8068, 0.8177] |
| 3 | `tighten_sibling_suffix_aliasing`: Repeated Panasonic false merges collapse distinct suffix-bearing identifiers to dmc-fh5. Disabling the generic | **drop (dev)** | 3 | [0.0, 0.0] | [0.9404, 0.9404] / [0.8068, 0.8068] |

Stopped after 3 drops in a row; rules stay at identity v0.5.0. Proposer cost: 60,629 input tokens, 133 s.

## Loop B (validator): Codex improver -> re-label -> score on dev gold

Validator v4 (from v3): **kept**. Exact on dev gold 0.667 -> 0.889, harm 0.111 -> 0.111.
Checklist lines added:
- Treat included accessories or upgrade wording as evidence for matching kit candidates; do not reject bundles solely because packaging differs.
- Allow multipacks to match explicitly identified constituent candidates when no pack candidate fits and no distinguishing product attributes conflict.
- Choose only supplied candidates; prefer an explicitly supported family node over an inferred exact model absent from the candidate set.

Improver cost: 18,347 input tokens; re-labelling with v4: 159,939 input tokens.
Decisions and evidence: `domains/electronics/identity-learned.yaml`, `domains/electronics/validator.yaml`, ledger.
