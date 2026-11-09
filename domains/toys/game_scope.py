"""Conservative source-evidence screen; not a taxonomy or a learned/gold label."""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass

VERSION = "toys-game-subtypes-v1"
RANK = re.compile(r"#[\d,]+\s+in\s+(.+?)(?=\s*\(|\s*#|$)", re.I)


def hit(pattern: str, text: str):
    return re.search(pattern, text, re.I)


def fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()


def evidence_row(row: dict) -> dict:
    return {**row, **row.get("games_source_row", {})}


def category_labels(row: dict) -> list[str]:
    ranks = row.get("best_seller_ranks") or [row.get("amazon_category_rank_text") or ""]
    labels = [m.group(1).strip() for rank in ranks for m in RANK.finditer(rank)]
    cats = row.get("categories")
    if cats is None and row.get("categories_json"):
        cats = json.loads(row["categories_json"])
    # Silver categories are source_label objects, not taxonomy paths.
    labels += [c if isinstance(c, str) else c.get("name") or c.get("label") or c.get("value") or ""
               for c in cats or []]
    return list(dict.fromkeys(x for x in labels if x))


@dataclass(frozen=True)
class ScopeDecision:
    status: str
    subtype: str | None
    reason: str
    evidence: tuple[str, ...] = ()
    version: str = VERSION

    def as_dict(self) -> dict:
        return asdict(self)


