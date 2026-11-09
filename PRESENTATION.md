# Taxo: presentation script

*About 7 minutes. **Say** is what you say; **Show** is what is on screen. Numbers in [brackets] come from today's runs.
Fill them in or cut the line; don't present a placeholder as a result. The figures to produce are listed at the end.
The system is in [SPEC.md](SPEC.md).*

---

## 1. Title (10 s)

**Show:** Taxo: learning to build product trees for any commerce domain.

**Say:** We're going to show you Taxo, a system that learns how to turn messy marketplace listings into clean product
trees, and gets faster at it with every domain it sees.

## 2. Where we're coming from (45 s)

**Show:** on the left, a climbing line labelled "what the system says". On the right, a flat or falling line labelled
"what a person finds". Under them, one line: *15 of 48 changes made the judge happier and our labels worse.*

**Say:**
- For months we have been hill-climbing classification and matching: putting marketplace listings on product trees,
  and matching the same product across shops.
- Every time, we hit the same wall. The system says it's right. It says it's getting better. And we can't trust it.
- One example: we let a loop improve our pipeline against an LLM judge. It learned the judge's bias. 15 of the 48
  changes it kept made the judge happier and made our own labels worse.
- So we want two things at once:
  - improve the real KPIs, not the ones the system grades itself on;
  - improve how we validate: grow the validation set, use agents to make the validation itself better, and carry all of
    it from one domain to the next.

## 3. Why trees (40 s)

**Show:** an Oreo tree. Oreo › Double Stuf › Mint. Under Mint sit listings from Amazon, Walmart and TikTok Shop, and
under those, the search terms and hashtags that lead to them.

**Say:**
- To understand a commerce market, you have to connect listings from different marketplaces.
- Oreo has products. Those products have variants. Each variant is sold in dozens of listings, in different shops, with
  different titles.
- Once a listing sits on the right node, everything attached to it rolls up: price, reviews, the search terms and
  hashtags people use. You can see interest and demand for "Oreo Mint", not just for one listing.
- Building that tree is hard. At four million listings, it gets really complicated.

## 4. Why it's hard (40 s)

**Show:** five real titles of one product, written five different ways. Below them: a shop posing as a brand, a gift
set, a flanker, a 12-pack.

**Say:**
- The same product is written fifty different ways. Shops pose as brands. A size or a 12-pack is not a new product.
  A flanker is.
- There are two easy answers, and both fail.
  - Label everything by hand: it doesn't scale.
  - Send everything to an agent: it's expensive, and it is wrong in ways that are hard to see. In our earlier system,
    59% of the food listings the agent set aside as unplaceable were real products.

## 5. Taxo in one slide (40 s)

**Show:** three loops: A Induction, B Validation, C Transfer. Under each, what it improves: the real KPIs; the
validation; the next domain.

**Say:** Taxo answers both halves of that problem with three loops.
- **Loop A** improves the real KPIs. It fits the pipeline to gold that a person labelled, never to an agent's opinion.
- **Loop B** improves the validation. Agents hunt for errors that gold doesn't show, a person settles them, and the gold
  and the validator both get better.
- **Loop C** carries both to the next domain.
- In short: A fits the pipeline to the gold, B fits the gold to the world, and C carries both to the next domain.

## 6. Loop A: induction (60 s)

**Show:** on the left, the pipeline (parse → brand → registry → lattice → route → agent). On the right, Figure A.

**Say:**
- We start with a small gold set that a person labelled.
- Taxo tries to turn it into **deterministic rules**, so that agents only see the hard cases.
- There are three kinds of rule:
  - **Counting.** The lattice counts word sequences across all of a brand's listings. "Khamrah" appears in five titles
    and "Khamrah Qahwa" in two, so Khamrah is a family and Khamrah Qahwa is a product. No word lists.
  - **Registries.** An agent searches the web for each brand's official product lines, and code writes them as a file
    the rules can read. *(Show the Lattafa YAML.)*
  - **Routes.** What's left goes to the cheapest agent that can settle it: the title alone, or the title plus the
    description, or a web search.
- Each round, an analyst agent reads the errors, proposes one change, and a gate in code keeps it only if it helps on
  gold that nobody tuned on.
- **Figure A:** F1 goes from [x] to [y] while the cost per thousand listings falls from [$a] to [$b].

## 7. Gold is not enough (40 s)

