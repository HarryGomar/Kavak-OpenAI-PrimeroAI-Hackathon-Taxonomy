# Footwear domain

Reads the current manifested footwear RAW export and source sidecar. The current manifest records 2,948 rows. Signed observation IDs, all export fields and original source rows are preserved. See evidence/footwear-inputs.json for current paths and hashes. Source files are unchanged.

Set TAXO_DATA_DIR to DATA/Listings/RAW, or set TAXO_FOOTWEAR_LISTINGS explicitly; optional TAXO_FOOTWEAR_SOURCE_ROWS and TAXO_FOOTWEAR_MANIFEST select sibling evidence. TAXO_FOOTWEAR_TAXONOMY can supply external nodes; absent means no trusted tree.

Two deterministic checks and three agent instructions are proposals. Preserve numbered model identity, keep size/width/colour distinct from models, and review standalone accessories. No human accuracy, rule admission, taxonomy run or new tests are claimed. Later execution uses the shared --construct path and saves artifacts under runs/footwear/.
