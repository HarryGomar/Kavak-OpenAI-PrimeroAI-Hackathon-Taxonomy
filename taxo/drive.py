"""The hackathon's shared data on Drive (Hackathon-Kavak-OpenAI-Primero/DATA/Listings), read in place:

    RAW/<domain>/subset-{1,2,3}/<domain>_listings.parquet     5,000 listings each
    Labeled/<domain>/subset-{1,2,3}/gold.parquet               Pedia's placement of 4,500 of them (key: silver_id)

Fragrance joins on source_record_key, food on observation_key (Labeled/README.md). The project agreed to use Pedia's
placement as gold here. Harry's human labels (fragrance only) are scored next to it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pyarrow.parquet as pq

from taxo.gold import GoldRow

DRIVE_DIR = Path(os.environ.get("TAXO_DRIVE_DIR", r"G:\My Drive\Hackathon-Kavak-OpenAI-Primero\DATA\Listings"))
SUBSETS = (1, 2, 3)
KEY = {"fragrance": "source_record_key", "food": "observation_key"}
MAKER = {"fragrance": "manufacturer_name"}          # food has no maker column
VARIANT = {"food": "variant_name"}                  # the shop's own variant label (Shopify, Amazon)
GOLD_COLS = ["silver_id", "pedia_brand_key", "pedia_brand", "pedia_path_json", "pedia_placement_level"]


def listings(domain: str = "fragrance") -> list[dict]:
    key, maker = KEY[domain], MAKER.get(domain)
    var = VARIANT.get(domain)
    cols = [key, "listing_name", "brand_name", "source_id", "listing_url"] + ([maker] if maker else []) + ([var] if var else [])
    out = []
    for k in SUBSETS:
        for r in pq.read_table(DRIVE_DIR / "RAW" / domain / f"subset-{k}" / f"{domain}_listings.parquet",
                               columns=cols).to_pylist():
            out.append({"id": str(r[key]), "title": r["listing_name"] or "", "subset": k,
                        "brand_name": r["brand_name"], "manufacturer_name": r.get(maker) if maker else None,
                        "source": r["source_id"] or "", "url": r["listing_url"], "variant": r.get(var) if var else None})
    return out


def pedia_gold(domain: str = "fragrance") -> tuple[list[GoldRow], dict[str, str]]:
    """(gold rows, brand key -> display name). A row's id is "pedia:<silver_id>"; its path comes from pedia_path_json."""
    rows, names = [], {}
    for k in SUBSETS:
        for r in pq.read_table(DRIVE_DIR / "Labeled" / domain / f"subset-{k}" / "gold.parquet",
                               columns=GOLD_COLS).to_pylist():
            path = [seg[0] for seg in json.loads(r["pedia_path_json"] or "[]")]
            if not path or not r["pedia_brand_key"]:
                continue
            names.setdefault(r["pedia_brand_key"], r["pedia_brand"] or path[0])
            rows.append(GoldRow(id=f"pedia:{r['silver_id']}", title="", brand=r["pedia_brand_key"], expected_path=path,
                                origin=f"pedia-drive/subset-{k}",
                                extra={"listing": str(r["silver_id"]), "level": r["pedia_placement_level"]}))
    return rows, names