def decide_scope(row: dict) -> ScopeDecision:
    r = evidence_row(row)
    title = r.get("title") or r.get("listing_name") or ""
    labels = category_labels(r)
    cats = "\n".join(labels)
    description = r.get("description") or r.get("description_text") or r.get("aplus_content") or ""

    def decision(status, reason, subtype=None, evidence=()):
        return ScopeDecision(status, subtype, reason, tuple(evidence))

    if not title.strip():
        return decision("hold", "missing_title")
    if r.get("scrape_status") not in (None, "ok"):
        return decision("hold", "source_capture_not_ok")
    if hit(r"video dvd|home entertainment", cats) and hit(r"\bfilm|movie|director|getaway driver", description):
        return decision("exclude", "film_conflicts_with_game_rank")
    if hit(r"\b(?:for dogs|for cats|dog pool|catnip)\b", title):
        return decision("hold" if hit(r"for kids|kids and dogs", title) else "exclude", "pet_or_shared_use")
    if hit(r"\b(?:ipad|apple pencil)\b", title) and hit(r"\b(?:stylus|pencil)\b", title) and not hit(r"nintendo|playstation|xbox|steam deck", title):
        return decision("exclude", "generic_tablet_accessory_despite_rank")
    if hit(r"\b(?:party plates|party cups|napkins|tablecloths?|tableware|cake toppers?|cupcake toppers?|party balloons|party banners)\b", title):
        return decision("exclude", "nonplay_partyware")

    # Clear toys cannot enter through licensed titles, broad departments or DLC codes.
    toy_title = hit(r"\b(?:action figures?|collector figure|collectible figures?|minifigures?|plush|stuffed animals?|building sets?|dolls?|dollhouse|pretend play|fidget|sensory squeeze|rc servo|rc cars?|remote.controlled)\b", title)
    toy_cat = hit(r"(?:action figures|toy.*building|building toys|doll|plush|stuffed animals|fidget|squeeze toys|hobby rc|rc servos|pretend play|miniature novelty toys|toy figure|play figure|early development|sorting & stacking toys|slime & putty)", cats)
    puzzle_title = hit(r"\bpuzzles?\b", title)
    if (toy_title or toy_cat) and puzzle_title:
        return decision("hold", "puzzle_toy_or_decor_conflict")
    if toy_title or toy_cat:
        return decision("exclude", "toys_domain", evidence=[x for x in labels if hit(r"toy|figure|doll|plush|fidget|rc", x)])
    if hit(r"\b(?:subscription|membership|game pass)\b", title) and hit(r"xbox|playstation|nintendo|pc gaming", title):
        return decision("hold", "subscription_entitlement_not_full_game")
    if hit(r"\b(?:dot markers?|art markers?|coloring supplies)\b", title) and hit(r"bingo daubers", cats):
        return decision("hold", "art_supply_or_bingo_accessory_ambiguous")
    if hit(r"\b(?:miniatures?|minatures|warband|combat patrol|starter set)\b", title) and hit(r"game pieces", cats):
        return decision("hold", "miniature_set_or_complete_tabletop_game_ambiguous")

    kinds: dict[str, list[str]] = {}

    def support(kind, pattern, text, label):
        m = hit(pattern, text)
        if m:
            kinds.setdefault(kind, []).append(f"{label}:{m.group(0)}")

    support("puzzle", r"\b(?:jigsaw|pegged|3-d|assembly & disentanglement|brain teaser).*puzzles?\b", cats, "category")
    support("puzzle", r"\bpuzzles?\b", title, "title")
    support("domino_game", r"\bdomino(?:es|s)?\b|mahjong|mah jong", title, "title")
    support("domino_game", r"domino & tile games", cats, "category")
    support("dice_game", r"\b(?:dice games?|standard game dice|dice set)\b", title, "title")
    support("dice_game", r"\b(?:dice games|standard game dice)\b", cats, "category")
    support("card_game", r"\b(?:card game|playing cards|trading card game|commander deck|booster pack|poker set)\b", title, "title")
    support("card_game", r"dedicated deck card games|standard playing card decks|collectible card game", cats, "category")
    support("board_game", r"\b(?:board games?|chess|checkers|backgammon|bingo game|juego de mesa|juegos de mesa)\b", title, "title")
    support("board_game", r"board games|travel games|stacking games|bingo sets", cats, "category")

    tabletop_accessory = hit(r"puzzle (?:mat|board(?! game)|table|glue|storage|roll)|(?:card|deck) sleeves?|deck box|dice (?:tray|tower|bag)|mahjong racks?|domino racks?", title)
    tabletop_accessory = tabletop_accessory or hit(r"puzzle accessories|game mats & boards|game pieces|game accessories|collectible trading card cases|bingo (?:cards|daubers)", cats)
    if tabletop_accessory:
        kinds = {"tabletop_accessory": ["title_or_specific_category:tabletop_accessory"]}

    platform = hit(r"\b(?:playstation|ps[1-5]|xbox|nintendo|steam deck|atari|sega|wii|gamecube|game ?boy)\b", title)
    game_marketing = hit(r"\b(?:gaming|gamer|video games?|plug.?[ &]+play)\b", title)
    accessory = hit(r"\b(?:controllers?|gamepads?|joysticks?|keyboards?|keypads?|mice|mouse|headsets?|headphones?|racing wheel|hotas|flight stick|faceplates?|covers?|cases?|thumb grips?|adapters?|power supply|chargers?|charging|batteries|battery|stylus|flash cart|screen protectors?|grips?|stand|dock|cable|sensor bar)\b", title)
    # A specific gaming category must describe the actual accessory; a generic
    # iPad stylus with a Nintendo rank was explicitly excluded above.
    accessory_cat = hit(r"(?:pc|mac) gam(?:e|ing) (?:keyboards|mice|headsets|flight controls|racing wheels|controllers|gamepads)|(?:playstation|nintendo|xbox|wii|gamecube|atari|sega).*(?:controllers|accessories|adapters|cases|headsets|batteries|faceplates|charging|grips|cables)", cats)
    own_title = re.split(r"\b(?:for|compatible with)\b", title, maxsplit=1, flags=re.I)[0]
    hardware = hit(r"\b(?:console|microconsole|handheld game|gamestation)\b(?!\s*(?:cover|stand|case|skin|vertical|cool|charg|accessor))", own_title)
    video_kind = None
    if hit(r"\b(?:gift card|currency|v.bucks|robux|wallet funds)\b", title) and (platform or hit(r"store currency cards", cats)):
        video_kind = "video_game_currency"
    elif hit(r"\b(?:dlc|downloadable content|season pass|expansion pass)\b", title) and (platform or hit(r"downloadable content|video games", cats)):
        video_kind = "video_game_dlc"
    elif hardware and (platform or game_marketing or hit(r"consoles|plug & play video games|microconsole|handheld games", cats)):
        video_kind = "video_game_hardware"
    elif accessory and (platform or accessory_cat or hit(r"\bgaming (?:keyboards?|keypads?|mouse|mice|headsets?|headphones?|controllers?|gamepads?|joysticks?)\b", title)):
        video_kind = "video_game_accessory"
    if video_kind is None and any(hit(r"^(?:PlayStation [1-5]|Nintendo (?:Switch(?: 2)?|3DS & 2DS|DS|64)|Xbox (?:One|360|Series X & S)|Atari 2600|PC|Wii(?: U)?|Sega .+) Games$", c) for c in labels):
        video_kind = "video_game_software"
    if video_kind:
        kinds[video_kind] = [f"title:{video_kind}"] + [f"category:{c}" for c in labels if c not in ("Video Games", "Toys & Games", "Toys")]
    if len(kinds) > 1:
        return decision("hold", "conflicting_game_kinds", evidence=sorted(kinds))
    if kinds:
        kind, evidence = next(iter(kinds.items()))
        return decision("accept", "specific_game_identity", kind, evidence)
    # Descriptions can support thin titles only with independent specific ranks.
    if hit(r"\bboard game\b", description) and any(c.lower() == "board games" for c in labels):
        return decision("accept", "description_and_specific_category", "board_game", ["description:board game", "category:Board Games"])
    return decision("hold", "no_supported_game_identity")


