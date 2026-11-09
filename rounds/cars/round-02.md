# Cars round 02: random gold eval; automatic rules loop (2 kept); validator improver (v3 rejected)

Rules 0.3.0 + 2 learned (`8004662c5fe4`): `identity.yaml` + `vocab.yaml` + `identity-learned.yaml`
(edits kept by the gate). Gold: `round-01.yaml` (50 random listings, 10 per source;
provenance {"ai_prelabel_checked": 50}: Opus pre-labels checked by Diego, so not fully blind; every row compare
{"exact": 50}), plus the owner's A/B review (review-r01, provenance review) and the imported round-0
reviews for the gate. Scored with the cars judge (`domains/cars/judge.py`: make, model, year, version incl. engine size
and gearbox), not taxo/score.py (it drops digit tokens). Intervals are 95% Wilson.

Owner decision this round: "CHRYSLER ATTITUDE SE CVT 2024" is a Dodge (gold row changed by Diego, noted in its `why`).

## 1. Headline: random gold (n = 50)

| System | Right | 95% CI | Not harmful | 95% CI | Validator flags right |
|---|---:|---|---:|---|---|
| rules 0.1.0 (rules only) | 6/50 (12%) | 6%–24% | 48/50 (96%) | 86%–99% |  |
| rules 0.2.0 (rules only) | 44/50 (88%) | 76%–94% | 48/50 (96%) | 86%–99% |  |
| rules 0.3.0 + 2 learned (rules only) | 46/50 (92%) | 81%–97% | 49/50 (98%) | 90%–100% |  |
| rules 0.3.0 + 2 learned settled (supported only) | 13/50 (26%) | 16%–40% | 49/50 (98%) | 90%–100% |  |
| rules+placer 0.2.0 | 44/50 (88%) | 76%–94% | 48/50 (96%) | 86%–99% |  |
| rules+placer 0.3.0 + 2 learned | 46/50 (92%) | 81%–97% | 49/50 (98%) | 90%–100% |  |
| validator v1 | 49/50 (98%) | 90%–100% | 50/50 (100%) | 93%–100% | 0/0 |
| validator v2 | 47/50 (94%) | 84%–98% | 50/50 (100%) | 93%–100% | 1/1 |

"Right" = the gold path holds (exact compare: a deeper answer fails). "Not harmful" = right, or correct but shallower /
version missing a word; never a wrong make, model, year or version. "Validator flags right" = of the listings where the
validator disagrees with rules+placer, how many gold says rules+placer got wrong.

## 2. Loop A, automatic (Codex proposer + gate)

Gate: rules only on dev gold (105 rows), kept only if it touches gold, holds no fewer rows, adds no harm and
holds more (or routes fewer); then one logged sealed read that must not fall. Sealed reads so far: 4.

| Change | From | Verdict | Dev rows touched | Delta (holds, harm, routed, version nodes) | Sealed |
|---|---|---|---:|---|---|
| version-label-gearbox | queued (human review) | kept | 13 | {"holds": 6, "harm": -3, "routed": 0, "version_nodes": 0} | {"rows": 7, "before": 6, "after": 6, "harm": 1, "reads_total": 3} |
| trim-typo-to-catalogue | queued (human review) | kept | 2 | {"holds": 1, "harm": -1, "routed": 0, "version_nodes": -2} | {"rows": 7, "before": 6, "after": 6, "harm": 1, "reads_total": 4} |
| catalogue-version-number-guard | queued (human review) | dropped on dev | 2 | {"holds": -1, "harm": 1, "routed": 2, "version_nodes": 2} | - |
| trim-generic-4wd | codex proposer | untestable: touches no gold row | 0 | {"holds": 0, "harm": 0, "routed": -8, "version_nodes": -7} | - |

Kept: ["version-label-gearbox", "trim-typo-to-catalogue"]. Dev after: {"holds": 101, "n": 105, "harm": 1}.

## 3. Validator improver (Codex)

{
 "from_version": 2,
 "candidate_version": 3,
 "lines": [
  "Validate advertised trims and powertrain aliases against the Mexican-market make–model–year catalog before assigning its canonical version label.",
  "Preserve body style, cab configuration, and conversion descriptors when extracting the complete version.",
  "Require explicit version evidence or a verified catalog match rather than treating generic transmission metadata as a version."
 ],
 "kept": false,
 "verdict": null
}

Current on dev gold: {"n": 99, "holds": 86, "hold_rate": 0.869, "harm": 5, "classes": {"wrong": 5, "exact": 68, "deeper": 17, "out_of_domain_right": 2, "shallower": 1, "version_incomplete": 6}, "flags": 4, "flags_right": 2, "flag_precision": 0.5}
Candidate on dev gold: {"n": 99, "holds": 87, "hold_rate": 0.879, "harm": 6, "classes": {"wrong": 6, "exact": 74, "deeper": 11, "out_of_domain_right": 2, "shallower": 2, "version_incomplete": 4}, "flags": 6, "flags_right": 2, "flag_precision": 0.333}

## 4. Where listings were settled now

{"parse": {"n": 88, "share": 0.01}, "brand": {"n": 40, "share": 0.005}, "registry": {"n": 381, "share": 0.044}, "lattice": {"n": 2354, "share": 0.273}, "agent": {"n": 5738, "share": 0.664}}; still routed: {"n": 36, "share": 0.004, "by_route": {"agent_title": 5499, "agent_search": 292, "agent_evidence": 1}}. Placer this round: {"calls": 5, "sent": 95, "accepted": 5756, "reused_unchanged": 5696, "outcome": {"node": 57, "new_version": 37, "stop": 1}}.

## 5. Cost this round (ledger, since the round started)

| Role | Codex calls | Cache hits | Seconds (sum of calls) | Listings | Tokens |
|---|---:|---:|---:|---:|---|
| improver | 1 | 1 | 15.3 | 0 | 19,608 in (0 cached) / 317 out |
| placer | 5 | 0 | 125.5 | 95 | 114,302 in (78,336 cached) / 6,925 out |
| proposer | 2 | 0 | 34.8 | 0 | 39,133 in (0 cached) / 703 out |
| validator_v2 | 7 | 7 | 220.6 | 93 | 128,569 in (90,496 cached) / 12,036 out |
| validator_v3 | 7 | 7 | 415.9 | 93 | 1,278,326 in (1,042,304 cached) / 21,479 out |

Ledger events this round: {"auto_rules_start": 1, "auto_rules_decision": 4, "codex_call": 37, "auto_rules_proposer_done": 1, "auto_rules_end": 1, "codex_batch": 5, "pipeline_run": 1, "auto_validator": 1}.

## 6. Reading

- The big gain came from the owner's round-1 decision ("as specific as possible"); validator flags fixed the make errors;
  the gate kept the two review-driven label fixes. The placer adds nothing on this sample: it confirms the rules.
- The validator labels these random listings better than the pipeline: it is the place to look for the next rules.
- Candidates left: Codex's "4WD is generic in trims" (untestable: no gold row touches it); the model-number guard
  (dropped on dev).
