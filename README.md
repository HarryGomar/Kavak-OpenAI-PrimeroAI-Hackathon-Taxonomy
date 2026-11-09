# Kavak × OpenAI — PrimeroAI Hackathon: Taxonomy

**Taxo** learns how to build product trees (brand › line › product › variant) from marketplace listings, for any
commerce domain. It is a two-fold system:

- **Inside one domain**, two loops:
  - the **induction loop** turns a hand-labelled gold set into cheap rules;
  - the **validation loop** has an agent hunt for errors on fresh listings, and a person settles them.
- **Across domains**, the **meta loop** carries what worked to the next domain.

| File | For |
|---|---|
| [SPEC.md](SPEC.md) | The system: why trees, the pipeline and its YAML rules, the induction, validation and meta loops, data, metrics, guardrails, and what to port from Pedia |
| [PRESENTATION.md](PRESENTATION.md) | The talk script, slide by slide, with the figures still to produce and questions to expect |
| [slides/index.html](slides/index.html) | The deck: open it in a browser. 13 slides. N shows the notes, O the overview. Run results go in `RESULTS` at the top of its script |

Built on what worked in Pedia ([Mantis4Real/pedia-harness](https://github.com/Mantis4Real/pedia-harness), local at
`C:\Work\Pedia-Harness\repo`). The original notes are in `C:\Work\Kavak-OpenAI-Primero-Hackathon\Taxo.md`.

Data stays in the home that owns it: this repo keeps pointers and toy samples only.
