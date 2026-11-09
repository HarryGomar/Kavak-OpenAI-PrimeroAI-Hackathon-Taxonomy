"""The hackathon's shared fragrance data on Drive (Hackathon-Kavak-OpenAI-Primero/DATA/Listings), read in place:

    RAW/fragrance/subset-{1,2,3}/fragrance_listings.parquet     5,000 listings each (key: source_record_key)
    Labeled/fragrance/subset-{1,2,3}/gold.parquet               Pedia's placement of 4,500 of them (key: silver_id)

The project agreed to use Pedia's placement as gold here (Labeled/README.md). Harry's human labels are scored next to it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pyarrow.parquet as pq

from taxo.gold import GoldRow

DRIVE_DIR = Path(os.environ.get("TAXO_DRIVE_DIR", r"G:\My Drive\Hackathon-Kavak-OpenAI-Primero\DATA\Listings"))
SUBSETS = (1, 2, 3)
RAW_COLS = ["source_record_key", "listing_name", "brand_name", "manufacturer_name", "source_id", "listing_url"]
GOLD_COLS = ["silver_id", "pedia_brand_key", "pedia_brand", "pedia_path_json", "pedia_placement_level"]


def listings() -> list[dict]:
    out = []
    for k in SUBSETS:
        for r in pq.read_table(DRIVE_DIR / "RAW" / "fragrance" / f"subset-{k}" / "fragrance_listings.parquet",
                               columns=RAW_COLS).to_pylist():
            out.append({"id": str(r["source_record_key"]), "title": r["listing_name"] or "", "subset": k,
                        "brand_name": r["brand_name"], "manufacturer_name": r["manufacturer_name"],
                        "source": r["source_id"] or "", "url": r["listing_url"]})
    return out


def pedia_gold() -> tuple[list[GoldRow], dict[str, str]]:
    """(gold rows, brand key -> display name). A row's id is "pedia:<silver_id>"; its path comes from pedia_path_json."""
    rows, names = [], {}
    for k in SUBSETS:
        for r in pq.read_table(DRIVE_DIR / "Labeled" / "fragrance" / f"subset-{k}" / "gold.parquet",
                               columns=GOLD_COLS).to_pylist():
            path = [seg[0] for seg in json.loads(r["pedia_path_json"] or "[]")]
            if not path or not r["pedia_brand_key"]:
                continue
            names.setdefault(r["pedia_brand_key"], r["pedia_brand"] or path[0])
            rows.append(GoldRow(id=f"pedia:{r['silver_id']}", title="", brand=r["pedia_brand_key"], expected_path=path,
                                origin=f"pedia-drive/subset-{k}",
                                extra={"listing": str(r["silver_id"]), "level": r["pedia_placement_level"]}))
    return rows, names
