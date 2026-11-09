# Toys domain, including games

There is ONE toys domain. Physical toys, tabletop/card games, puzzles and video-game products are subtypes, not independent domains. Clothing and footwear are the other two additions.

Use TAXO_TOYS_LISTINGS for the current combined RAW Parquet. Alternatively set TAXO_DATA_DIR to DATA/Listings/RAW; the adapter discovers toys/subset-1 or the existing legacy-named games/subset-1 delivery. The source folder name does not create a games domain. No RAW files are renamed or modified.

The adapter preserves source fields and signed keys, emits include/exclude/hold decisions, and keeps platform, edition, language, physical/digital form and base-game/expansion evidence when present. The harness partitions game subtypes and evidenced identity so software, hardware, accessories and physical toys are not merged together.

All initial rules remain proposals. Earlier separate games/toys counts and E2E reports belong to the superseded split; they are not measurements of this combined domain. No new tests or taxonomy runs were performed for this correction, per the user's instruction. Earlier evidence remains in the previous PRs and local run directories. Future runs save placements, nodes, scope decisions, rule events, errors and an input/code/rule hash manifest through taxo.bootstrap.
