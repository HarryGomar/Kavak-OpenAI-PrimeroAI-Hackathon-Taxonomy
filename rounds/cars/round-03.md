# Cars round 03: 100 random gold rows; review r02; Codex proposer kept 2 aliases; validator v3 rejected (more harm)

Rules 0.3.0 + 4 learned (`7504bc83265c`): `identity.yaml` + `vocab.yaml` + `identity-learned.yaml`
(edits kept by the gate). Gold: `round-01+round-02.yaml` (100 random listings, 10 per source;
provenance {"ai_prelabel_checked": 100}: Opus pre-labels checked by Diego, so not fully blind; every row compare
{"exact": 50, "prefix": 50}), plus the owner's A/B review (review-r01, provenance review) and the imported round-0
reviews for the gate. Scored with the cars judge (`domains/cars/judge.py`: make, model, year, version incl. engine size
and gearbox), not taxo/score.py (it drops digit tokens). Intervals are 95% Wilson.

Owner decision this round: "CHRYSLER ATTITUDE SE CVT 2024" is a Dodge (gold row changed by Diego, noted in its `why`).

## 1. Headline: random gold (n = 100)

| System | Right | 95% CI | Not harmful | 95% CI | Validator flags right |
|---|---:|---|---:|---|---|
| rules 0.1.0 (rules only) | 13/100 (13%) | 8%–21% | 97/100 (97%) | 92%–99% |  |
| rules 0.2.0 (rules only) | 84/100 (84%) | 76%–90% | 96/100 (96%) | 90%–98% |  |
| rules 0.3.0 + 4 learned (rules only) | 88/100 (88%) | 80%–93% | 98/100 (98%) | 93%–99% |  |
| rules 0.3.0 + 4 learned settled (supported only) | 26/100 (26%) | 18%–35% | 99/100 (99%) | 95%–100% |  |
| rules+placer 0.2.0 | 85/100 (85%) | 77%–91% | 97/100 (97%) | 92%–99% |  |
| rules+placer 0.3.0 + 4 learned | 88/100 (88%) | 80%–93% | 99/100 (99%) | 95%–100% |  |
| validator v1 | 49/50 (98%) | 90%–100% | 50/50 (100%) | 93%–100% | 0/0 |
| validator v2 | 90/100 (90%) | 83%–94% | 98/100 (98%) | 93%–99% | 0/0 |

"Right" = the gold path holds (exact compare: a deeper answer fails). "Not harmful" = right, or correct but shallower /
version missing a word; never a wrong make, model, year or version. "Validator flags right" = of the listings where the
validator disagrees with rules+placer, how many gold says rules+placer got wrong.

## 2. Loop A, automatic (Codex proposer + gate)

Gate: rules only on dev gold (194 rows), kept only if it touches gold, holds no fewer rows, adds no harm and
holds more (or routes fewer); then one logged sealed read that must not fall. Sealed reads so far: 6.

| Change | From | Verdict | Dev rows touched | Delta (holds, harm, routed, version nodes) | Sealed |
|---|---|---|---:|---|---|
| Normalize Kia Soul with embedded EX trim | codex proposer | kept | 1 | {"holds": 1, "harm": 0, "routed": -2, "version_nodes": 1} | {"rows": 34, "before": 23, "after": 23, "harm": 6, "reads_total": 5} |
| Guard against numeric trim information loss | codex proposer | dropped on dev | 2 | {"holds": -1, "harm": 1, "routed": 2, "version_nodes": 2} | - |
| Restore JAC nameplate after make-prefix stripping | codex proposer | kept | 2 | {"holds": 2, "harm": -1, "routed": 1, "version_nodes": 0} | {"rows": 34, "before": 23, "after": 23, "harm": 6, "reads_total": 6} |
| Treat 4WD consistently with generic drivetrain tokens | codex proposer | untestable: touches no gold row | 0 | {"holds": 0, "harm": 0, "routed": -8, "version_nodes": -7} | - |
| Ignore trailing abbreviated catalogue years | codex proposer | untestable: touches no gold row | 0 | {"holds": 0, "harm": 0, "routed": 0, "version_nodes": 0} | - |
| Normalize gear-count transmission notation | codex proposer | untestable: touches no gold row | 0 | {"holds": 0, "harm": 0, "routed": 0, "version_nodes": 0} | - |

