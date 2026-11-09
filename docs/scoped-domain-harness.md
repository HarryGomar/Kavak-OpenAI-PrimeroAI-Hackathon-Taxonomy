# Toys, clothing and footwear harness hooks

These hooks load the three domain packs, local proposal checks and admitted agent instructions. Raw-only construction retains numeric identity tokens and source-reported brands. It saves provisional nodes, placements, scope decisions, rule events, observations, errors and a hashed run manifest under ignored runs/<domain>/ directories. Construction makes no model calls or gold reads and promotes no rules.

Fragrance-specific normalization, pack, rule files, brand parser and evaluation gate are unchanged. No food or games domain files are changed by this integration.

Set TAXO_DATA_DIR to the current RAW root or configure each adapter explicitly. Later commands, using fresh output directories:

```powershell
python -m taxo.pipeline toys --construct --limit 100 --output runs/toys/baseline-01
python -m taxo.pipeline clothing --construct --limit 100 --output runs/clothing/baseline-01
python -m taxo.pipeline footwear --construct --limit 100 --output runs/footwear/baseline-01
```

These commands were not executed after the scope correction. New-domain gold evaluation needs a configured scorer and reviewed labels. No additional unit or E2E tests were run after the user's stop-testing instruction.
