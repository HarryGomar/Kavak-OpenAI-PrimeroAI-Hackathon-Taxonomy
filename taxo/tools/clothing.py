"""Conservative garment evidence and candidate checks. Source screens are not gold labels."""
from __future__ import annotations

import re

RANK = re.compile(r"#[\d,]+\s+in\s+(.+?)(?=\s*\(|\s*#|$)")
GARMENT = r"\b(?:tshirts?|undershirts?|shirts?|tees?|tops?|polos?|cardigans?|shrugs?|scrubs?|sweatpants|sweatshorts|tanks?|camis|dresses|dress|pants?|trousers|jeans|shorts|skirts?|skorts?|bras?|bralettes?|panties|underwear|boxers?|briefs|socks?|hosiery|tights|leggings|swimwear|swimsuits?|bikinis?|tankinis?|swim trunks|cover ups?|sweaters?|sweatshirts?|hoodies?|jackets?|coats?|parkas?|vests?|blouses?|tunics?|bodysuits?|rompers?|jumpsuits?|leotards?|pajamas?|pyjamas?|nightgowns?|robes?|suits?|sweatsuits?|tracksuits?|overalls?|coveralls?|sleepwear|pullovers?)\b"
ACCESSORY = r"\b(?:sockless|flat\s*socks|shoe liners?|shoe inserts?|bra liners?|fake collars?|false collars?|detachable collars?|nipple covers?|body tape|breast lift tape|breast forms?|prosthetic|belts?|handbags?|backpacks?|necklaces?|bracelets?|earrings?|hair clips?|scarves|scarfs|hats?|caps|gloves?)\b"
FOOTWEAR = r"\b(?:shoes?|sneakers?|sandals?|boots?|slippers?|loafers?|mules?|clogs?|flip.flops?)\b"


def scope(row: dict) -> dict:
    title = row.get("title") or row.get("listing_name") or ""
    ranks = row.get("best_seller_ranks") or [row.get("amazon_category_rank_text") or ""]
    labels = [m.group(1).strip() for rank in ranks for m in RANK.finditer(rank)]
    garment = bool(re.search(GARMENT, title, re.I))
    if re.search(r"\b(?:doll|dolls|pet|dog|cat)\s+(?:clothes|clothing|dress|shirt|costume)\b", title, re.I):
        decision, reason = "reject", "nonhuman_garment"
    elif re.search(ACCESSORY, title, re.I) and not garment:
        decision, reason = "reject", "separate_accessory"
    elif re.search(r"\b(?:sockless|flat\s*socks|shoe inserts?|shoe liners?|bra liners?|detachable collars?|nipple covers?|body tape|breast lift tape|breast forms?|prosthetic)\b", title, re.I):
        decision, reason = "reject", "non_garment_body_or_accessory_product"
    elif re.search(FOOTWEAR, title, re.I) and (not garment or re.search(r"\bdress\s+(?:shoes|boots)\b", title, re.I)):
        decision, reason = "reject", "footwear_outside_garments"
    elif not garment or not any(re.search(GARMENT, label, re.I) for label in labels):
        decision, reason = "hold", "garment_title_and_specific_rank_required"
    else:
        decision, reason = "accept", "garment_title_and_rank_no_detected_conflict"
    return {"decision": decision, "reason": reason, "rank_labels": labels, "basis": "machine_source_screen_v1"}


def quality(row: dict) -> list[str]:
    text = " ".join(str(row.get(k) or "") for k in ("title", "listing_name", "description_text", "description", "aplus_content"))
    issues = []
    if re.search(r"The video showcases|Video Player is loading|Captions off|This is a modal window", text, re.I):
        issues.append("video_ui_in_source_text")
    if "\ufffd" in text:
        issues.append("source_encoding_replacement_character")
    return issues


def style_codes(text: str) -> set[str]:
    # Only explicit style/model markers: bare sizes and ages are never guessed to be codes.
    return {m.group(1).casefold() for m in re.finditer(r"\b(?:style|model)\s*(?:no\.?|number|#)?\s*[:#]?\s*([a-z]*\d+[a-z0-9-]*)\b", text, re.I)}


def clothing_style_conflict(listing, node, tax, **params):
    a, b = style_codes(listing.title), style_codes(node.name)
    if a and b and a.isdisjoint(b):
        return f"explicit style identifiers conflict: {sorted(a)} vs {sorted(b)}"


def _types(text):
    groups = {"shirt": r"\b(?:t.shirts?|shirts?|tees?)\b", "dress": r"\bdress(?:es)?\b",
              "trouser": r"\b(?:pants|jeans|trousers)\b", "shorts": r"\bshorts\b"}
    return {k for k, p in groups.items() if re.search(p, text, re.I)}


def clothing_type_conflict(listing, node, tax, **params):
    # Audience alone is not product identity. Any additional name/code stays eligible.
    audience = {"woman", "women", "womens", "man", "men", "mens", "boy", "boys", "girl", "girls",
                "kid", "kids", "child", "children", "baby", "babies", "toddler", "toddlers",
                "adult", "adults", "unisex"}
    words = set(re.findall(r"[a-z0-9]+", node.name.casefold().replace("'", "").replace("\u2019", "")))
    if words & audience and words <= audience | {"for", "and"}:
        return "audience-only candidate lacks garment or product identity"
    a, b = _types(listing.title), _types(node.name)
    if len(a) == len(b) == 1 and a.isdisjoint(b):
        return f"garment types conflict: {sorted(a)} vs {sorted(b)}"


def _composition(text):
    if re.search(r"\b(?:multi.?pack|\d+\s*pack|pack\s+of\s+\d+)\b", text, re.I):
        return "multipack"
    if re.search(r"\b(?:\d+\s*piece|matching|coordinated|lounge)\s+(?:\w+\s+)?sets?\b", text, re.I):
        return "coordinated_set"
    return None


def clothing_set_conflict(listing, node, tax, **params):
    a, b = _composition(listing.title), _composition(node.name)
    if a and b and a != b:
        return f"composition conflict: {a} vs {b}"


CHECKS = {"clothing_style_conflict": (clothing_style_conflict, "veto"),
          "clothing_type_conflict": (clothing_type_conflict, "abstain"),
          "clothing_set_conflict": (clothing_set_conflict, "abstain")}