Kept: ["Normalize Kia Soul with embedded EX trim", "Restore JAC nameplate after make-prefix stripping"]. Dev after: {"holds": 170, "n": 194, "harm": 10}.

## 3. Validator improver (Codex)

{
 "from_version": 2,
 "candidate_version": 3,
 "lines": [
  "Resolve conflicting brand fields using the model’s identity in the target Mexican taxonomy before rejecting a listing.",
  "Match versions to the target make–model–year taxonomy, applying established aliases for trim, engine, drivetrain, and transmission.",
  "Retain all explicit version qualifiers across title, model, and version fields, including body style, cab configuration, and “Estándar.”"
 ],
 "kept": false,
 "verdict": null
}

Current on dev gold: {"n": 175, "holds": 157, "hold_rate": 0.897, "harm": 5, "classes": {"wrong": 5, "exact": 137, "deeper": 18, "out_of_domain_right": 2, "shallower": 2, "version_incomplete": 11}, "flags": 3, "flags_right": 2, "flag_precision": 0.667}
Candidate on dev gold: {"n": 175, "holds": 164, "hold_rate": 0.937, "harm": 9, "classes": {"wrong": 9, "exact": 148, "deeper": 14, "out_of_domain_right": 2, "shallower": 1, "version_incomplete": 1}, "flags": 3, "flags_right": 2, "flag_precision": 0.667}

## 4. Where listings were settled now

{"parse": {"n": 88, "share": 0.01}, "brand": {"n": 40, "share": 0.005}, "registry": {"n": 380, "share": 0.044}, "lattice": {"n": 2356, "share": 0.273}, "agent": {"n": 5756, "share": 0.666}}; still routed: {"n": 17, "share": 0.002, "by_route": {"agent_title": 5497, "agent_search": 293, "agent_evidence": 1}}. Placer this round: {"calls": 5, "sent": 97, "accepted": 5774, "reused_unchanged": 5693, "outcome": {"node": 78, "new_version": 18, "stop": 1}}.

## 5. Cost this round (ledger, since the round started)

| Role | Codex calls | Cache hits | Seconds (sum of calls) | Listings | Tokens |
|---|---:|---:|---:|---:|---|
| improver | 1 | 0 | 12.5 | 0 | 18,203 in (0 cached) / 294 out |
| placer | 5 | 0 | 128.6 | 97 | 112,844 in (76,800 cached) / 6,766 out |
| proposer | 6 | 0 | 94.1 | 0 | 127,392 in (15,360 cached) / 2,346 out |
| validator_v2 | 12 | 0 | 364.7 | 169 | 225,396 in (187,648 cached) / 18,891 out |
| validator_v3 | 12 | 0 | 395.3 | 169 | 246,896 in (208,384 cached) / 20,363 out |

Ledger events this round: {"auto_rules_start": 2, "auto_rules_decision": 9, "auto_rules_end": 2, "codex_call": 36, "codex_batch": 3, "auto_validator": 1, "pipeline_run": 1}.

## 6. Reading

- The big gain came from the owner's round-1 decision ("as specific as possible"); validator flags fixed the make errors;
  the gate kept the two review-driven label fixes. The placer adds nothing on this sample: it confirms the rules.
- The validator labels these random listings better than the pipeline: it is the place to look for the next rules.
- Candidates left: Codex's "4WD is generic in trims" (untestable: no gold row touches it); the model-number guard
  (dropped on dev).

## 7. Owner review r02 (A/B, sources hidden; 2 disagreements + 47 spot checks from 550 fresh listings)

- Validator v2 vs pipeline on 550 fresh random listings: 548 agree, 2 disagree.
- Disagreements: "Chrysler Attitude ... Plata" (both wrong: owner typed Dodge > Attitude; the pipeline left it unplaced
  on a make conflict, the validator gave no make) and "Dodge Ram Laramie 2015" (pipeline right: Dodge > Laramie > 2015).
  Validator flag precision on review: 1/2.
- Spot checks of agreed listings: both right 20, validator's wording better 17, pipeline's better 10 (mostly version
  completeness: gearbox, "C 180", hybrid words). "Agreed" is not the same as "right": 27/47 needed a choice.
- Owner ruling to carry: "Dodge Ram Laramie" of 2015 stays Dodge (the year-bounded Ram rebrand fired on Dodge Ram
  <number> titles only). Round-02 gold: owner kept all 50 Claude pre-labels (changed_by_person false on every row), so
  round 02 measures agreement with those confirmed labels, not independent labels.
