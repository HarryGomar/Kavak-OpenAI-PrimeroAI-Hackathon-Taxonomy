# Bounded independent Codex CLI validator

For food, clothing, unified toys (including games), and footwear only. No fragrance execution or changes.

On 2026-11-09 the refreshed `origin/main` was `b688f7c`. Its validator used
`openai-agents`; no installed CLI implementation or invocation was found in the
remote branches or local Taxo worktrees. The subsequent `distill/rounds` branch
contains lessons, not that implementation. This entry point supplies the missing
transport without replacing another contributor's SDK code.

`taxo/validator_cli.lock.json` pins `codex-cli 0.166.0`, `gpt-6.1-sol`, reasoning
effort `xhigh`, and `service_tier="fast"` (request value `priority`). It uses the
installed, already authenticated `codex` executable. No SDK/API fallback exists.
CLI upgrades must be coordinated across all domains; a version mismatch fails.
Each run records executable, code, prompt, domain configuration and input hashes,
Git HEAD, commands, final structured outputs, usage, elapsed time, and errors.
Served tier and cost remain unavailable unless explicitly reported by the CLI.

## Invocation

Install the locked Python dependencies with `uv sync --frozen`. Set
`TAXO_DATA_DIR` or the domain-specific source variables from its documentation.
Use fresh directories outside Git. For example:

```powershell
uv run python -m taxo.pipeline clothing --construct --limit 50 --output C:/local-runs/<run-id>/clothing/iteration-00/construction
uv run python -m taxo.validate_cli clothing --construction C:/local-runs/<run-id>/clothing/iteration-00/construction --output C:/local-runs/<run-id>/clothing/iteration-00/validation
```

Construction now saves a complete adapter `listings.jsonl` snapshot alongside its
existing evidence. Its `selection.listing_ids` and `adapter_order` method identify
the deterministic prefix sample. This is reproducible, not a population-random
sample. Use up to 100 source observations and record this sampling limitation.

Validation consumes that snapshot, never reselects rows, and independently labels
all observations including screened rows. Only title, source-reported brand,
source name and an explicit allowlist of raw evidence fields reach the CLI.
It never passes pipeline decisions, Pedia placements, imported labels or review
outcomes. Source evidence is untrusted data. The validator runs in an empty
temporary working directory with user config ignored, web disabled, read-only
sandbox, and instructions prohibiting tools. Tool use invalidates a batch.

The subprocess invocation uses documented `codex exec --json --output-schema
--output-last-message --ephemeral --ignore-user-config` flags plus explicit model
and configuration overrides. See [official CLI reference](https://developers.openai.com/codex/cli/reference/)
and [configuration reference](https://developers.openai.com/codex/config-reference/).
Events are filtered in memory: private reasoning and unfiltered stdout/stderr
are not saved. Usage counts may include reasoning-token totals, never content.
There are no automatic retries; preserve failed attempts and use a fresh directory.

## One bounded proposal iteration

Freeze the initial CLI judgments and unchanged source snapshot. Inspect the
disagreements; propose one general domain change, run construction once more on
the same source observations, and compare to the frozen judgments using:

```python
from pathlib import Path
import json
from taxo.validate_cli import compare
judgments = json.loads(Path("<baseline-validation>/judgments.json").read_text(encoding="utf-8"))
output = Path("<iteration-01>/comparison")
output.mkdir(parents=True, exist_ok=False)
compare("clothing", Path("<iteration-01>/construction"), judgments, output)
```

Keep any proposed change in shadow/proposal or an isolated experiment until
reviewed human labels support admission. Report changed paths, routing,
abstentions, regressions and counterexamples. Model agreement is not accuracy.
Check full source-snapshot hashes before claiming unchanged evaluation evidence.
Use `blind-review-queue.json` for human labeling; it hides both competing answers.
Imported Pedia annotations, model silver, synthetic examples and human outcomes
remain separate evidence classes. This entry point never reads or writes gold.

The one-observation integration smoke run used actual clothing RAW data and saved
artifacts outside Git under
`C:/Users/eduar/Desktop/HACKATON/tasks/taxo-four-20261109-cli/smoke/`.
It verified the installed CLI path and a structured answer, not classification
accuracy. No unit or end-to-end test suite was run.
