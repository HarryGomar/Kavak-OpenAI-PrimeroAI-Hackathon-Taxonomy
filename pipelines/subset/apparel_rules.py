"""Conservative garment/footwear rules over source-stated Amazon rank labels.

Garments include socks, underwear, swimwear and sleepwear. Hats, gloves, scarves,
belts, jewelry, bags, beauty products and garment accessories are not garments.
Unclear evidence is held rather than admitted through the broad department.
"""
import re
from content_audit.quality import check as quality_check

RANK = re.compile(r"#[\d,]+\s+in\s+(.+?)(?=\s*\(|\s*#|$)")
GARMENT = re.compile(
    r"\b(?:dresses|t[ -]?shirts|shirts|tops|tanks|camis|camisoles|bras|bralettes|socks|"
    r"sweaters|sweatshirts|hoodies|shorts|pants|trousers|leggings|jeans|skirts|skorts|"
    r"jumpsuits|rompers|overalls|jackets|coats|vests|underwear|briefs|boxers|panties|"
    r"bikini sets|bikini tops|swimwear|swimsuits|swim trunks|rash guards|pajamas|"
    r"sleepwear|nightgowns|nightshirts|robes|bathrobes|tights|pantyhose|hosiery|"
    r"bodysuits|leotards|unitards|tracksuits|suits|sweatsuits|sweatpants|blouses|"
    r"tunics|cardigans|polos|pullovers|uniforms|undershirts|henleys|scrub sets)\b", re.I)
FOOTWEAR = re.compile(
    r"\b(?:shoes|boots|sneakers|sandals|slippers|flats|pumps|loafers|oxfords|clogs|"
    r"espadrilles|moccasins|mules|flip[ -]?flops|slides|cleats)\b", re.I)
GARMENT_SINGULAR_TITLE = re.compile(
    r"\b(?:dress|shirt|sock|bra|jacket|coat|skirt|blouse|robe|bodysuit|swimsuit|"
    r"sweater|sweatshirt|hoodie|romper|jumpsuit|vest|leotard|unitard|cardigan|"
    r"pullover|polo|tunic|undershirt|nightgown|nightshirt|tank|camisole)\b", re.I)
ACCESSORY_RANK = re.compile(
    r"\b(?:accessories|jewelry|jewellery|necklaces|earrings|bracelets|rings|watches|"
    r"handbags|purses|wallets|backpacks|bags|luggage|sunglasses|eyeglasses|glasses|"
    r"hats|caps|headbands|headwear|scarves|scarfs|belts|gloves|mittens|ties|bow ties|"
    r"masks|wigs|hair|makeup|cosmetics|nail|nails|shoe care|insoles|inserts|laces|"
    r"shoelaces|charms|extenders|straps|pads|padding|forms|sewing|patterns|patches|"
    r"hangers|storage|costume weapons|adhesive|pet|dog|cat|doll)\b", re.I)
NON_PRODUCT = re.compile(
    r"\b(?:sewing patterns?|crochet patterns?|knitting patterns?|iron[ -]on|patches|"
    r"shoe charms?|shoe clips?|shoelaces|insoles|heel cups?|shoe trees?|shoe bags?|"
    r"bra extenders?|bra straps?|bra inserts?|bra liners?|breast forms?|nipple covers?|"
    r"shoe liners?|shoe inserts?|sockless|flat\s*socks|body harness|modesty panels?|"
    r"cleavage covers?|breast lift tape|prosthetic|prosthesis|vagina pants|"
    r"(?:fake|false|detachable) collars?|dickey|dickie collars?|"
    r"adhesive.{0,40}\bbra|sticky bras?|stick[ -]?on bras?|"
    r"fashion tape|body tape|wig caps?|garment bags?|laundry bags?|hangers?|"
    r"doll clothes|doll clothing|for dolls|dog clothes|dog clothing|pet costumes?|"
    r"makeup|cosmetics|mascara|eyeliner|lipstick|lip gloss|foundation brush|"
    r"costume masks?|face masks?)\b", re.I)


def labels(row):
    return [m.group(1).strip() for text in row["best_seller_ranks"] or [] for m in RANK.finditer(text)]


def decide(row):
    if row["scrape_status"] != "ok" or not all((row[k] or "").strip() for k in ("asin", "title", "analysis_text")):
        return None, "ineligible_capture", []
    ranks = labels(row)
    if "Clothing, Shoes & Jewelry" not in ranks:
        return None, "outside_department", []
    quality = quality_check(row)
    if quality:
        return None, quality[0], []
    if NON_PRODUCT.search(row["title"]):
        return None, "non_garment_or_accessory_title", []
    leaves = [label for label in ranks if label != "Clothing, Shoes & Jewelry"]
    garment = [label for label in leaves if GARMENT.search(label) and not ACCESSORY_RANK.search(label) and not FOOTWEAR.search(label)]
    footwear = [label for label in leaves if FOOTWEAR.search(label) and not ACCESSORY_RANK.search(label)]
    primary = (row["categories"] or [None])[0]
    if primary == "Apparel" and garment and not footwear:
        # Require positive title evidence as well as a specific rank category;
        # a brand/model-only name cannot qualify as clothes through a broad tag.
        if GARMENT.search(row["title"]) or GARMENT_SINGULAR_TITLE.search(row["title"]):
            return "clothing", "specific_garment_rank_and_title", garment
        return None, "garment_rank_without_clear_garment_title", garment
    if primary == "Shoes" and footwear and not garment:
        return "footwear", "specific_footwear_rank_and_primary_shoes", footwear
    return None, "ambiguous_or_non_garment_department_item", []
