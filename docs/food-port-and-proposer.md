# Food port, rule proposer and agent baseline: 2026-11-09

Branch `claude/food-port-proposer`. Gold is Pedia's placements on the hackathon Drive data: 13,500 rows per domain,
split by whole brand (`sha256("taxo-sealed-v1|brand") < 0.2`) into dev and sealed. Every sealed read is logged in
`runs/<domain>/sealed_reads.jsonl`, which stays outside Git like every other run file. This doc holds no listing titles.

Set `TAXO_DRIVE_DIR` to the Drive `DATA/Listings` folder before any command below.

## What is on the branch

- **Food runs end to end.** `taxo/drive.py`, `taxo/pipeline.py` and `taxo/gate.py` take `food` as well as `fragrance`.
  A domain rule file overrides the global rule of the same id. The evaluator has a `has_any` op on `listing.title`.
- **Three food settings, each kept on sealed** (`domains/food/vocab.yaml`):
  - `variant_field`: the shop's own variant label becomes the node under the product, unless it is a placeholder, a
    multi-option string, or a size, pack or count.
  - `shop_brand`: the `brand_site` rung also matches a shop whose name holds a known brand's name, or starts it. One
    brand must fit.
  - `strip` gains flavour markers and buying words: flavored, flavor, box, bag, drinks, halloween, with.
- **`taxo/propose.py`: the rule proposer.** Codex CLI proposes vocab, rule, toggle and brand-suffix changes. Code
  refuses anything brand-specific or outside the rule language. Each proposal is scored on dev; the best dev winner, or
  a bundle of the round's dev winners, gets one logged sealed read through the gate. The prompt shows the dev error
  shapes and a leaf-word table: which words make placements wrong, how often each sits in right leaves, and how many
  brands each spans.
- **`taxo/agent_baseline.py`: the agent alone vs rules.** The Codex agent places each listing from its title, shop,
  URL and brand field. Three solvers are scored on the same gold rows: agent alone, rules only, and rules + agent (the
  agent's answer where the pipeline routes to the agent). Tokens and seconds per listing are measured.
  `--split sealed` scores sealed rows in one logged read.
- **`experiments/`**: the dev-only probes and gate scripts behind every number below. `gate_setting.py` gates one
  setting or list addition: dev first, then one sealed read.

## Food loop 1 (sealed gold, 2,171 rows)

| Round | Change | Exact | Right or shallower | Harm | To agent | Gate |
|---|---|---:|---:|---:|---:|---|
| 0 | cold start: fragrance's code and global rules, food vocab | 11.2% | 57.8% | 23.8% | 34.7% | |
| 7 | `variant_field` | 14.7% | 59.1% | 22.5% | 34.7% | kept: 114 better, 18 worse |
| 8 | `shop_brand` | 16.7% | 65.2% | 24.7% | 27.5% | kept: 134 better, 53 worse |
| 9 | strip += flavored, flavor, box, bag, drinks, halloween, with | 16.8% | 66.0% | 24.0% | 27.5% | kept: 26 better, 10 worse |

Rounds 1-6 were dropped: two by hand, four by the proposer.

Round 8 raised harm: listings that now get a brand go through food's place step instead of stopping unbranded.

Of the food listings still without a brand, 1,412 of 1,425 on dev don't name the brand anywhere in the title. Two
fixes were tried on dev and not gated:
- a fuzzy shop-name match: 81 wrong brands for 698 right;
- a shop-majority brand: 63 right at best, and it labels a whole shop wrong at looser settings.

## Agent alone vs rules (400 random sealed rows per domain, one logged read each)

| Domain | Solver | Exact | Right or shallower | Harm | Tokens per 1,000 listings |
|---|---|---:|---:|---:|---:|
| fragrance | agent alone | 85.0% | 88.7% | 11.3% | 631,800 |
| fragrance | rules only | 72.3% | 84.3% | 13.3% | 0 |
| fragrance | rules + agent (11.2% routed) | 74.8% | 85.3% | 14.7% | 70,762 |
| food | agent alone | 44.5% | 77.2% | 22.8% | 579,815 |
| food | rules only | 16.3% | 68.5% | 22.5% | 0 |
| food | rules + agent (27.5% routed) | 20.0% | 73.5% | 26.5% | 159,449 |

The agent costs about 600 tokens and 1 s per listing (gpt-6.1-sol on the Codex CLI, batches of 40). On 200 dev rows,
fragrance rules + agent looked even with the agent alone: 68.0% vs 69.0% exact. The rules were tuned on those brands,
so the sealed rows are the fair test. There, rules + agent costs a ninth of the tokens and gives up about 10 points of
exact on fragrance. On food it gives up about 25.

## The proposer

- **Fragrance, rounds 9-12, before the leaf-word table:** 0 of 10 proposals passed dev.
- **Fragrance, rounds 14-18, with the table:** 11 of 14 passed dev, all generic strips or buying-format words. Four
  went to sealed and all were dropped:
  - three moved 1-3 sealed rows, under the 10-row minimum;
  - the round 17 bundle of two dev winners moved 23 sealed rows, but changed the class of none.

  The words that make dev placements wrong are rare in the sealed brands' titles. On fragrance, what changes inside
  this rule language no longer reach held-out brands.
- **Bundling:** a round's dev winners are now tried together. Replaying round 14 offline, the bundle scored 80 better
  and 4 worse on dev; its parts scored 34, 28 and 18 better.
- **Food, rounds 3-6 and 10-11:** 2 of 12 passed dev, and both were dropped on sealed. The kept food changes came from
  a new input (the variant label), a new rung (the shop) and the leaf-word table, worked by hand. All three are now in
  the proposer's prompt.

## Run it

```
uv run python experiments/gate_setting.py food shop_brand 8 "label"           # dev, then one sealed read
uv run python -m taxo.propose food --rounds 2 --start 10 --max-sealed 2
uv run python -m taxo.agent_baseline fragrance --split sealed --n 400 --seed 11
```

## Caveats

- Pedia's placements are the gold. Against Harry's own fragrance labels the loop 1 gain is small: 47.2% -> 50.3% on
  121 sealed rows, about ±9 points.
- Fragrance's sealed split has been read many times today; food's 8 times.
- The 400-row comparisons are about ±2 to 2.5 points per rate.
