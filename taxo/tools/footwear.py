"""Small footwear source screen and unvalidated identity checks."""
import re

RANK = re.compile(r"#[\d,]+\s+in\s+(.+?)(?=\s*\(|\s*#|$)")
FOOT = r"\b(?:shoes?|sneakers?|boots?|sandals?|slippers?|clogs?|mules?|loafers?|pumps|oxfords?|cleats?|flats|flip.flops?)\b"
ACCESSORY = r"\b(?:insoles?|shoe inserts?|shoelaces?|shoe charms?|heel grips?|shoe trees?|shoe polish|shoe cleaner)\b"

def scope(row):
    title = row.get("title") or row.get("listing_name") or ""
    labels = [m.group(1).strip() for r in row.get("best_seller_ranks", []) for m in RANK.finditer(r)]
    specific = [s for s in labels if s != "Clothing, Shoes & Jewelry"]
    if not title.strip():
        decision, reason = "hold", "missing_title"
    elif re.search(ACCESSORY, title, re.I):
        decision, reason = "hold", "footwear_or_standalone_accessory_needs_review"
    elif re.search(r"\b(?:doll|pet|dog|cat)\s+(?:shoes?|boots?|slippers?)\b", title, re.I):
        decision, reason = "reject", "nonhuman_footwear"
    elif any(re.search(FOOT, label, re.I) for label in specific):
        decision, reason = "accept", "specific_footwear_source_category"
    else:
        decision, reason = "hold", "specific_footwear_evidence_missing"
    return {"decision": decision, "reason": reason, "rank_labels": labels, "basis": "source_screen_proposal_v1"}

def quality(row):
    text = " ".join(str(row.get(k) or "") for k in ("title", "description", "description_text", "aplus_content"))
    return ["video_ui_in_source_text"] if re.search(r"The video showcases|Video Player is loading|This is a modal window", text, re.I) else []

def model_codes(text):
    return {m.group(1).casefold() for m in re.finditer(r"\b(?:style|model)\s*(?:no\.?|number|#)?\s*[:#]?\s*([a-z]*\d+[a-z0-9-]*)\b", text, re.I)}

def footwear_model_conflict(listing, node, tax, **params):
    a, b = model_codes(listing.title), model_codes(node.name)
    if a and b and a.isdisjoint(b):
        return "Explicit footwear style/model codes conflict"

def footwear_accessory_conflict(listing, node, tax, **params):
    if re.search(ACCESSORY, listing.title, re.I) and node.fields.get("offering_kind") == "complete_footwear":
        return "Standalone accessory evidence needs review before complete-footwear placement"

CHECKS = {"footwear_model_conflict": (footwear_model_conflict, "abstain"),
          "footwear_accessory_conflict": (footwear_accessory_conflict, "abstain")}
