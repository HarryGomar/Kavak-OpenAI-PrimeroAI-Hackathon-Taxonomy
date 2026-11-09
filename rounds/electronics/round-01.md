# Electronics round 01: validator v1 (Codex), first Loop B pass

The validator labelled 150 listings blind (5 Codex calls): the 50-listing gold sample and 100 fresh
random in-scope listings. Its candidate page comes from brands named in the title and rare shared words, never from the
pipeline's answer. Prompt: `taxo/roles/codex_placer.py` `VALIDATOR_PROMPT`.

Fresh listings, validator vs pipeline: {'depth': 8, 'different_product': 4, 'one_parks': 1, 'same': 82, 'validator_rejected': 5}.
Disagreement shapes: `depth` = same brand, one stops shallower (mostly the validator stopping at the brand where the
pipeline used a part number from the model field); `different_product` = series name vs part number for the same item
(e.g. "my passport essential se" vs "wdbabm0010bbk-nesn"), which is a naming convention to settle, not always an error.
`validator_rejected` = the code checks refused its answer (a brand it named was not on its page).

**Not scored yet:** the validator counts only once it is scored on gold (SPEC §8). 24 cases
(6 of them random spot checks of agreements) wait for a person in the review page.
Every answer is in [`round-01-validator.csv`](round-01-validator.csv).

## Rule and validator candidates

1. **Convention needed: series name or part number?** When a listing gives both ("my passport essential se" and
   "wdbabm0010bbk-nesn"), which names the product? Decide in `domains/electronics/pack.yaml`; then align the rule and the
   validator prompt.
2. **Validator v2:** let it use the model field as evidence (today it often stops at brand when the title lacks the
   part number), and give it the brand node whenever a brand word starts the title.

## Next

Diego: 50 one-click gold (`domains.electronics.loop gold-page`) and the review page; then `loop score --round 1`.
