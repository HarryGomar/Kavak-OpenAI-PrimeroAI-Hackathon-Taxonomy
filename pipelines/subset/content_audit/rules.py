"""Combine independent scope checks with conservative source-quality holds."""
import importlib.util
from pathlib import Path
from .food import check as food_check
from .other_domains import decide as other_check
from .quality import check as quality_check

_path = Path(__file__).resolve().parents[1] / 'delivery/s3-gold-check-20261109/semantic_guard.py'
_spec = importlib.util.spec_from_file_location('prior_raw_positive_evidence', _path)
_prior = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_prior)


def decide(domain, row):
    if domain == 'fragrance':
        raise ValueError('Fragrance is excluded from repair by owner instruction.')
    quality = quality_check(row)
    if quality:
        return {'decision': 'hold', 'reason': quality[0], 'evidence': quality[1]}
    if domain == 'food':
        result = food_check(row)
        if result['decision'] != 'accept':
            return result
        verdict, reason, evidence = _prior.decide('food', row)
        return {'decision': verdict, 'reason': reason, 'evidence': evidence}
    verdict, reason, evidence = other_check(domain, row)
    return {'decision': verdict, 'reason': reason, 'evidence': evidence}
