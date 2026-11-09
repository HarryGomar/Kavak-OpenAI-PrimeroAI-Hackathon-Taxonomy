"""Conservative Food-only source checks; no human labels or canonical name lookups."""
from __future__ import annotations

import re

from taxo.lattice.vocab import tokens


_CONTAINERS = set('bag bags box boxes pouch pouches packet packets package packages carton cartons case cases display displays wrapper wrappers'.split())
_PACKAGING = _CONTAINERS | set('peg stand up resealable reclosable zip zipper large small mini miniature bulk single individual individually wrapped retail family size count piece pieces pack packs'.split())
_FOOD = set('candy candies chocolate chocolates cracker crackers biscuit biscuits cookie cookies gummy gummies sweets cereal cereals snack snacks chews'.split())
_GENERIC = _PACKAGING | _FOOD | set('of the and with in for net weight wt ounce ounces oz lb lbs g gram grams kilogram kilograms kg piece pieces pack packs'.split())
_EXTERNAL = re.compile(r'\b(?:peg|stand[ -]up|resealable|reclosable|zipper)\s+(?:peg\s+)?(?:bag|bags|pouch|pouches)\b', re.I)
_NONFOOD = re.compile(r'\b(?:empty|reusable|storage|handbag|tote|paper)\b', re.I)


def packaging_only_identity(listing, node, tax):
    """Flag an external-container-only model when affirmative original food evidence
    and a separate named title identity survive before vocabulary stripping.

    No flag on missing/ambiguous context, edible forms, or mixed named identities.
    """
    if listing.domain != 'food' or node.level not in ('product', 'model') or len(node.path) < 2:
        return None
    model = set(tokens(node.name))
    if not model or not model <= _PACKAGING or not model & _CONTAINERS:
        return None
    title = listing.title or ''
    if not _EXTERNAL.search(title) or _NONFOOD.search(title):
        return None
    raw = listing.fields.get('raw_source') or {}
    context = ' '.join(str(raw.get(k) or '') for k in ('food_form_text', 'category_path_json', 'description_text'))
    if not set(tokens(context)) & _FOOD:
        return None
    brand = set(tokens(node.path[0]))
    remaining = [t for t in tokens(title) if t not in brand | _GENERIC and len(t) >= 3 and not any(c.isdigit() for c in t)]
    if not remaining:
        return None
    return 'Container-only identity discards a separately named original-title food product; source explicitly describes external peg/resealable packaging.'


CHECKS = {'packaging_only_identity': (packaging_only_identity, 'abstain')}
