from pathlib import Path
root=Path('C:/Users/eduar/Desktop/HACKATON')
p=root/'repo-taxonomy/pipelines/subset/README.md'
body=p.read_text(encoding='utf-8')
start=body.index('## Label the saved Silver subsets with Pedia')
end=body.index('## Extract raw Silver subsets',start)
section=(root/'tasks/pedia-labeled-subsets-20261109/gold-readme-section.md').read_text(encoding='utf-8')
p.write_text(body[:start]+section+'\n'+body[end:],encoding='utf-8')
base=(root/'tasks/pedia-labeled-subsets-20261109/previous-pr-body.md').read_text(encoding='utf-8-sig')
intro='''The pipeline creates parallel listing-level Gold Parquets from the already prepared RAW Silver subsets. Each output contains only the exact `silver_id` and current pinned Pedia identity values: brand, canonical name, model, variant, family/sub-brand paths, full typed path, canonical IDs and placement/release provenance. Silver payload columns are not copied into Gold, and input subsets are neither resampled nor mixed.

There is one Gold file for each of the six current RAW inputs, retaining the same domain and subset number. Each RAW input has 5,000 listings; each Gold output contains exactly its 4,500 in-Pedia IDs. The 500 outside-Pedia listings remain only in RAW. All six RAW copies match the active Drive `DATA/Listings/RAW` files by checksum. Direct saved-file ID inspection confirms each Gold ID set exactly equals its own RAW subset's in-Pedia IDs, with unique Gold IDs and zero foreign IDs. No smoke, unit or end-to-end suite was run, and Gold was not uploaded to Drive.

'''
(root/'gold-pr-body.md').write_text(intro+base,encoding='utf-8')
