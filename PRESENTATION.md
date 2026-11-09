# Taxo: presentation script

*About 7 minutes, 12 slides. **Show** is what is on screen; **Say** is what you say. Numbers in [brackets] come from
today's runs: fill them in or cut the line, and never present a placeholder as a result. The system is in
[SPEC.md](SPEC.md); the deck is [slides/index.html](slides/index.html). Slides 3, 6 and 7 have variants in the deck
(3A/3B, 6A/6B/6C, 7A/7B): pick one of each and delete the rest.*

The story, in one breath: self-improving systems are hard to trust because they grade themselves; to understand a
market you connect listings into product trees; at four million listings an agent alone is too expensive and wrong in
ways you can't see; Taxo is a pipeline of free rules with three loops that improve it, and no loop lets the system grade
itself. The tree is the first task; the method is the point.

---

## 1. Title (10 s)

**Show:** Taxo: learning to build product trees for any commerce domain.

**Say:** We're going to show you Taxo, a system that learns how to turn messy marketplace listings into clean product
trees, and gets faster at it with every domain it sees.

## 2. A system that grades its own work climbs the wrong hill (40 s)

**Show:** Pedia replay `pe2`: the LLM judge's score against the owner's labels over four rounds (the mean of six runs,
with the runs faint behind). Beside it: 15 of 48.

**Say:**
- Before the problem, the lesson that shaped Taxo. Self-improving systems are easy to build and hard to trust.
- In Pedia, a loop changed its own rules and an LLM judge scored each round. The judge went from 78% to 87%. The
  owner's labels went from 81% to 84%.
- 15 of the 48 changes made the judge happier and the labels worse, and the loop kept every one.
- To improve a system you need a score it can't move by itself. That is the constraint on everything that follows.

## 3. Understanding a market means connecting its listings into a tree (40 s)

**Show (3A):** Lattafa › Khamrah, with its five listings as photos (the brand's site, Amazon, Walmart, two TikTok Shop
sellers), and Lattafa › Khamrah Qahwa with its Walmart listing.

**Show (3B):** two trees with a photo at each leaf. Food: Oreo › Double Stuf › Golden. Fragrance: Lattafa › Khamrah ›
Khamrah, Khamrah Qahwa.

**Say:**
- To understand a commerce market you connect listings from different marketplaces. This is one perfume: five shops,
  five titles. Until you know they're the same product, you can't add up its price, its reviews or its demand.
- The way to connect them is a tree, in every domain: brand, product, variant, listings.
- A size, a 12-pack or a gift set is never a new node. A flanker like Khamrah Qahwa is.

## 4. Four million listings, and the hard ones look easy (30 s)

**Show:** 4M, and three photos: a variety pack sold by Muchai (a shop, not a brand), a Khamrah gift set, an Oreo Minis
Golden 12-pack.

**Say:**
- With four million listings this gets really complicated. The same product is written fifty different ways.
- Shops pose as brands. A gift set is still its maker's product. A 12-pack is not a new product.
- Labelling four million listings by hand doesn't scale.

## 5. Why not send every listing to an agent? (40 s)

**Show:** the bill, 4M × [$c] per 1,000 = [$C]; and the errors: the agent's F1 on gold [f], and Pedia's 59%.

**Say:**
- The obvious answer is an agent for every listing. At [$c] per thousand, four million cost [$C] for one pass, and again
  for every refresh and every new domain.
- And it is wrong in ways you can't see: on gold the agent alone scores [f]; in Pedia, 59% of the food listings the
  agent set aside as unplaceable were real products.
- So this is not over-engineering a labeller. Rules are free, and you can read and test them. Taxo sends an agent only
  what the rules can't settle.

## 6. The system (50 s)

