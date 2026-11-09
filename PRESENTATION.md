# Taxo: presentation script

*About 9 minutes, 17 slides (if you must cut, cut 4 and 14). **Show** is what is on screen; **Say** is what you say. Numbers in [brackets] come from
today's runs: fill them in or cut the line, and never present a placeholder as a result. The figures still to produce
are listed at the end. The system is in [SPEC.md](SPEC.md); the deck is [slides/index.html](slides/index.html).*

The story, in one breath: to understand a market you connect listings into product trees; at four million listings that
is hard, and an agent alone is too expensive and wrong in ways you can't see; Taxo is a two-fold system that learns to
do it. Inside one domain, the **induction loop** turns gold into cheap
rules and the **validation loop** finds the errors gold can't show. Across domains, the **meta loop** carries what worked
to the next one. It is not a labelling system: the tree is the first task, and the method (turn agent judgment into
rules you can test, never let a system grade itself, carry what worked) is the point.

---

## 1. Title (10 s)

**Show:** Taxo: learning to build product trees for any commerce domain.

**Say:** We're going to show you Taxo, a system that learns how to turn messy marketplace listings into clean product
trees, and gets faster at it with every domain it sees.

## 2. Understanding a market means connecting listings (35 s)

**Show:** one product, Lattafa Khamrah 100 ml, as five listings: the brand's own site, Amazon, Walmart and two TikTok
Shop sellers. Each has its logo, its photo and its real title. They all point to one node.

**Say:**
- To understand a commerce market, you have to connect listings from different marketplaces.
- This is one perfume. Five shops, five titles. Until you know they are the same product, you can't add up its price,
  its reviews or its demand.

## 3. Food and fragrance taxonomies (30 s)

**Show:** two trees side by side. Food: Oreo › Double Stuf › Golden. Fragrance: Lattafa › Khamrah › Khamrah Qahwa.

**Say:**
- The way to connect them is a tree. In food, a brand has products and the products have variants: Oreo has Double
  Stuf, and Double Stuf comes in Golden.
- Fragrance has one more level: Lattafa has the Khamrah family, and Khamrah Qahwa is a product inside it.
- A size or a 12-pack is never a new node.

## 4. A variant connects listings, search terms and hashtags (30 s)

**Show:** Oreo › Double Stuf › Golden. On it, listings from Amazon, Walmart and TikTok Shop; under them, the search terms
and hashtags that lead to them; on the right, what rolls up.

**Say:**
- Oreo has products, those products have variants, and each variant connects to listings in different shops, and to
  the hashtags and search terms people use.
- Once they are connected you can see interest in Double Stuf Golden, not just in one listing, and make better
  predictions.

## 5. Doing this is hard (35 s)

**Show:** four million listings, and four traps with their photos: a shop posing as a brand, a gift set, a flanker,
a 12-pack.

**Say:**
- Doing this is hard, and with four million listings it gets really complicated.
- The same product is written fifty different ways. Shops pose as brands. A gift set belongs to its maker. A 12-pack
  is not a new product, but a flanker like Khamrah Qahwa is.
- Labelling four million listings by hand doesn't scale.

## 6. Why not just an agent? (40 s)

**Show:** the bill: 4M listings × [$c] per 1,000 = [$C] for one pass. Next to it, three ways an agent is wrong without
saying so: its F1 on gold [f]; 59% of the food listings our earlier agent parked were real products; an LLM judge said
87% where the owner's labels said 84%.

**Say:**
- The obvious answer is to send every listing to an agent. At [$c] per thousand listings, four million listings cost
  [$C] for one pass, and again for every refresh and every new domain.
- And it is wrong in ways you can't see. On gold, the agent alone scores [f]. In our earlier system, 59% of the food
  listings the agent set aside as unplaceable were real products. When we let a loop grade itself with an LLM judge, the
  judge said 87%; the owner's labels said 84%.
- So this is not over-engineering a labeller. Rules are free, and you can read them and test them. Taxo sends an agent
  only what the rules can't settle.

## 7. Taxo: a two-fold system (40 s)

**Show:** the two folds. Inside one domain: the induction loop and the validation loop, with gold and a person between
them. Across domains: the meta loop.

**Say:**
- We introduce Taxo, a two-fold system with generalisable learning for this task.
- First, inside one domain, two loops. **Induction** turns a hand-labelled gold set into rules. **Validation** goes
  looking for the errors gold can't show.
