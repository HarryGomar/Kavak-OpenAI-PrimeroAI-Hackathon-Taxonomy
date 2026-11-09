"""A domain = a pack (pack.yaml) + an adapter (adapter.py) under domains/<name>/. Loaded by name, never imported
by another domain."""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Iterator

import yaml

from taxo.core.config import DOMAINS_DIR
from taxo.core.schemas import Listing, Node

DOMAINS = ("food", "fragrance", "cars", "car_parts", "electronics")


@dataclass
class Domain:
    name: str
    pack: dict

    @property
    def adapter(self):
        return importlib.import_module(f"domains.{self.name}.adapter")

    def listings(self, limit: int | None = None) -> Iterator[Listing]:
        return self.adapter.load_listings(limit=limit)

    def nodes(self) -> Iterator[Node]:
        return self.adapter.load_taxonomy()


def load(name: str) -> Domain:
    if name not in DOMAINS:
        raise ValueError(f"unknown domain {name!r}; known: {DOMAINS}")
    pack = yaml.safe_load((DOMAINS_DIR / name / "pack.yaml").read_text(encoding="utf-8"))
    return Domain(name, pack)