**Show:** Figure B, first half: rule set R1 on gold, on V1, and on V2. The bars drop.

**Say:**
- A gold set is small, and a person chose it. It can't contain every error a rule will make.
- We learned this the hard way. In our earlier system, a rule matched the agent's answers 145 times out of 145. It was
  marked as holding. But its truth was the agent it was meant to replace.
- Here, R1 scores [x] on gold, [y] on validation set 1, and [z] on validation set 2. Fresh listings find errors gold
  never showed us.

## 8. Loop B: validation (60 s)

**Show:** the Loop B cycle (sample → validator labels blind → disagreements → person → gold, rules, validator). Then the
routing YAML.

**Say:**
- So Loop B goes looking for errors.
- An agent validator labels fresh listings on its own, with more budget than the pipeline. Where it disagrees with the
  pipeline, a person settles it.
- When the pipeline is wrong, the case joins gold and goes back to Loop A. For example, [confirm from the run: small
  fragrance houses with no barcode name the product only in the description, and our rules stopped at the brand].
  Loop A turned that into a route: no barcode and a long description → send it to the agent with the description.
  *(Show the YAML.)*
- The validator learns too. When it is wrong, the person tells it why. It proposed searching the web for each brand's
  official lines, we approved it, and it started finding products that gold had missed.
- Each new validator re-reads what earlier ones accepted, so errors we had marked as fine come back.
- **Show the second half of Figure B:** R2 recovers on V2, [z → w], and gold grows from [n] to [m] cases.

## 9. Loop C: transfer (50 s)

**Show:** Figure C, the transfer matrix (food, fragrance, cars), each cell showing rounds saved.

**Say:**
- Every change that worked is stored as a lesson, with its scope: one domain, or all of them.
- When we start a new domain, Loop A starts from those lessons instead of from zero.
- It does not transfer equally. [If the run confirms it: going from food to fragrance saved [n] rounds; going from
  fragrance to food saved [m].] Food has more structure (packs, multipacks, shops posing as brands), so its lessons
  cover fragrance. Fragrance's lessons are more specific.
- Cars are a different case, and they matter to Kavak. Make, model and version are published, and a VIN decodes them.
  So the registry and the barcode routes should do most of the work there.

## 10. Close (25 s)

**Show:** the three-loop slide again, with the headline numbers.

**Say:** Systems will always say they're right. Taxo doesn't take their word for it. It improves the real KPIs on gold
it never tuned on, it grows and sharpens its own validation with agents, and it starts every new domain ahead. Agents
handle what is truly hard, rules handle the rest, and a person decides what is true.

---

## Figures to produce

| Figure | What it shows | Axes | From | Status |
|---|---|---|---|---|
| **A** | Loop A on one domain | x: round; y1: F1 on sealed gold; y2: cost per 1,000 listings. Each point is labelled by the change kept (lattice, registry, route) | Loop A runs on fragrance | to run |
| **B** | Gold is not enough, and Loop B fixes it | grouped bars: R1 and R2 on gold, V1 and V2 | Loop B rounds 1–2 | to run |
| **C** | Transfer between domains | matrix, source × target: rounds saved to reach the target F1, warm start against cold | food ↔ fragrance; cars if there is data | to run |
| Says vs finds | Where we're coming from | two lines over rounds: the judge's score against the owner's labels | Pedia replay `pe2` (`C:\Work\RSI\hackathon\runs\`) | data exists |
| Oreo tree | Why trees | a tree diagram with listings, search terms and hashtags | hand-drawn from real listings | to make |
| Pipeline | Loop A | step diagram with the cost of each step | SPEC §4 | to make |

## Questions to expect

| Question | Answer |
|---|---|
| Why not just use an agent for everything? | Cost, and errors you can't see. In Pedia, the agent wrongly set aside most of the listings it parked. Rules are cheap and testable, and agents get only the hard cases. |
| Isn't the validator just another agent you trust? | No. It is scored on gold at every version, its agreements are spot-checked, and only a person settles a disagreement or changes gold. |
| How do you know a rule generalises? | Sealed gold is whole brands that the loop never tunes on. And Loop B tests the rules on listings gold doesn't contain. |
| What does a person actually do? | Settles the disagreements Loop B raises (about [n] per round), and tells the validator what to look for. |
| What about cars? | Make, model and year come from a VIN. Version and trim are where listings disagree, and that is where the lattice and routes come in. |
