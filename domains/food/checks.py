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


def source_flavour_omitted(listing, node, tax):
    """Request source-evidence investigation when a literal original flavour is omitted.

    This is not a wrong-path verdict or an instruction to create a variant: a
    flavour may belong in the model, already be represented by an alias, or
    conflict with the title. Title priority remains an agent evidence question.
    Apply after routing/brand settlement as well as to product candidates.
    """
    if listing.domain != 'food' or node.domain != 'food' or not node.path:
        return None
    raw = listing.fields.get('raw_source')
    value = raw.get('flavor_text') if isinstance(raw, dict) else None
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if ('\n' in value or any(c in value for c in '<>{}[]') or any(c.isdigit() for c in value) or
        ' '.join(value.casefold().split()) in {'default', 'default title', 'unspecified', 'unknown',
                                             'n/a', 'none', 'null', 'not applicable', 'select flavor', 'choose flavor'}):
        return None
    flavour = set(tokens(value))
    quantities = {'pack', 'packs', 'count', 'ct', 'oz', 'ounce', 'ounces', 'g', 'gram', 'grams',
                  'kg', 'ml', 'l', 'lb', 'lbs', 'serving', 'servings'}
    if not flavour or flavour & quantities:
        return None
    missing = flavour - set(tokens(' '.join(node.path)))
    if not missing:
        return None
    return (f'Original flavour field {value!r} has literal words omitted from the proposed identity path; '
            'request agent_evidence investigation. Do not force a variant, rename a product, or override '
            'conflicting title evidence; aliases and source-field disagreement may explain the omission.')


CHECKS = {'packaging_only_identity': (packaging_only_identity, 'abstain'),
          'source_flavour_omitted': (source_flavour_omitted, 'abstain')}
