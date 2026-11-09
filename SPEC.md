# Taxo: system spec

*Kavak × OpenAI × Primero hackathon, Mon 9 Nov 2026. Taxo is a small, fast rebuild of the parts of Pedia
([Mantis4Real/pedia-harness](https://github.com/Mantis4Real/pedia-harness), local at `C:\Work\Pedia-Harness\repo`)
that worked. §11 says what to port and what to leave behind. The talk is [PRESENTATION.md](PRESENTATION.md).*

## 1. Why

To understand a commerce market, you have to connect listings from different marketplaces. One perfume, Lattafa
Khamrah 100 ml, is sold on the brand's own site, on Amazon, on Walmart and by several TikTok Shop sellers, each with a
different title. Until you know they are the same product, you can't add up its price, its reviews or its demand.

The way to connect them is a **product tree**: brand › product › variant, such as Oreo › Double Stuf › Golden. Once a
listing sits on its node, everything attached to it rolls up the tree: shop, price, reviews, search terms, hashtags.
You can see interest in Double Stuf Golden, not just in one listing, and make better predictions.

Building the tree is hard. The same product is written fifty different ways. Shops pose as brands. A gift set belongs
to its maker. A 12-pack is not a new product, but a flanker like Khamrah Qahwa is. At four million listings:

- labelling by hand doesn't scale;
- sending everything to an agent is expensive, and wrong in ways that are hard to see. The bill is the agent-only cost
  per 1,000 listings × 4,000, for every pass, refresh and new domain (measured as the agent-only baseline, §13). In
  Pedia, 59% of the food listings the agent set aside as unplaceable were real products, and an LLM judge scored a
  loop at 87% where the owner's labels said 84%.

**Why it is not over-engineering a labeller.** The tree is the first task; the method is the point:

1. Turn agent judgment into procedures you can read, test and run for free. Agents keep only the hard cases.
2. Never let the system grade itself. Agents hunt for errors; a person decides what is true.
3. Keep what worked, with its scope, so the next problem starts ahead.

The same loops extend to more interesting tasks: matching one product across shops (one price and demand signal per
product); cars at Kavak, where make, model, version and trim decide the price; demand and trends, once search terms and
hashtags roll up to a product (a new node is a new product); and any agent work that has to be trusted at scale, such
as extraction, compliance checks or triage.

## 2. Taxo in one paragraph

Taxo builds the tree for a commerce domain and places every listing on its node. It also learns **how** to build the
tree. It is a two-fold system:

- **Fold 1, inside one domain.**
  - The **induction loop** turns a small hand-labelled gold set into a cheap pipeline: deterministic rules (the
    lattice), registries of official brands, and routes that send only the hard listings to agents. Its goal is two
    numbers: F1 on gold up, cost down.
  - The **validation loop** goes looking for the errors gold can't show. An agent validator labels fresh listings
    blind, and a person settles the cases where it and the pipeline disagree. That grows gold, sharpens the validator,
    and hands new error shapes back to induction.
- **Fold 2, across domains.** The **meta loop** stores everything that worked, with its scope, so the next domain's
  induction loop starts ahead.

> **Induction fits the pipeline to the gold. Validation fits the gold to the world. The meta loop carries both to the
> next domain.**

| Fold | Loop | What it changes | Measured on | Who decides | What it produces |
|---|---|---|---|---|---|
| 1 · one domain | **Induction** | the pipeline: rules, vocabulary, registries, routes, cards | sealed gold: F1 and cost | the gate, in code | a cheaper, more accurate pipeline |
| 1 · one domain | **Validation** | the gold set and the validator | disagreements on fresh listings | a person | more gold, a sharper validator, new error shapes for induction |
| 2 · across domains | **Meta** | the starting kit of the next domain | rounds and cost to reach a target F1, warm start against cold | measured | lessons with a scope and a record |

## 3. Words we use

| Word | Meaning |
|---|---|
| **Domain** | A commerce vertical: fragrance, food, cars, electronics. |
| **Tree** | A domain's product hierarchy. Each domain has its own levels (§4). |
| **Placement** | One listing put on the deepest right node, or parked with a reason. |
| **Pipeline** | The ordered steps that place listings: rules first, agents for what is left (§5). |
| **Rule** | A deterministic step written in YAML: parse, count, look up, or route. |
| **Rule set R*k*** | The pipeline's active rules after round *k*. |
| **Route** | Which process a listing goes to, and so how much it costs. |
| **Gold** | Placements a person labelled. **The only truth.** Split into dev and sealed, by whole brand. |
| **Silver** | Placements the validator agent made on unlabelled listings. **Never truth**: it points to where to look. |
| **Validator** | An agent (a card, tools and a version number) that labels listings on its own and flags pipeline errors. |
| **Validation set V*k*** | A fresh sample labelled by validator v*k*, with every disagreement settled by a person, then frozen. |
| **Lesson** | Something that worked (a rule shape, a route, a registry source, a validator check), with its scope and record. |

## 4. The tree

| Domain | Levels | Example |
|---|---|---|
| Food | brand › product › variant | Oreo › Double Stuf › Golden |
| Fragrance | brand › (sub-brand or family) › product › variant | Lattafa › Khamrah › Khamrah Qahwa |
| Cars | make › model › generation › version › year | Volkswagen › Jetta › A7 › Comfortline 1.4 TSI › 2021 |

Conventions that hold in every domain (all from Pedia's cards and owner rulings):

- Size, pack count and multipacks are never nodes. A 12-pack of a flavour sits on that flavour.
- A correct shallower node is fine; a wrong deeper one is not.
- A shop is not a brand.
- A gift set or variety pack of one maker's goods is a node of that maker, not an assortment.

## 5. The pipeline being learned

A listing goes through the steps in order. Each step either settles it or passes it on. Every placement records the
step that decided it and what it cost.

| # | Step | What it does | Cost |
|---|---|---|---|
| 1 | **Parse** | Normalise the title. Tag and strip variant tokens (size, pack, concentration, audience). Read the barcode or VIN, brand field and shop. | free |
| 2 | **Brand** | The brand field names exactly one brand; the maker after "by"; the title's first words; the brand's own site; the listing's sibling listings. | free |
| 3 | **Registry** | Look the cleaned name up in the brand's registry of official lines and products. | free |
| 4 | **Lattice** | Count name sequences across all the brand's listings to find its products and families. Clear clusters are placed; the unclear ones go on. | free |
| 5 | **Route** | Rules that send what is left to the cheapest agent that can settle it. | none |
| 6 | **Agent** | The judge card answers place / new variant / new product / park. Code checks every answer before it counts. | per call |

Agent routes, cheapest first:

| Route | The agent gets | Typical use |
|---|---|---|
| `agent_title` | title and the brand's page of nodes | the default |
| `agent_evidence` | the above, plus description, variant options and maker | thin title, no barcode |
| `agent_siblings` | the above, plus other listings of the same product page | a shop lists one page per flavour |
| `agent_search` | the above, plus a web search for the brand's official products | brand not in the registry |

### 5.1 The rules, in YAML

**Variant vocabulary (domain file).** It says which tokens are variants rather than names. The lattice strips them
before counting.

```yaml
# domains/fragrance/vocab.yaml
variant:
  size: ['\d+(\.\d+)?\s?(ml|oz|fl oz)']
  concentration: [eau de parfum, edp, eau de toilette, edt, parfum, extrait]
  audience: [for women, for men, unisex, pour homme, pour femme]
  form: [spray, travel size]
strip: [perfume, fragrance, cologne]
```

**Lattice count (ported from Pedia, §11).** A toy example with six titles of one brand:

```
Lattafa Khamrah Eau de Parfum 100ml Unisex        -> khamrah
Lattafa Khamrah EDP Spray 3.4 oz                  -> khamrah
Lattafa Khamrah Qahwa Eau de Parfum 100 ml        -> khamrah qahwa
Khamrah Qahwa by Lattafa EDP 3.4oz for men        -> khamrah qahwa
Lattafa Khamrah Dukhan EDP 100ml                  -> khamrah dukhan
Lattafa Yara Eau de Parfum for Women 100ml        -> yara
```

- Strip the brand and the variant tokens, then count every run of words: `khamrah` 5, `khamrah qahwa` 2,
  `khamrah dukhan` 1, `yara` 1.
- Each title joins its **longest** run that is supported (seen at least twice, or an official name). That gives the
  products **Khamrah** and **Khamrah Qahwa**.
- A leading run shared by two or more products is a **family**, so Khamrah is a family.
- `khamrah dukhan` and `yara` are below the floor. They are **unclear**: the registry settles them if it lists them,
  otherwise they go to an agent.
- No word lists are involved: adding a word to the vocabulary changes the count on the next run.

**Brand registry.** It holds the official structure. An agent builds it with web search and returns a proposal; code
writes the file and keeps the evidence.

```yaml
# registry/fragrance/lattafa.yaml (shape from Pedia's registry/fragrance/lattafa.yaml, trimmed)
brand: Lattafa
aliases: [lattafa, lattafa perfumes]
nodes:
  - {id: F_khamrah,        level: family,    name: Khamrah}
  - {id: P_khamrah_qahwa,  level: product,   name: Khamrah Qahwa, parent: F_khamrah}
  - {id: S_maison_alhambra, level: sub_brand, name: Maison Alhambra, aliases: [maison alhambra]}
basis:
  P_khamrah_qahwa: {source: official, ref: lattafa.com, found_by: agent_search@v1}
```

**Routing rule.** This is the kind of rule the validation loop finds. The case comes from our notes; the YAML shows
the format.

```yaml
# rules/fragrance/route-no-barcode-description.yaml
id: route/no-barcode-description
when:
  - {fact: listing.barcode, missing: true}
  - {fact: listing.description_words, ge: 40}
  - {fact: placement.level, eq: brand}          # the free steps stopped at the brand
then: {route: agent_evidence}
status: shadow                                   # shadow -> active only through the gate (§6.1)
found_by: validation/V2
why: "Small houses with no barcode name the product only in the description; the rules stopped at the brand."
record: {gold_dev: null, gold_sealed: null, cost_per_1k: null}   # filled in by the run
```

**A rule we will not accept.** This is Pedia's real learned rule. It was mined from the judge's own answers, matched
the judge 145 of 145 times where it was mined and 22 of 24 held out, and was recorded as "holds". Its truth was the
agent it was meant to replace. In Taxo it fails the gate, because the gate scores rules on gold only (§10).

```yaml
# Pedia: scopes/general/rules/loop/brand-learned-not-a-brand.yaml (trimmed)
id: loop/brand-learned-not-a-brand
when: [{fact: loop.evidence.first, in: [ready, ona, usa, more, brand, cupcake, mars, tyson]}]   # 38 words in the original
then: {op: loop.no_brand}
metrics:
  mined:  {n: 145, agree: 145}      # agreement with the judge, not with a person
  shadow: {fired: 24, agree: 22, holds: true}
```

## 6. Fold 1: inside one domain

### 6.1 The induction loop

**Goal:** the highest F1 on gold at the lowest cost. Agents are the fallback. A rule earns its place by settling
listings an agent used to settle, at equal or better accuracy.

Each round:

1. **Run** the pipeline on gold dev and collect the errors, each with the step that decided it.
2. **Analyse.** An analyst agent groups the errors by shape and works through a fixed list of questions (taken from
   Pedia's playbook chains):
   - Does a shared root explain them? (lattice)
   - Is the extra word a product type or part of a name? (vocabulary)
   - Does an official source group them? (registry)
   - Which rule should have caught them, and which condition failed?
   - How many brands show the same shape?
3. **Propose one change:** a rule, a vocabulary entry, a registry addition, a route, or a card edit.
4. **Shadow.** Run the change on gold dev without letting it act. Record what it would change, how much of that is
   right, and the cost difference.
5. **Gate (code).** Keep the change only if, on sealed gold:
   - F1 does not fall, and either F1 rises or cost falls;
   - the change touches enough sealed rows that the test could have failed;
   - the lower bound of its precision clears the bar.
6. **Keep or drop.** A kept change becomes active and is logged. Every read of sealed gold is counted.

**Cheap rule mining.** When agents give the same answer on the same facts again and again, propose that as a rule
(Pedia's `learn.py`), and measure it on **gold**, never on the agents' answers.

**Figure A:** F1 on sealed gold and cost per 1,000 listings, round by round, with each point labelled by the rule kept.

### 6.2 The validation loop

**Why it is needed.** Gold is small and a person chose it. Even with a clean test split, a rule can be right on all of
gold and wrong on shops, brands or shapes gold does not contain.

Each round *k*:

1. **Sample** fresh unlabelled listings where gold is thin: new shops, brands not in gold, rules that fire a lot, agent
   routes, and decisions with a small margin.
2. **Label blind.** Validator v*k* labels each listing without seeing the pipeline's answer. It gets more budget than
   the pipeline: the full evidence, sibling listings and web search.
3. **Compare.** Where they agree, the label is silver-agreed. Where they disagree, the item goes to review.
4. **Review.** A person settles every disagreement, plus a spot check of agreed items. Each verdict is one of: pipeline
   wrong, validator wrong, both wrong, or unclear.
5. **Use the verdicts:**
   - **Pipeline wrong:** the case joins gold (dev, or sealed when its brand is a sealed brand). Its error shape goes
     to the induction loop.
   - **Validator wrong:** feedback to the validator, as a card edit, a new tool or a new check. This gives v*k+1*.
   - **V*k* is frozen:** its labels are the agreed items plus the reviewed ones, with an error bar from the spot check.
6. **Score the validator** on gold at every version: agreement, how precise its "wrong" flags are, and its tilt (how
   often it says wrong or park). Its silver counts only once these are good enough.
7. **Re-read.** v*k+1* re-reads earlier silver-agreed items, and any it now flags go to review. This is how something
   that was considered fine comes back as an error.

**Who changes gold.** Only a person. A claim that a gold label is wrong is a review item, not an edit.

**Then we iterate.** The error shapes from V*k* go back to the induction loop. New rules come from them; we add more
brands and run more of the process, and the analyst looks for the pattern underneath, not the single case. That gives
rule set R*k+1*, which is scored on gold and on every frozen V.

**Human feedback.** A person improves what the validator looks for. For example, the validator proposed searching the
web for each brand's official product lines, and we approved it. It then found products that gold had missed, and these
became registry-backed gold cases. This grows the correct cases and the overall accuracy.

**Figure B:** rule set R1 scored on gold, V1 and V2. Its score drops on V2, where new error shapes appear. R2, after the
induction loop has learned from V2's errors, recovers. The full grid is R*i* × V*k*.

## 7. Fold 2: the meta loop, across domains

Every change kept by the induction or validation loop becomes a lesson:

```yaml
# lessons/strip-variants-before-counting.yaml
id: lesson/strip-variants-before-counting
kind: rule_shape        # rule_shape | route | registry_source | validator_check | card_text
scope: global           # domain:<name> | global
claim: "Strip size, pack and audience tokens before counting names, or every size becomes a product."
record:                 # one row per domain where it was tried; filled in by the runs
  - {domain: fragrance, round: null, delta_f1: null, delta_cost: null}
  - {domain: food,      round: null, delta_f1: null, delta_cost: null}
status: active
```

For a new domain:

1. **Start** from the global lessons plus the nearest domain's lessons. Rule shapes carry over as they are. An agent
   writes the new domain's vocabulary from its listings.
2. **Run the induction loop twice:** from this warm start, and from a cold start where every listing goes to an agent.
3. **Measure** the rounds and cost to reach the target F1, and F1 after a fixed number of rounds. For each lesson,
   record whether it fired in the new domain and whether it was right.
4. **Promote or retire.** A lesson that helps in two domains becomes global. One that hurts is scoped down to the
   domains where it works.

**Figure C:** a transfer matrix, source domain × target domain, where each cell is the rounds saved to reach the target F1.

**Transfer is uneven.** What we expect, to be confirmed by today's runs (there are no Taxo numbers for it yet):

| From → to | Expected | Why |
|---|---|---|
| Food → fragrance | carries | Food has more structure (packs, multipacks, shops posing as brands, generic names), so its lessons cover fragrance's shapes. |
| Fragrance → food | not much | Fragrance's lessons (flankers, concentrations) are specific to it. |
| Fragrance → cars | little | Cars have a much more defined catalogue: make, model and version are published, and a VIN decodes them. The registry and barcode routes do the work there, not the lattice. |

## 8. Data

The data stays in the home that owns it. Taxo reads it in place and keeps pointers plus toy samples.

| Set | What | Where |
|---|---|---|
| Listings | title, brand field, shop, barcode, description, variant options | M4R frozen extracts (`C:\Work\Pedia-Harness\data\inbox\`) |
| Gold, fragrance | 150 owner-labelled titles (accept or reject, prefix or exact); 1,486 owner reviews of nodes and listings; the truth store (17,596 rows, 4,540 of them holdout) | `repo\tests\fixtures\fresh150-harry.yaml`, `repo\tests\fixtures\owner-structure.jsonl`, `data\verdicts\fragrance\` |
| Gold, food | the food truth store | `data\verdicts\food\truth@33bf14d31fea.*` |
| Gold, cars | still to get: Kavak listings, plus VIN decoding (NHTSA vPIC) for make, model and year | — |
| Silver, V*k* | validator output by version; frozen validation sets | `runs/` (outside Git) |

**Splits.** Sealed gold is whole brands, chosen by a hash of the brand name (20%), so a rule cannot pass by memorising
a brand. Only the gate reads sealed gold, and every read is logged.

## 9. Metrics

- **Placement accuracy and F1 by level** (brand, product, variant). An exact match and a correct-but-shallower match are
  counted separately. Going too deep counts as worse than stopping too shallow.
- **Accept and reject checks** (Pedia's fixture format). Accept: the path must hold. Reject: a known-wrong shape must not come back.
- **Parks:** the park rate, and how many parked listings truly could not be placed.
- **Cost:** dollars and agent calls per 1,000 listings, and the share settled by rules.
- **Validator:** agreement with gold, precision of its flags, and its tilt.
- **Transfer (meta loop):** rounds to the target F1, warm start against cold.

## 10. Guardrails

Each guardrail comes from something that went wrong in Pedia.

| Guardrail | What happened in Pedia |
|---|---|
| A rule's truth is gold, never the agent it replaces. | The learned rule matched the judge 145 of 145 times. The judge was its truth. |
| Silver counts only after the validator is scored on gold. | A checker card said "When in doubt, disagree". All 25 audited parks from that checker were real products. For the other main park reasons, 72–80% were wrong. |
| Agreed cases are spot-checked. | Two judges agreed on 23 conflict cases, and no one checked those against the owner. |
| Only a person edits gold. | Judges ruled 15 owner examples "unsatisfiable", and they left the yardstick. |
| A loop is never scored by the judge it trains against. | A loop scored by the LLM judge learned the judge's bias: 15 of 48 changes helped the judge and hurt the owner's labels. |
| Sealed gold is split by brand, and reads are counted. | The frozen holdout was read 75 times in about 37 hours. |
| A sealed test must be able to fail. | "Holds" was recorded on 24 items, too few for the test to fail. |
| Parks are re-read every round. | Parks were carried forward for good; 59% of food parks were real products. |
| Code checks every agent answer: ids exist, levels fit, no twin nodes. | Taken directly from Pedia's `judge.py`. |

## 11. What to port from Pedia, and what to leave behind

**Target:** one Python package of about 1,500 lines. It uses files on disk (YAML, JSONL, DuckDB) and calls agents
through the OpenAI API with structured outputs. One command runs one loop round on a slice of a few thousand listings
in minutes. Paths below are relative to `C:\Work\Pedia-Harness\repo`.

### Steal

| Take | From | How to port | Effort |
|---|---|---|---|
| **Lattice count** | `packages/engine/pedia_engine/lattice/count.py` (753 lines, standard library only, pure) | Copy as it is. Replace `CountVocab.from_taxonomy` with a loader for `domains/<d>/vocab.yaml`. | 1 h |
| **Rule format** | `scopes/general/rules/loop/*.yaml`: `id`, `when` facts, `then` op, `status: shadow\|active`, `metrics` | Keep the format. Write a first-match evaluator of about 150 lines with a shadow mode ("would it change the answer?"). Do **not** port the interpreter. | 2 h |
| **Brand and node rule ladder** | the docstring of `pipeline/populate/loop/ladder.py`: sibling, brand_page, site, brand_name, title_by, title_lead, brand_shared, then node rules | Port the list of general patterns as six to eight rules over our facts. Skip `Pages` and the frame. | 2 h |
| **Agent cards** | `pipeline/populate/cards/loop-judge-v2.md`, `loop-brand-v2.md`, `loop-verify-v2.md`, `loop-judge-fragrance-v1.md` (30–60 lines each) | Copy them, and make them domain-neutral. Remove "When in doubt, `disagree`" from `loop-verify-fragrance-v1.md:35`. They are the base of the judge and validator cards. | 1 h |
| **Agent call contract** | `matching/agents/runner.py` (1,143 lines): a frozen card plus a payload, a strict JSON parse, a validator; a bad answer is refused and logged, never patched; a secret scan before every call | Rewrite in about 100 lines on the OpenAI API. Keep the refuse-don't-patch rule and the secret scan. | 1.5 h |
| **Checking agent answers in code** | `pipeline/populate/loop/judge.py`: ids exist, levels fit, a "new" node that has a same-name twin becomes a placement on the twin | Port the checks, about 60 lines. | 1 h |
| **Registry file** | `registry/fragrance/lattafa.yaml` (nodes with a `basis`) and `registry/brand-names/*.yaml` (names, level, family, evidence) | Merge them into one small format (§5.1). The agent proposes, code writes. | 1 h |
| **Rule mining** | `pipeline/populate/loop/learn.py` (447 lines): count by question rather than by listing, cap each page, take the Wilson lower bound, shadow before promoting | Port the guards and constants. Mine from gold and reviewed silver, never from raw agent answers. | 2 h |
| **Sealed split** | `harness/verdicts/holdout.py` (253 lines): `frac(k) = sha256(salt\|k)`, grouped by brand, one reader | About 30 lines, plus a JSONL log of reads. | 0.5 h |
| **Scorer** | `harness/construct/score.py` (336 lines): precision of built nodes, recall of curated products, merge and split pairs, precision per rule | Port the metric definitions only. Where the builder and the gold registry disagree, list the case for review instead of counting it as an error. | 1.5 h |
| **Gold format and data** | `tests/fixtures/fresh150-harry.yaml` (accept or reject, prefix or exact, with a `why` per row) | Use this format for all gold, and read the existing files in place. | 0.5 h |
| **Error-analysis questions** | `labs/chains/P01.yaml` (questions, then a decision: generalise or read) | Use these as the analyst card's checklist in the induction loop. | 0.5 h |
| **Review protocol** | `data/verdicts/fragrance/example-conflicts/` (four outcomes; two models, a third breaks ties) | Reuse the four outcomes for the validation loop's review. Change it so the person decides and agreed cases are spot-checked. | 0.5 h |

### Leave behind

| Leave | Why |
|---|---|
| The rule interpreter (`pedia_engine/rules/`, 2,371 lines: addresses, rivals, envelopes, slots) | A small first-match ladder is enough for a demo. |
| Claim-based construction C0–C10 (`harness/construct/*`, except the lattice) | Too heavy. The lattice plus the registry covers it. |
| The release path (Zilin, S3 store, Postgres, a-build, live push) | Taxo does not publish a release. |
| Codex worker offload, `judge_cache.py`, the per-batch blind read gate | Use direct API calls. The validation loop's sample replaces the batch gate. |
| The citation and ratification system (`spaces/` ids, `DESK.json`) | One `approved_by` field on gold edits and promotions is enough. |
| Search-term homing (`matching/policy/launch.yaml`) | This is the payoff after the tree exists, not part of building it. |
| Carrying parks forward | It hid real products. Re-read parks every round. |
| The seven-level court and hash-chained ledger from the RSI proposal | An append-only `ledger.jsonl` is enough. |

## 12. Layout

```
domains/<d>/domain.yaml       levels, conventions
domains/<d>/vocab.yaml        variant and strip tokens
registry/<d>/<brand>.yaml     official structure, with its basis
rules/<d>/*.yaml              domain rules
rules/global/*.yaml           rules promoted by the meta loop
cards/                        judge, brand, validator, analyst, registry
lessons/*.yaml                the meta loop's store
taxo/                         parse, lattice, rules, pipeline, agents, gate, validate, transfer, score, split
runs/<run>/                   outside Git: placements.jsonl, metrics.json, ledger.jsonl
```

## 13. Build order for today

1. Port the lattice, rule evaluator, vocabulary and gold reader. Run on fragrance gold for a baseline: all-agent
   against rules plus agents, F1 and cost.
2. The induction loop, three to five rounds on fragrance → Figure A.
3. The validator card and one validation round (V1, then V2), with a person reviewing the disagreements → Figure B.
4. Food from a cold start and from a warm start → the first cell of Figure C.
5. A cars slice, if there is time and data.

## 14. Not proven yet

- Every number in Figures A to C still has to come from a run. Nothing in this spec is a measured Taxo result; the
  numbers in §1, §5.1 and §10 are Pedia's.
- Whether lessons transfer across domains, and in which direction. The directions in §7 are what we expect; the run
  has to confirm them.
- How much review a person must do per validation round before the validator's silver can be trusted on its own.
- Cars: no data yet.