- Second, across domains, a **meta loop** carries what worked to the next domain.

## 8. The induction loop (50 s)

**Show:** the gold set, and the three kinds of rule it turns into: the lattice, a registry of official brands, and a
route to an agent. Under them, one round: run, read the errors, propose one change, keep it only if sealed gold improves.

**Say:**
- Inside one domain, we start from a gold set that a person labelled by hand.
- The induction loop tries to turn it into deterministic rules, so that agents only see the hard cases. Three kinds:
  - **The lattice** counts word sequences across all of a brand's listings. "Khamrah" is in five titles and "Khamrah
    Qahwa" in two, so Khamrah is a family and Khamrah Qahwa is a product. No word lists.
  - **A registry.** An agent searches the web for each brand's official lines, and code writes them as a file the rules
    can read.
  - **A route.** What is left goes to the cheapest agent that can settle it: the title alone, the title plus the
    description, or a web search.
- Each round, an agent reads the errors and proposes one change. A gate in code keeps it only if it helps on gold that
  nobody tuned on.
- The goal is two numbers: more of gold labelled right, at a lower cost.

## 9. What induction buys (40 s)

**Show:** Figure A. F1 on gold and cost per 1,000 listings, round by round. Each point is labelled with the rule it
kept: rule 1, rule 2, and so on.

**Say:**
- This is the induction loop on fragrance. Each round keeps one rule.
- F1 on gold goes from [x] to [y], while the cost per thousand listings falls from [$a] to [$b].

## 10. How much each rule saves (35 s)

**Show:** Figure D, a waterfall: cost per 1,000 listings for the agent alone, then the drop from each rule the gate kept,
then Taxo. Beside it: agent only at 4M listings [$C], Taxo at 4M listings [$B], and [p] of listings settled without an
agent.

**Say:**
- This is the answer to "why not just an agent". Each step is one rule the gate kept, and how much it cut the cost.
- At four million listings the agent alone costs [$C]; Taxo costs [$B], and [p] of the listings never see an agent.
- None of it costs accuracy: the gate refuses any rule that lowers F1 on sealed gold.

## 11. Gold doesn't cover everything (40 s)

**Show:** the validation loop. Fresh listings → an agent validator labels them blind → where it disagrees with the
rules, a person settles it → new gold, and new errors for induction.

**Say:**
- But the gold set doesn't cover everything. Even with a clean test split, we can't say the rules generalise: a person
  chose those cases, and they can't contain every error a rule will make.
- That is why we have the validation loop. An agent labels new listings on its own, with more budget than the pipeline,
  and brings up the errors the system is making. Where it disagrees, a person settles it.
- Each round gives a new, frozen validation set.

## 12. Rule set 1 drops on fresh listings (30 s)

**Show:** Figure B, first half. Rule set 1 on gold, on validation set 1 and on validation set 2. The line falls.

**Say:**
- Rule set 1 scores [x] on gold, [y] on validation set 1 and [z] on validation set 2.
- Fresh listings find errors gold never showed us.

## 13. We iterate (45 s)

**Show:** the new rule that came out of validation (the routing YAML), and Figure B, second half: rule set 2 recovers on
validation set 2.

**Say:**
- So we iterate. New rules come from those errors. We join more brands, run more of the process, and look for the
  pattern underneath, not the single case.
- For example, [confirm from the run: small fragrance houses with no barcode name the product only in the description,
  and our rules stopped at the brand]. Induction turned that into a route: no barcode and a long description → the agent
  that reads the description.
- Rule set 2 recovers on validation set 2: [z] → [w].

## 14. A person teaches the validator (40 s)

