# Taxo: presentation script

*About 8 minutes, 13 slides. **Show** is what is on screen; **Say** is what you say. Numbers in [brackets] come from
today's runs: fill them in or cut the line, and never present a placeholder as a result. The system is in
[SPEC.md](SPEC.md); the deck is [slides/index.html](slides/index.html).*

The story in one breath: a system improves only as far as its eval, and most useful tasks have no ground truth to check
against. We took one that looks easy and isn't, connecting a market's listings, and built a system that improves at
it on three fronts (accuracy, cost, speed): rules learned from a small gold set, an eval that itself gets better with a
person's feedback, and lessons carried to the next domain. Everything is in the evals.

---

## 1. Title (10 s)

**Show:** Taxo. Learning to build product trees for any commerce domain.

**Say:** We're going to show you Taxo: a system that keeps improving at a task with no ground truth.

## 2. A system improves only as far as its eval (60 s)

**Show:** left, the system's own eval climbing round by round, 78% → 87%; then the human check done afterwards, 81% →
84%. Right, three short points.

**Say:**
- Hill-climbing is hard. We've tried it on several problems, and continual learning is not a solved problem.
- Evals are what drive performance. In our last project a loop improved its own rules and climbed its own eval, an LLM
  judge, from 78% to 87%. When we checked by hand afterwards, it had gone from 81% to 84%: a third of the gain. 15 of
  the 48 changes it kept made our labels worse.
- Where a task checks itself, like a loss or a test suite, that's enough. Karpathy's autoresearch can hill-climb on its
  own.
- Most useful tasks have no such check. So the eval itself needs a method to improve: what counts as right, and how we
  check it. That's what this talk is about.

## 3. Seemingly easy, deceptively hard: connect a market's listings (35 s)

**Show:** two product trees with photos at the leaves. Food: Oreo › Double Stuf › Golden. Fragrance: Lattafa › Khamrah
› Khamrah and Khamrah Qahwa.

**Say:**
- The task we tried this on comes from our own work. To understand a market you have to match and connect its
  listings into product trees.
- Until you know which listings are one product, you can't add up its price, its reviews or its demand.
- It looks trivial for a person and is surprisingly hard for an agent. A size or a 12-pack is never a new product; a
  flanker like Khamrah Qahwa is.

## 4. What we want the system to improve, by itself (40 s)

**Show:** three columns: accuracy (F1 on gold and on listings nobody labelled), cost (dollars for all 2 million
listings) and speed (time to place them all), each with what an agent on everything gets: [f], [$C], [h].

**Say:**
- We want the system to improve on three fronts, by itself.
- Accuracy: an agent on every listing gets [f] on our gold set. Cost: [$C] to place all two million listings, again on
  every refresh and in every new domain. Speed: [h] to place them all; rules are near-instant, an agent call takes
  seconds.
- Cost and speed check themselves. Accuracy doesn't, so that's where the loops do their work. That's what makes it a
  good task for self-improvement.

## 5. Over 2 million listings, and every constraint points to rules (30 s)

**Show:** four problems and what we do about each: little time to label → loop 1; agents too expensive to run on
everything → the solver; we don't know if we're improving → loop 2; every domain starts from zero → loop 3.

**Say:**
- We have little time to label cases, agents cost too much to run on everything, we don't know if we're improving, and
  we don't want each new domain to start from zero.
- That's why we want rules: they are free, you can read and test them, and they carry over. Each problem is one part of
  the system.

## 6. The architecture: a solver and three loops (40 s)

