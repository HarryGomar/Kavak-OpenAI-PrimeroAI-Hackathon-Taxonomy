# Cycle 1 (silver S2)

## Rule phase (gated on silver)
- start: phase 1 start: silver exact 0.745 harm 0.125 (200 rows)
- end: unchanged
- proposer calls: 1 of 1 rounds
  - round 1: convention_question `preserve_product_name_tokens`: Should product identity terms such as body mist, hair mist, travel spray, and gift set be retained when they appear as part of a fragrance product name or bundl -> not testable this round (recorded)

## Validator (human round, improver, A/B)
- improver change: model `product_name`: Reword product_name to retain named products and sets, including non-fragrance items, instead of limiting named paths to fragrances.
- A/B on dev human rows (V6): current exact 0.825 harm 0.175 abstain 0.05 -> candidate 0.85 / 0.15 / 0.1
- validator card: v1 -> v2 (KEPT)

## Dev checkpoint (human labels; sealed not read)
- dev exact 0.658 harm 0.193; human dev exact 0.529; to agent 0.109
- placer: 40 calls, 29 placed, 11 abstained, 0 refused, 0 failed, 169 tool calls, 160.1 s
