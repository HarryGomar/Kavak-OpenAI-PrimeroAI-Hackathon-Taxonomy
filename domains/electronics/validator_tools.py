"""Electronics validator tools (taxo/roles/validator.py loads TOOLS). A tool reads the listing, the product tree or
the brand list; it never reads labels or the pipeline's answer for the listing being validated."""
from __future__ import annotations

import csv
from functools import lru_cache

from agents import RunContextWrapper, function_tool

from taxo.core import config
from taxo.roles.validator import ValidateContext


@lru_cache(maxsize=1)
def _rows() -> dict:
    with (config.data_dir() / "electronics" / "listings" / "products.csv").open(encoding="utf-8-sig", newline="") as s:
        return {r["record_key"]: r for r in csv.DictReader(s)}


def brand_names() -> dict[str, str]:
    """Brand key -> display name, from the listings' own brand field (used by similar_brands)."""
    out = {}
    for r in _rows().values():
        b = " ".join((r.get("brand_manufacturer") or "").casefold().split())
        if b:
            out.setdefault(b, b)
    return out


@function_tool
def listing_fields(ctx: RunContextWrapper[ValidateContext]) -> dict:
    """The listing's own structured fields: brand field, model field (often the manufacturer part number), source
    category and description. Evidence like the title; not an answer."""
    r = _rows().get(ctx.context.listing_id or "", {})
    return {k: r.get(k, "") for k in ("brand_manufacturer", "manufacturer_model", "source_category", "description")}


@function_tool
def brand_products(ctx: RunContextWrapper[ValidateContext], brand: str, limit: int = 40) -> list[str]:
    """Products this brand already has in the tree (`Product type > model`), most listed first. Reuse one only when it
    is the same part number the listing names."""
    menus = ctx.context.menus
    key = next((b for b in menus if b.lower() == brand.lower().strip()), None)
    return (menus.get(key) or [])[:limit]


TOOLS = [listing_fields, brand_products]