**Show:** one domain opened up on the left: the solver in the middle (listings → free rules → an agent only for what
rules can't settle → product tree), loop 1 above it, loop 2 below. On the right, loop 3: food, fragrance and cars joined
by lessons.

**Say:**
- We propose this architecture. The solver places listings with free rules, and sends an agent only what they can't
  settle.
- Three loops improve it. Loop 1 learns rules from a small gold set. Loop 2 improves the eval itself. Loop 3 carries what
  worked to the next domain. We'll go through each with an example.

## 7. Loop 1, induction: a few labelled cases become rules (50 s)

**Show:** one Walmart title, "Lattafa Khamrah Qahwa Eau De Parfum 3.4 Oz Unisex Fragrance Lattafa", going down the
rules. Each step shows what it decided, and beside it the rule file that decided it: the vocabulary (variants),
the registry (Lattafa's official lines), the lattice counts and a route. The registry places it as Lattafa › Khamrah ›
Khamrah Qahwa with no agent call; the lattice and the route are greyed out, as the steps that would run if it hadn't.

**Say:**
- Loop 1 starts from cases we labelled by hand, and induction turns them into rules. Each rule is a file you can read.
- Here is one title. The vocabulary file says which words are variants, so "Eau De Parfum 3.4 Oz Unisex" is stripped.
- The registry file holds Lattafa's official lines, found once by an agent with web search and written down by code.
  Khamrah Qahwa is in it, so the listing is placed with no agent call.
- If it hadn't been, the lattice counts names across the brand's listings, and a route file sends whatever is still
  unclear to the cheapest agent that can settle it.

## 8. Loop 1: the lattice finds products by counting (40 s)

**Show:** six Lattafa titles. 1, strip the brand and the variants. 2, count every run of words: khamrah 5, khamrah qahwa
2, khamrah dukhan 1, yara 1, with a floor at two titles. 3, the tree it builds: Lattafa › Khamrah (family) › Khamrah,
Khamrah Qahwa; Dukhan and Yara left unclear.

**Say:**
- This is how the lattice works. Strip the brand and the variant words, then count every run of words across the
  brand's titles.
- Each title joins its longest run seen at least twice. That gives two products, Khamrah and Khamrah Qahwa, and
  because they share "khamrah", Khamrah is a family.
- Dukhan and Yara are below the floor: the registry settles them if it knows them, otherwise an agent does.
- No word lists: add a word to the vocabulary and the count changes on the next run.

## 9. Loop 1: F1 on the gold set as each rule is added (30 s)

**Show:** Figure A: F1 on gold, round by round, each point labelled with the rule kept.

**Say:**
- Each round an agent proposes one rule, and a gate in code keeps it only if F1 on gold rises.
- F1 on gold goes from [x] to [y] as the rules are built.

## 10. Loop 2, validation: improve the eval itself (55 s)

**Show:** the loop in four steps. Beside it, Figure B: F1 of the solver as the checks get stricter (gold, then checks 1
and 2), for rule set 1 and rule set 2.

**Say:**
- A small gold set doesn't cover everything, so loop 2 improves the eval itself.
- A validator agent runs on listings nobody labelled, raises errors and cases it isn't confident about, and brings them
  to us. We label them, and what counts as right gets sharper.
- Then it asks what is going on. For example, [confirm from the run: small houses with no barcode name the product only
  in the description]. That goes back into the rules, and into a stricter check, so confidence goes up.
- On the graph: as the checks get stricter, rule set 1 falls from [x] to [z]; after refining, rule set 2 gets back to
  [w]. We improve the definition of right, the way we check it, and the solver underneath.

## 11. Loop 3, meta: the next domain starts ahead (35 s)

**Show:** a lesson as YAML (strip variants before counting, scope global), and rounds saved against a cold start: food →
fragrance [n], fragrance → food [m], fragrance → cars [k].

**Say:**
- The last loop distils what worked, with its scope, into lessons for the next domain.
- A domain that starts from those lessons gets there in fewer rounds. Food to fragrance carried; fragrance to food, not
  much. Cars have a published catalogue, so there the registry does the work.

## 12. Results: what each loop adds, in each domain (35 s)

**Show:** a table, fragrance, food and cars: F1 on fresh listings and cost per 1,000 listings for an agent on everything,
after loop 1, after loop 2, and with loop 3's head start.

**Say:**
- We have more under the hood, like the wiki our agents keep. Happy to go into it after; there isn't time for the whole
  architecture now.
- Here is what each loop adds in each domain. [Read the one row that matters most once the numbers are in.]

## 13. Everything is in the evals (30 s)

**Show:** Everything is in the evals. We improved a task that isn't directly verifiable by improving how we check it,
with feedback. Next: customer-feedback models, and any task without a ground truth.

**Say:**
- What matters is that we improved a task that isn't directly verifiable.
- We showed different kinds of verification, and improved the evaluation itself with feedback. We think it extends to
  other tasks, like customer-feedback models.
- Everything is in the evals. As we improve the system, we have to improve the evals.

---

## Figures to produce

| Figure | Slide | What it shows | From | Status |
|---|---|---|---|---|
| Agent alone | 4 | F1 on gold, dollars and hours for all 2M listings with an agent on everything | the agent-only baseline | to run |
| **A** | 9 | F1 on gold, round by round, each point labelled with the rule kept | induction runs on fragrance | to run |
| **B** | 10 | F1 of rule set 1 and rule set 2 on gold, checks 1 and checks 2 | validation rounds 1–2 | to run |
| **C** | 11 | Rounds saved to reach the target F1, warm start against cold | food ↔ fragrance; fragrance → cars | to run |
| **Results** | 12 | F1 on fresh listings and cost per 1,000 listings: agent alone, after loops 1, 2 and 3, by domain | all runs | to run |
| Own eval vs human check | 2 | The LLM judge's score by round, against our labels at the start and after round 4 | Pedia replay `pe2` (`C:\Work\RSI\hackathon\runs\`), mean of 6 runs, 245 held-out listings | in the deck |

## Questions to expect

| Question | Answer |
|---|---|
| Isn't this over-engineering a labeller? | The labels are the first task, not the point. The point is improving a task with no ground truth by improving its eval. Rules are free, testable and carry to the next domain; the same loops apply wherever an answer can't be checked directly. |
| Why not just use an agent for everything? | Cost, speed, and errors you can't see. In our last project, 59% of the food listings the agent set aside as unplaceable were real products. |
| Isn't the validator just another agent you trust? | No. It is scored on gold at every version, its agreements are spot-checked, and only a person settles a disagreement or changes gold. |
| How do you know a rule generalises? | The gate tests it on sealed gold the loop never tunes on, and loop 2 tests it on listings gold doesn't contain. |
| What does a person actually do? | Labels the small gold set, labels what the validator brings up (about [n] cases per round), and tells it what to look for. |
| What about cars? | Make, model and year come from a VIN. Version and trim are where listings disagree, and that is where the lattice and routes come in. |
