"""Independent actual-product content screening for the three new RAW domains.

Input is a merged raw/source row. Rules inspect titles, source categories,
descriptions and specific rank labels; a root department is not sufficient.
Reject = clear scope conflict. Hold = evidence ambiguous or too weak.
"""
import re

RANK = re.compile(r'#[\d,]+\s+in\s+(.+?)(?=\s*\(|\s*#|$)')

def hit(pattern, text):
    return re.search(pattern, text or '', re.I)

def decide(domain, row):
    title = row.get('title') or row.get('listing_name') or ''
    description = row.get('description') or row.get('description_text') or ''
    aplus = row.get('aplus_content') or ''
    text = title + '\n' + description + '\n' + aplus
    ranks = row.get('best_seller_ranks') or [row.get('amazon_category_rank_text') or '']
    labels = [m.group(1).strip() for r in ranks for m in RANK.finditer(r)]
    specific = [x for x in labels if x not in ['Video Games', 'Toys & Games', 'Clothing, Shoes & Jewelry']]
    categories = row.get('categories') or []
    evidence = [title, '; '.join(specific)]
    if domain == 'clothing':
        if hit(r'\b(?:sockless|flat\s*socks|shoe liners?|shoe inserts?|bra liners?|fake collars?|false collars?|detachable collars?|nipple covers?|body tape|breast lift tape|vagina pants|breast forms?|prosthetic)\b', title):
            return 'reject', 'non_garment_accessory_or_body_product', evidence
        if hit(r'\b(?:makeup|lipstick|mascara|serum|shampoo|cosmetic brushes?)\b', title) and not hit(r'\b(?:shirt|dress|hoodie|sweater|t-shirt)\b', title):
            return 'reject', 'beauty_product_not_garment', evidence
        return 'accept', 'garment_title_and_specific_garment_evidence_no_conflict', evidence
    if domain == 'footwear':
        if hit(r'\b(?:shoe cleaner|shoe polish|shoelaces|shoe insert|heel cup|shoe tree|shoe liner|sockless|flat\s*socks)\b', title) and not hit(r'\b(?:sneakers?|sandals?|boots?|slippers?|loafers?|mules?|clogs?|flip.flops?)\b', title):
            return 'reject', 'standalone_footwear_accessory', evidence
        return 'accept', 'specific_footwear_evidence_no_conflict', evidence
    if hit(r'\b(?:for dogs|for cats|dog pool|dog ball pit|catnip)\b', title):
        if hit(r'\b(?:for kids|for toddlers|kids pools|pools for kids|kids and dogs)\b', title):
            return 'hold', 'human_pet_shared_pool_scope_ambiguous', evidence
        return 'reject', 'pet_product_not_human_toy', evidence
    if hit(r'\b(?:ipad|apple pencil)\b', title) and hit(r'\b(?:pencil|stylus)\b', title) and not hit(r'nintendo|playstation|xbox|steam deck', title):
        return 'reject', 'generic_tablet_stylus_not_game_accessory', evidence
    if categories and categories[0] in ['Video DVD', 'Home Entertainment'] and hit(r'\b(?:film|movie|master|director|Nicolas Winding Refn|getaway driver)\b', description):
        return 'reject', 'movie_not_video_game', evidence + [description[:450]]
    if hit(r'\b(?:white noise|sound machine|nap mat|slumber bag|sleeping bag|beverage cooler|cooler float)\b', title):
        if hit(r'\b(?:doll|dolls|prank|gag)\b', title):
            return 'accept', 'doll_accessory_or_prank_toy_not_household_utility', evidence
        return 'reject', 'household_baby_or_pool_utility_not_toy', evidence
    if hit(r'\b(?:hair clips?|hair bang clips?|clip.on earrings?|liquid latex|skin body paint|teacher survival kit)\b', title) and not hit(r'making kit|pretend', title):
        return 'reject', 'grooming_jewelry_or_nonplay_supplies', evidence
    if hit(r'\b(?:humanoid robot|fishing drone.*bait release|medical.*flashcards?|nursing.*flash.?cards?|anatomy.*flash.?cards?|comic book edition|savings challenge box|piggy bank for adults|adults piggy bank|tungsten cube)\b', title):
        return 'hold', 'professional_educational_or_utility_scope_not_established', evidence
    # Pure party supplies and costume clothing do not become toys through the root department.
    if any(hit(r'(?:party.*(?:balloons?|banners?|plates?|tablecovers?|tablecloths?|napkins?|cups|centerpieces?|decorations?|headwear|blowers?|candles?|invitations?|confetti|favor bags|favor boxes)|non.edible (?:cake|cupcake) toppers)', x) for x in specific):
        if hit(r'\b(?:dolls?|action figures?|stuffed animals?|fidget toys?|squishy toys?|toy assortment)\b', title):
            return 'hold', 'toy_and_decoration_dual_use_ambiguous', evidence
        return 'reject', 'pure_party_decoration_or_tableware', evidence
    if any(hit(r'\bcostumes?\b|costume (?:wigs|masks|accessory sets|jewelry)', x) for x in specific):
        if hit(r'\b(?:foam blaster|toy sword|toy hammer|playset)\b', title):
            return 'hold', 'roleplay_toy_or_costume_ambiguous', evidence
        return 'reject', 'costume_clothing_or_accessory_not_toy', evidence
    if hit(r'\b(?:cake|cupcake) toppers?|\bparty decorations?|\b(?:banner|backdrop|tableware|tablecloth|napkins|cutlery|party plates|party cups)\b', title):
        if hit(r'\b(?:toy|toys|figurines?|figures?|dolls?|plush|stuffed animals?|board game|card game|puzzle|beach balls?|painting crafts?|stress ball|bubble wands?)\b|pi[n?]atas?', title) and not any(hit(r'party (?:supplies|tableware|decorations)',x) for x in specific):
            return 'accept', 'play_product_with_incidental_decoration_wording', evidence
        if hit(r'pretend play|crafts?', title):
            return 'hold', 'decoration_or_craft_roleplay_ambiguous', evidence
        return 'reject', 'decorative_or_party_utility_product', evidence
    if hit(r'\bstickers?|\bdecals?\b', title):
        if hit(r'sticki rolls|sticki mates|sticker.*(?:activity|puzzle|scene|reusable pad)|(?:activity|puzzle|scene).*sticker|make.a.face', title):
            return 'accept', 'interactive_sticker_activity_or_collectible_toy', evidence
        if hit(r'vinyl|waterproof|water bottles?|laptops?|phone case|scrapbook|decals?|stick.on earring', text):
            return 'reject', 'generic_decorative_stickers_not_play_activity', evidence
        return 'hold', 'sticker_activity_not_established', evidence
    if hit(r'\b(?:real washable makeup|washable real cosmetic|real.*make.?up set)\b', title):
        return 'hold', 'real_cosmetics_or_toy_kit_ambiguous', evidence
    if categories and categories[0] == 'Jewelry' and hit(r'\b(?:bracelets?|rings?|necklaces?|earrings?)\b', title) and not hit(r'making kit|craft|fidget|sensory|pretend', title):
        return 'hold', 'wearable_jewelry_or_play_jewelry_ambiguous', evidence
    if hit(r'\b(?:school glue|adhesive dots|paper clips|greeting cards|photo sign|first day of school.*(?:board|sign))\b', title) and not hit(r'\b(?:toy|game|activity kit|craft kit)\b', title):
        return 'hold', 'generic_stationery_not_clear_play_kit', evidence
    if not specific:
        return 'hold', 'no_specific_category_evidence', evidence
    return 'accept', 'specific_play_game_or_accessory_evidence_no_conflict', evidence
