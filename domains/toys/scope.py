"""Conservative, deterministic source screen; decisions are machine evidence, not gold."""
from __future__ import annotations

import re

VERSION = "toys-source-scope-v1"
RANK = re.compile(r"#[\d,]+\s+in\s+(.+?)(?=\s*\(|\s*#|$)")


def hit(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def rank_labels(row: dict) -> list[str]:
    ranks = row.get("best_seller_ranks") or [row.get("amazon_category_rank_text") or ""]
    return list(dict.fromkeys(m.group(1).strip() for r in ranks for m in RANK.finditer(r)))


# Specific play-object evidence. Department names and generic "game" are omitted.
TOY_TITLE = (
    r"\b(?:(?:action|battle|collector) figures?|toy.*\bfigures?|figurines?|plush|stuffed animals?|teddy bears?|dolls?|dollhouses?|"
    r"building (?:sets?|toys?|blocks?)|magnetic tiles?|pretend (?:play|phones?)|playsets?|play sets?|"
    r"sensory (?:play|toys?)|fidget|squeeze toys?|squishy toys?|slime|putty|"
    r"(?:remote control|radio control|RC) (?:cars?|trucks?|boats?|helicopters?|robots?|vehicles?)|"
    r"toy (?:cars?|trucks?|trains?|vehicles?|robots?|kitchens?|foods?|medical|swords?|hammers?|clay)|"
    r"foam blasters?|bubble (?:makers?|wands?|guns?)|beach balls?|prank|gag toy|"
    r"miniature.*\bdoll|play kitchen|science kits?|craft kits?|activity kits?)\b"
)
TOY_RANK = (
    r"\b(?:toys?|action figures|dolls?|dollhouse|plush|stuffed animals|building sets|"
    r"playsets|play sets|play.*figures|play (?:cars|trucks|trains|buses|boats)|"
    r"hobby RC|RC (?:servos|vehicle|battery|radio|aircraft)|remote.*controlled|"
    r"fidget|slime|putty|bubble makers|beach balls|sorting & stacking|rattles|puppets|"
    r"activity cubes|sand & water tables|science kits|craft kits|art clay & dough)\b"
)
GAME_RANK = (
    r"\b(?:board games|card games|card game|playing card|trading card|domino|dice|"
    r"puzzles?|poker|bingo|casino|game (?:pieces|mats|accessories|collections)|"
    r"games & accessories|stacking games|travel games|floor games|bean bag game|"
    r"collectible.*card|party games|electronic dance mats|"
    r"playstation|xbox|nintendo|gamecube|game boy|atari|wii|sony PSP|"
    r"PC (?:games?|gaming|gamepads?|accessories|virtual reality)|Mac (?:games?|gaming|gamepads?)|video games?|virtual reality|"
    r"GEM Box|legacy (?:systems|game)|handheld games)\b"
)
GAME_TITLE = (
    r"\b(?:board game|card game|dice|domino(?:es|s)?|jigsaw|puzzles?|poker|bingo|"
    r"trading cards?|booster (?:packs?|boxes?)|TCG|CCG|"
    r"(?:playstation|PS[345]|xbox|nintendo switch|steam deck)\b.*"
    r"(?:games?|controllers?|headsets?|consoles?|cases?|chargers?|cables?|adapters?)|"
    r"(?:controllers?|gamepads?|joy.cons?|gaming keyboards?|gaming mice|gaming mouse)|chess(?:men)?\b)"
)
ACCESSORY = r"\b(?:replacement|accessor(?:y|ies)|compatible|display (?:stand|holder)|axles?|servos?|chargers?|batter(?:y|ies)|spare parts?)\b"


def _toy_object_scope(row: dict) -> dict:
    """Return include/exclude/hold with observable reasons; never assign taxonomy."""
    title = row.get("title") or row.get("listing_name") or ""
    description = row.get("description") or row.get("description_text") or ""
    labels = rank_labels(row)
    ranks = "; ".join(x for x in labels if x not in ("Toys & Games", "Video Games"))
    categories = row.get("categories") or []
    if not categories and row.get("categories_json"):
        import json
        categories = [r.get("label", "") for r in json.loads(row["categories_json"])]
    toy_title = hit(TOY_TITLE, title)
    toy_rank = hit(TOY_RANK, ranks)
    game_title = hit(GAME_TITLE, title)
    game_rank = hit(GAME_RANK, ranks)

    def result(decision, reason):
        return {"decision": decision, "reason": reason, "version": VERSION,
                "evidence": {"rank_labels": labels, "toy_title": toy_title,
                             "toy_rank": toy_rank, "game_title": game_title, "game_rank": game_rank}}

    if not title.strip():
        return result("hold", "missing_title")
    if row.get("scrape_status") not in (None, "ok"):
        return result("hold", "source_capture_not_ok")
    if "Clothing, Shoes & Jewelry" in labels and not hit(r"\bdoll", ranks):
        return result("hold" if toy_title else "exclude", "garment_footwear_or_jewelry_source")
    if categories and categories[0] in ("Video DVD", "Home Entertainment"):
        return result("exclude", "movie_or_home_entertainment_source")
    if hit(r"\b(?:for dogs|for cats|kids and dogs|kids and cats|dog pool|dog ball pit|catnip|dog toys?|cat toys?)\b", title):
        if hit(r"\b(?:kids|toddlers|children|baby)\b", title):
            return result("hold", "shared_human_pet_use")
        return result("exclude", "pet_only_goods")
    if hit(r"\b(?:ipad|apple pencil)\b", title) and hit(r"\b(?:pencil|stylus)\b", title):
        return result("exclude", "generic_tablet_stylus")
    if hit(r"\b(?:white noise|sound machine|nap mat|slumber bag|sleeping bag|beverage cooler|cooler float)\b", title):
        if not hit(r"\b(?:dolls?|prank|gag)\b", title):
            return result("exclude", "household_baby_or_pool_utility")
    if hit(r"\b(?:humanoid robot|professional|bait release|medical flashcards?|nursing|anatomy|comic book edition|savings challenge|piggy bank|tungsten cube)\b", title):
        return result("hold", "professional_educational_or_utility_use")
    if hit(r"\b(?:real.*(?:make.?up|cosmetic)|washable.*make.?up|wearable jewelry)\b", title):
        return result("hold", "real_cosmetics_or_wearable_goods")
    if hit(r"\b(?:hair clips?|clip.on earrings?|liquid latex|skin body paint|teacher survival kit)\b", title) and not hit(r"dolls?|pretend|making kit", title):
        return result("exclude", "grooming_or_nonplay_goods")
    if hit(r"\b(?:costumes?|costume (?:wigs|masks|hats)|robes|capes)\b", ranks) and not hit(r"dolls?|toy (?:sword|hammer)|foam blaster|pretend play|playset", title):
        return result("exclude", "costume_garment_or_accessory")
    if hit(r"\b(?:stickers?|decals?)\b", title):
        if not hit(r"sticki (?:rolls|mates)|sticker.*(?:activity|scene|reusable pad)|make.a.face|doll|RC vehicle|ride.on", title):
            if hit(r"vinyl|waterproof|water bottles?|laptops?|phone case|scrapbook|decals?|stick.on earring", title + " " + description):
                return result("exclude", "generic_decorative_stickers")
            return result("hold", "sticker_play_activity_not_established")
    party = r"\b(?:party.*(?:plates|napkins|cups|table|balloons|banners|decorations|supplies|favor bags)|cake toppers?|cupcake toppers?|tableware|tablecloths?|cutlery|backdrops?)\b"
    if hit(party, title + " " + ranks):
        clear_play = toy_title and toy_rank and not hit(party, ranks)
        explicit_nonplay = hit(r"party (?:plates|napkins|cups|tableware)|tablecloth|cutlery", title)
        if not clear_play or explicit_nonplay:
            if toy_title and not explicit_nonplay:
                return result("hold", "toy_and_party_decoration_conflict")
            return result("exclude", "nonplay_partyware_or_decoration")
    if hit(r"\b(?:school glue|adhesive dots|paper clips|greeting cards|photo sign|first day of school|stationery|coloring pens|crayons|colored pencils|diaries|notebooks|erasers|art paintbrushes)\b", title + " " + ranks) and not toy_title and not hit(r"\b(?:activity|craft|science) kit|pretend|toy", title):
        return result("hold", "generic_stationery_or_art_supply")
    if hit(r"\b(?:jewelry|play (?:bracelets|rings|necklaces|earrings)|money banks|flash cards|kids' electronics|kids' cameras|telescopes|microscopes)\b", ranks) and not hit(r"making kit|craft kit|fidget|sensory|pretend|toy", title):
        return result("hold", "play_or_utility_boundary_unclear")
    # Specific games evidence outranks broad toy evidence; conflicting play-object
    # titles are held unless the title explicitly describes a game/puzzle.
    if game_title:
        # A puzzle is owned by games even if sold as an educational wooden toy.
        return result("exclude", "games_owned_product_or_accessory")
    if game_rank:
        return result("hold" if toy_title else "exclude",
                      "toy_title_games_rank_conflict" if toy_title else "games_owned_specific_rank")
    if toy_title or toy_rank:
        reason = "toy_accessory_or_compatibility_evidence" if hit(ACCESSORY, title) else "human_play_product_evidence"
        return result("include", reason)
    return result("hold", "no_positive_specific_toy_evidence")


def scope_decision(row: dict) -> dict:
    """One toys domain, including tabletop, puzzle and video-game subtypes."""
    from .game_scope import decide_scope, identity_features
    toy = _toy_object_scope(row)
    game = decide_scope(row)
    if game.status == "accept":
        return {"decision": "include", "reason": game.reason, "version": "toys-unified-v1",
                "subtype": game.subtype, "identity": identity_features(row, game.subtype),
                "evidence": list(game.evidence)}
    if toy["decision"] == "include":
        return {**toy, "subtype": "toy", "identity": {}}
    if toy["reason"].startswith("games_owned"):
        return {**toy, "decision": "hold", "reason": "game_identity_needs_review"}
    return toy