**Show:** what the validator proposed (search the web for each brand's official lines), a person approving it, and
what it found. Gold grows from [n] to [m] cases.

**Say:**
- Human feedback matters here: it improves what the validator looks for.
- For example, the validator proposed searching the web for each brand's official products. We approved it, and it
  found gold cases we were missing.
- When the validator is wrong, the person tells it why. Each new version re-reads what earlier ones accepted, so errors
  we had marked as fine come back.
- This grows the correct cases and the overall accuracy: gold grows from [n] to [m] cases.

## 15. The meta loop: across domains (45 s)

**Show:** Figure C, the transfer matrix (food, fragrance, cars): rounds saved by starting from the other domain's
lessons. Next to it, what carried over and what didn't.

**Say:**
- This is where the meta loop comes in: we take which rules worked, with which validation, and apply them to other
  domains.
- Running the induction loop from those distilled rules, the next domain gets there faster.
- It doesn't transfer equally. From food to fragrance there was learning: [n] rounds saved. From fragrance to food,
  not much: [m].
- From fragrance to cars it is clear why: cars have a much more defined catalogue. Make, model and version are
  published and a VIN decodes them, so the registry does the work there, not the lattice.

## 16. Why it matters beyond labels (40 s)

**Show:** the tree is the first task; the method is the point. The pattern underneath, in three lines, and four places it
goes next: matching across shops, cars at Kavak, demand and trends, and any agent work that has to be trusted at scale.

**Say:**
- This is not a labelling system. The tree is the first task; the method is the point.
- The pattern underneath: turn agent judgment into procedures you can read, test and run for free; never let the system
  grade itself, so agents hunt for errors and a person decides what is true; keep what worked, with its scope, so the
  next problem starts ahead.
- It extends to more interesting tasks: matching the same product across shops; cars at Kavak, where make, model,
  version and trim decide the price; demand and trends, once search terms and hashtags roll up to a product; and any
  agent work that has to be trusted at scale.

## 17. Close (25 s)

**Show:** Systems will always say they're right. Taxo doesn't take their word for it. Three numbers, one per loop.

**Say:** Systems will always say they're right. Taxo doesn't take their word for it. Inside a domain it raises F1 on
gold it never tuned on and lowers the cost, and it grows its own validation with agents and a person. Across domains it
starts every new one ahead. Agents for what is truly hard, rules for the rest, and a person decides what is true.

---

## Backup slides

| Slide | For the question |
|---|---|
| Where we're coming from (two versions: side by side, stacked) | "Why not let the system grade itself?" Pedia replay `pe2`: the LLM judge's score climbed from 78% to 87%; the owner's labels went from 81% to 84%. 15 of the 48 changes made the judge happier and our labels worse, and the loop kept all 15. |
| Three trees | Food, fragrance and cars, level by level. |
| The lattice, step by step | How counting finds families and products. |
| The rules in YAML (two slides) | The vocabulary, a registry, a route, and the Pedia rule we will not accept (it matched the agent 145 of 145 times; its truth was the agent). |
| Guardrails | What went wrong in Pedia, and the rule that stops it here. |

## Figures to produce

| Figure | What it shows | Axes | From | Status |
|---|---|---|---|---|
| **A** | The induction loop on one domain | x: round. Two panels: F1 on sealed gold; cost per 1,000 listings. Each point labelled with the rule kept | induction runs on fragrance | to run |
| **B** | Gold is not enough, and iterating fixes it | F1 of rule set 1 (and then rule set 2) on gold, validation set 1, validation set 2 | validation rounds 1–2 | to run |
| **D** | How much each rule saves | waterfall: cost per 1,000 listings for the agent alone, the drop from each rule kept, the final pipeline; plus the 4M-listing bill both ways and the share settled without an agent | the agent-only baseline and the induction rounds on fragrance | to run |
| **C** | Transfer between domains | matrix, source × target: rounds saved to reach the target F1, warm start against cold | food ↔ fragrance; cars if there is data | to run |
| Says vs finds (backup) | Why we don't let a system grade itself | the LLM judge's score against the owner's labels, by round | Pedia replay `pe2` (`C:\Work\RSI\hackathon\runs\`) | in the deck |

## Questions to expect

| Question | Answer |
|---|---|
| Isn't this over-engineering a labeller? | The labels are the first task, not the point. An agent alone costs [$C] per pass at 4M listings and is wrong in ways it can't report; rules are free, testable and carry to the next domain. The same loops apply wherever an agent's answer has to be trusted at scale. |
| Why not just use an agent for everything? | Cost, and errors you can't see. In Pedia, the agent wrongly set aside most of the listings it parked. Rules are cheap and testable, and agents get only the hard cases. |
| Isn't the validator just another agent you trust? | No. It is scored on gold at every version, its agreements are spot-checked, and only a person settles a disagreement or changes gold. |
| How do you know a rule generalises? | Sealed gold is whole brands that the loop never tunes on. And the validation loop tests the rules on listings gold doesn't contain. |
| What does a person actually do? | Settles the disagreements the validation loop raises (about [n] per round), and tells the validator what to look for. |
| What about cars? | Make, model and year come from a VIN. Version and trim are where listings disagree, and that is where the lattice and routes come in. |
