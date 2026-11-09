"""Cars: used-car listings from Kavak, Seminuevos, Mercado Libre, Autocosmos, Carshop (Mexico), placed into the
catalogue taxonomy make > model > year > version (Autocosmos + brand sites)."""
from __future__ import annotations

import re
from typing import Iterator

from taxo.core import config
from taxo.core.io import link_children, read_jsonl
from taxo.core.schemas import Listing, Node

DOMAIN = "cars"


def _slug(s) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")


def listing_id(r: dict) -> str:
    """Stable id: the source's own id; Kavak feed rows use stockId (their URL repeats across cars of one version);
    rows with neither (Kavak promo cards) use the URL plus their page position."""
    own = r.get("id") or r.get("stockId")
    if own:
        return f"{r['_source']}:{own}"
    return f"{r['_source']}:{r.get('url')}#p{r.get('page')}-{r.get('position_on_page', r.get('position'))}"


def load_listings(limit: int | None = None) -> Iterator[Listing]:
    for r in read_jsonl(config.data_dir() / DOMAIN / "listings.jsonl", limit):
        make = r.get("make") or r.get("brand") or r.get("slice_brand")
        parts = [make, r.get("model"), r.get("version"), r.get("year")]
        title = r.get("title") or " ".join(str(p) for p in parts if p)
        yield Listing(id=listing_id(r), domain=DOMAIN, title=title,
                      source=r["_source"], brand=make,
                      fields={k: r.get(k) for k in ("model", "version", "year", "km", "kilometers", "price_mxn",
                                                     "price", "url") if r.get(k) is not None})


def load_taxonomy() -> list[Node]:
    nodes: dict[str, Node] = {}

    def add(path, level):
        nid = "/".join(_slug(p) for p in path)
        if nid not in nodes:
            parent = "/".join(_slug(p) for p in path[:-1]) or None
            nodes[nid] = Node(id=nid, domain=DOMAIN, name=str(path[-1]), parent_id=parent, level=level,
                              path=[str(p) for p in path])
        return nodes[nid]

    for r in read_jsonl(config.data_dir() / DOMAIN / "taxonomy.jsonl"):
        if not (r.get("brand") and r.get("model")):
            continue
        add([r["brand"]], "make")
        add([r["brand"], r["model"]], "model")
        if r.get("year"):
            add([r["brand"], r["model"], r["year"]], "year")
            if r.get("version"):
                leaf = add([r["brand"], r["model"], r["year"], r["version"]], "version")
                leaf.fields.update({k: r.get(k) for k in ("msrp_mxn", "_source") if r.get(k) is not None})
    return link_children(list(nodes.values()))