def identity_features(row: dict, subtype: str | None) -> dict:
    """Evidence features only. Unknown is explicit; titles are never rewritten."""
    r = evidence_row(row)
    title = r.get("title") or r.get("listing_name") or ""
    text = fold(title)
    features: dict = {"title_key": " ".join(re.findall(r"[a-z0-9]+", text))}
    patterns = {
        "ps5": r"\b(?:ps5|playstation 5)\b", "ps4": r"\b(?:ps4|playstation 4)\b",
        "ps3": r"\b(?:ps3|playstation 3)\b", "ps2": r"\b(?:ps2|playstation 2)\b",
        "switch_2": r"\bnintendo switch 2\b|\bswitch 2\b",
        "switch": r"\b(?:nintendo )?switch\b(?! 2)", "xbox_series_x_s": r"\bxbox series [xs]\b",
        "xbox_one": r"\bxbox one\b", "xbox_360": r"\bxbox 360\b",
        "pc": r"\bpc\b", "steam_deck": r"\bsteam deck\b", "nintendo_64": r"\b(?:n64|nintendo 64)\b",
        "nintendo_3ds": r"\b(?:nintendo )?3ds\b", "wii_u": r"\bwii u\b", "wii": r"\bwii\b(?! u)",
    }
    platforms = [k for k, pattern in patterns.items() if hit(pattern, title)] if (subtype or "").startswith("video_game_") else []
    # Compatibility targets are not the accessory's manufacturer or identity.
    features["compatible_platforms" if subtype == "video_game_accessory" else "platforms"] = platforms
    features["editions"] = re.findall(r"\b(?:\d+(?:st|nd|rd|th)|standard|deluxe|ultimate|complete|definitive|collector'?s?|bedrock|day 1|anniversary|special|limited) edition\b", text)
    features["languages"] = [v for v in ("english", "japanese", "spanish", "french", "german", "italian") if hit(rf"\b{v}\b", text)]
    if "espanol" in text:
        features["languages"].append("spanish")
    features["distribution"] = "unknown"
    if subtype in ("video_game_software", "video_game_dlc", "video_game_currency"):
        digital = bool(hit(r"digital code|download(?:able)?|dlc", text))
        physical = bool(hit(r"\b(?:disc|disk|cartridge|physical)\b", text))
        features["distribution"] = "conflict" if digital and physical else "digital" if digital else "physical" if physical else "unknown"
    features["product_role"] = "unknown"
    if subtype in ("board_game", "card_game", "dice_game", "domino_game"):
        evidence_text = fold(title + " " + (r.get("description") or r.get("description_text") or ""))
        features["requires_base_game"] = True if hit(r"requires? (?:the |a )?.{0,40}base game", evidence_text) else "unknown"
        features["standalone_play"] = True if hit(r"stand.?alone|play.{0,25}(?:by itself|on its own)", evidence_text) else "unknown"
        if hit(r"\+ expansion|base game.*expansion|game and.*expansion", text):
            features["product_role"] = "base_plus_expansion_bundle"
        elif hit(r"\bexpansion|\badd.on|requires.*base game", text):
            features["product_role"] = "expansion"
        elif hit(r"stand.?alone|base game", text):
            features["product_role"] = "base_or_standalone"
    if subtype == "video_game_software" and hit(r"collector|bundle", text):
        features["product_role"] = "collector_or_bundle"
    if subtype == "puzzle":
        features["puzzle_piece_counts"] = sorted({int(n.replace(",", "")) for n in re.findall(r"\b(\d[\d,]*)[ -]*(?:piece|pieces)\b", text)})
    return features
