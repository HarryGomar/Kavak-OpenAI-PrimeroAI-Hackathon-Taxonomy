"""Electronics: historical US retail listings (DeepMatcher Amazon-Google, Walmart-Amazon, Abt-Buy), placed into a
brand > product > variant tree that the pipeline builds from the listings themselves (no official catalogue)."""
from __future__ import annotations

import csv
import json
from typing import Iterator

from taxo.core import config
from taxo.core.config import RUNS_DIR
from taxo.core.io import link_children
from taxo.core.schemas import Listing, Node

DOMAIN = "electronics"
FIELDS = ("dataset", "source_table", "source_id", "manufacturer_model", "source_category", "description", "price",
          "price_raw")


def listings_path():
    return config.data_dir() / DOMAIN / "listings" / "products.csv"


def load_listings(limit: int | None = None) -> Iterator[Listing]:
    with listings_path().open(encoding="utf-8-sig", newline="") as s:
        for i, r in enumerate(csv.DictReader(s)):
            if limit is not None and i >= limit:
                break
            yield Listing(id=r["record_key"], domain=DOMAIN, title=r["title"], source=r["merchant"],
                          brand=r["brand_manufacturer"] or None,
                          fields={k: r[k] for k in FIELDS if r.get(k)})


def load_taxonomy() -> list[Node]:
    """The tree the last pipeline run built (runs/electronics/nodes.jsonl), as Nodes; empty before the first run."""
    path = RUNS_DIR / DOMAIN / "nodes.jsonl"
    if not path.exists():
        return []
    nodes = []
    for line in path.read_text(encoding="utf-8").splitlines():
        n = json.loads(line)
        if n["level"] in ("brand", "type", "product", "variant"):
            nodes.append(Node(id=n["id"], domain=DOMAIN, name=n["name"], parent_id=n.get("parent_id"), level=n["level"],
                              path=n["path"], fields={k: n[k] for k in ("status", "category") if n.get(k)}))
    return link_children(nodes)
