# Universal Codex CLI execution for Taxo

All model roles and registered domains use the same installed Codex CLI transport:
placer, validator, proposer, improver, and the pipeline title-placement step.
The curator remains deterministic Python code. There is no OpenAI SDK/API execution
path or API-key requirement. No fragrance data was run or changed for this migration.

On 2026-11-09 the refreshed `origin/main` was `b688f7c`. Its validator used
`openai-agents`; no installed CLI implementation or invocation was found in the
remote branches or local Taxo worktrees. The subsequent `distill/rounds` branch
contains lessons, not that implementation. This entry point supplies the missing
transport, then expands it universally at the user's request. The old SDK model
calls are replaced, while existing Python tools and rule gates remain.

`taxo/validator_cli.lock.json` pins `codex-cli 0.166.0`, `gpt-6.1-sol`, reasoning
effort `xhigh`, and `service_tier="fast"` (request value `priority`). It uses the
installed, already authenticated `codex` executable. No SDK/API fallback exists.
The historical lock filename is shared by every role and domain. CLI upgrades must be coordinated across all domains; a version mismatch fails.
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
sandbox, and instructions prohibiting tools. Tool use invalidates a batch. Batch validation
always disables web to keep it a supplied-evidence comparison; the role validator
can use native CLI web search when its domain setup enables it.

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

## Universal roles and Python tools

`taxo/codex_cli.py` implements the single CLI transport. It checks the installed
version, applies the common model/xhigh/FAST pin, enforces JSON Schema locally,
and saves filtered events, structured final output, usage, errors and hashed
manifests. `taxo/roles/runtime.py` bounds the structured tool loop (six turns by
default, eight requests per turn). Python executes only registered tools by name;
models cannot execute Python or inspect the repository. The placer retains
`search_taxonomy`, `read_node`, and `check_rules`. The validator retains
`similar_brands`; its optional web search uses Codex CLI's native web setting.
Unknown tools/nodes, blocked placements and invalid outputs fail explicitly.
Placement gates run in code even if the model omits the rule-check tool.

The factories return `CliAgent` values; callers use `taxo.roles.runtime.run_sync`
instead of the removed SDK Runner. It returns `final_output` plus `artifacts`.
Role prompts/schemas, model tool requests/results, shadow findings and final
placement gate outcomes are preserved outside Git. No private reasoning content
or unfiltered stdout/stderr is retained. All model selection comes from the
shared lock, including for legacy domain validator files carrying old `model`
fields; those fields no longer choose runtime models. Change the shared pin
explicitly to coordinate model changes.

Placer invocation (any registered domain with a configured taxonomy):

```powershell
uv run python -m taxo.cli place cars --n 1
```

Other roles have an explicit saved-artifact entry point:

```powershell
uv run python -m taxo.cli run-role cars validator --input C:/local-runs/validator-input.json --output C:/local-runs/fresh-validator
uv run python -m taxo.cli run-role cars proposer --input C:/local-runs/reviewed-disagreements.json --output C:/local-runs/fresh-proposer
uv run python -m taxo.cli run-role cars improver --input C:/local-runs/reviewed-validator-mistakes.json --output C:/local-runs/fresh-improver
```

Validator input is `{"listing": <adapter Listing>, "brands": [<source brand names>]}`.
Code projects the listing to the evidence allowlist, strips imported Pedia brand
assignments from legacy adapters, and never passes an extra proposed placement.
Proposer/improver inputs contain only the scoped cases supplied by the caller;
never pass a gold file or sealed split. Mark unreviewed model evidence and
synthetic demonstrations explicitly; neither authorizes rule admission.

The pipeline's existing `--agent-calls` route also uses this transport and no
longer checks an API key. It remains opt-in and bounded. Domain taxonomy,
adapter, labeling and scorer readiness are separate from transport support;
this migration does not fabricate missing data/gold or implement unrelated
domain pipelines. Every registered domain, including future packs, is selectable
in batch validation without a four-domain allowlist. No separate games domain exists.

## Frozen in-flight runs

The four coordinated 50-observation baselines and one proposal experiment each
remain on shared commit `21c65f8` and lock version 1 for comparability. This
universal expansion uses lock version 2 with the same installed CLI/model/FAST
settings. It does not relabel their frozen observations or rerun their loops.
The universal change remains in PR #8 and the coordinator worktree; no merge to
main is authorized. Domain worktrees can take the completed universal commit
after preserving their frozen run evidence.