**Show (6A):** the pipeline in the middle (listings → free rules → a paid agent for what's left → the tree), the
induction loop above it, the validation loop below, the meta loop on the right.

**Show (6B):** the two folds: food, fragrance and cars on the left, joined by lessons; one domain zoomed in on the right.

**Show (6C):** who does what. Rows: code, agents, a person. Columns: placing listings, induction, validation, meta.

**Say:**
- Taxo is a pipeline of free rules, and three loops that improve it.
- **Induction:** run the rules on a hand-labelled gold set; an agent reads the errors and proposes one rule; a gate in
  code keeps it only if F1 on sealed gold rises.
- **Validation:** a validator agent labels fresh listings blind; where it disagrees with the pipeline, a person settles
  it, and that becomes new gold.
- **Meta:** what worked, with its scope, starts the next domain.
- Code does the work, agents do the judgment, and a person decides what is true. No loop lets the system grade itself.

## 7. Induction turns the gold set into rules you can read (50 s)

**Show (7A):** one Walmart title, "Lattafa Khamrah Qahwa Eau De Parfum 3.4 Oz Unisex Fragrance Lattafa", through the
four free rules (vocabulary, registry, lattice, route), each with its YAML. It lands on Lattafa › Khamrah › Khamrah
Qahwa with no agent call.

**Show (7B):** the round in five lines, beside a kept rule as YAML (the Lattafa registry and the lattice counts).

**Say:**
- Here is what a rule looks like. The vocabulary strips sizes, concentrations and audiences: they are variants, never
  names. The registry holds each brand's official lines, found once by an agent and written down by code.
- The lattice counts word sequences across all of a brand's listings: Khamrah is in five titles and Khamrah Qahwa in
  two, so Khamrah is a family and Khamrah Qahwa a product. No word lists.
- Only the unclear ones go to an agent, the cheapest one that can settle them.
- Induction learns these files. Each round an agent proposes one change, and a gate in code keeps it only if F1 on
  sealed gold rises and the cost doesn't.

## 8. What induction buys, round by round (40 s)

**Show:** Figure A. F1 on sealed gold, and cost per 1,000 listings against the agent alone, round by round, each point
labelled with the rule it kept. Under it: the 4M bill both ways, and the share of listings that never sees an agent.

**Say:**
- This is induction on fragrance. Each round keeps one rule. F1 on gold goes from [x] to [y], while the cost per
  thousand listings falls from [$a] to [$b].
- At four million listings the agent alone costs [$C]; Taxo costs [$B], and [p] of listings never see an agent.
- None of it costs accuracy: the gate refuses any rule that lowers F1 on sealed gold.

## 9. Gold doesn't cover everything (45 s)

**Show:** the validation loop as four steps, and Figure B: rule set 1 on gold, validation set 1 and validation set 2.

**Say:**
- Even with a clean test split we can't say the rules generalise: a person chose the gold cases, and they can't contain
  every error a rule will make.
- So an agent labels fresh listings on its own, with more budget than the pipeline, and brings up the errors. Where it
  disagrees with the rules, a person settles it. Each round gives a new frozen validation set.
- Rule set 1 scores [x] on gold, [y] on validation set 1 and [z] on validation set 2. Fresh listings find errors gold
  never showed us.

## 10. So we iterate, and a person teaches the validator (45 s)

**Show:** the new routing rule as YAML, and rule set 1 → 2 on validation set 2, [z] → [w]. Beside it, what the person
added, and gold growing from [n] to [m] cases.

**Say:**
- New rules come from those errors. We join more brands and look for the pattern underneath, not the single case.
- For example, [confirm from the run: small fragrance houses with no barcode name the product only in the description,
  and our rules stopped at the brand]. Induction turned that into a route to the agent that reads the description. Rule
  set 2 recovers on validation set 2: [z] → [w].
- A person improves the validator. It proposed searching the web for each brand's official lines; we approved it, and
  it found gold cases we were missing. When it is wrong, the person tells it why, and each new version re-reads what
  earlier ones accepted. Gold grows from [n] to [m] cases.

## 11. Across domains, what worked carries over (40 s)

**Show:** Figure C, rounds saved against a cold start: food → fragrance [n], fragrance → food [m], fragrance → cars [k].

**Say:**
- The meta loop takes which rules worked, with which validation, and starts the next domain's induction from them.
- It doesn't transfer equally. From food to fragrance there was learning. From fragrance to food, not much.
- From fragrance to cars it's clear why: make, model and version are published and a VIN decodes them, so the registry
  does the work there, not the lattice.

## 12. Close (35 s)

**Show:** "Systems will always say they're right. Taxo doesn't take their word for it." Under it, the method in three
lines and where it goes next.

**Say:**
- This is not a labelling system. The tree is the first task; the method is the point.
- Turn agent judgment into rules you can read, test and run for free. Never let a system grade itself: agents hunt for
  errors and a person decides what is true. Keep what worked, with its scope, so the next problem starts ahead.
- It goes to matching across shops, cars at Kavak, demand and trends, and any agent work that has to be trusted at
  scale.
- Systems will always say they're right. Taxo doesn't take their word for it.

---

## Figures to produce

| Figure | What it shows | Axes | From | Status |
|---|---|---|---|---|
| **A** | Induction on one domain (slide 8) | x: round. Two panels: F1 on sealed gold; cost per 1,000 listings against the agent alone. Each point labelled with the rule kept | the agent-only baseline and the induction runs on fragrance | to run |
| **B** | Gold is not enough, and iterating fixes it (slides 9, 10) | F1 of rule set 1 (then rule set 2) on gold, validation set 1 and validation set 2; gold's size before and after | validation rounds 1–2 | to run |
| **C** | Transfer between domains (slide 11) | source × target: rounds saved to reach the target F1, warm start against cold | food ↔ fragrance; fragrance → cars | to run |
| Says vs finds | Why we don't let a system grade itself (slide 2) | the LLM judge's score against the owner's labels, by round | Pedia replay `pe2` (`C:\Work\RSI\hackathon\runs\`) | in the deck |

## Questions to expect

| Question | Answer |
|---|---|
| Isn't this over-engineering a labeller? | The labels are the first task, not the point. An agent alone costs [$C] per pass at 4M listings and is wrong in ways it can't report; rules are free, testable and carry to the next domain. The same loops apply wherever an agent's answer has to be trusted at scale. |
| Why not just use an agent for everything? | Cost, and errors you can't see. In Pedia, the agent wrongly set aside most of the listings it parked. Rules are cheap and testable, and agents get only the hard cases. |
| Isn't the validator just another agent you trust? | No. It is scored on gold at every version, its agreements are spot-checked, and only a person settles a disagreement or changes gold. |
| How do you know a rule generalises? | Sealed gold is whole brands that the loop never tunes on. And the validation loop tests the rules on listings gold doesn't contain. |
| What does a person actually do? | Settles the disagreements the validation loop raises (about [n] per round), and tells the validator what to look for. |
| What about cars? | Make, model and year come from a VIN. Version and trim are where listings disagree, and that is where the lattice and routes come in. |
