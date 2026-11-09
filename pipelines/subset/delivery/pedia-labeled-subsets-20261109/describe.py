from pathlib import Path
root=Path('tasks/pedia-labeled-subsets-20261109')
old=(root/'previous-pr-body.md').read_text(encoding='utf-8-sig')
intro='''The pipeline also exports listing-level Pedia reference labels directly from the existing raw Silver subsets. The source is the current pinned Pedia placement graph, and each matched listing stays one row with every original Silver column plus Pedia brand/model/variant names and IDs, family/sub-brand paths, full typed path, canonical ancestors, placement metadata and release pins. Exact signed observation IDs and source IDs are used, with the verified historical identity bridge where needed. Conflicting entity assignments remain unlabeled. Missing hierarchy levels remain empty.

The new `run-label-pedia.ps1` mode processed the six current `pedia-4500-outside-500-v3-content-checked` raw inputs. Each yielded 4,500 labeled rows and 500 unchanged unmatched rows, with a reason index and nine 500-row labeled batches. Inputs were not overwritten or resampled, and no new models or cluster annotations were used. This extraction ran locally without smoke, end-to-end or unit tests, as requested. No Drive upload was performed.

'''
(root/'pr-body.md').write_text(intro+old,encoding='utf-8')
