"""Fragrance validator tools (taxo/roles/validator.py loads the TOOLS list). A tool reads the listing, the taxonomy or
the web; it never reads labels or the pipeline's answer for the listing being validated."""
from __future__ import annotations

from agents import RunContextWrapper, function_tool

from taxo.roles.validator import ValidateContext


@function_tool
def brand_products(ctx: RunContextWrapper[ValidateContext], brand: str, limit: int = 40) -> list[str]:
    """The node names this brand already has in the product tree (lines and products, `Line > Product`), most listed
    first. Some are junk words; reuse a name only when it is the same product the listing names."""
    menus = ctx.context.menus
    key = next((b for b in menus if b.lower() == brand.lower().strip()), None)
    return (menus.get(key) or [])[:limit]


TOOLS = [brand_products]
