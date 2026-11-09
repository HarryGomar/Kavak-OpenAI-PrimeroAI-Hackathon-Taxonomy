"""Category step for electronics: which browse category a listing's own product is (title rules first, the source
category only corroborates). Category is a field on the placement, never a tree level or part of a node id.

Ported unchanged in behaviour from the Taxonomy repo's scripts/profile_tools.py (Pack.categorize), reading
domains/electronics/categories/{taxonomy,category-rules,source-categories}.yaml.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent / "categories"
FILES = ("taxonomy.yaml", "category-rules.yaml", "source-categories.yaml")


def normalized(text):
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (text or "").casefold()).split())


def require(cond, msg):
    if not cond:
        raise ValueError(msg)


class Categories:
    def __init__(self, folder: Path = HERE):
        digest = hashlib.sha256()
        docs = {}
        for name in FILES:
            raw = (folder / name).read_bytes()
            digest.update(name.encode() + b"\0" + raw + b"\0")
            docs[name] = yaml.safe_load(raw)
        self.digest = digest.hexdigest()
        self.categories = {c["id"]: c for c in docs["taxonomy.yaml"]["categories"]}
        self.hints = {}
        crosswalk = docs["source-categories.yaml"]
        self.crosswalk_version = crosswalk["version"]
        for group in crosswalk["hint_groups"]:
            for alias in group["aliases"]:
                self.hints[normalized(alias)] = group["category"]
        self.rules = docs["category-rules.yaml"]
        self.boundary = re.compile(self.rules["subject"]["compatibility_boundary"], re.IGNORECASE)
        self.inclusion_boundary = re.compile(self.rules["subject"]["inclusion_boundary"], re.IGNORECASE)
        self.bundle_patterns = self.compile_patterns(self.rules["bundle_patterns"])
        for group in ("title_rules", "exclude_rules"):
            for rule in self.rules[group]:
                rule["_any"] = self.compile_patterns(rule["any"])
                rule["_none"] = self.compile_patterns(rule.get("none", []))
                if group == "title_rules":
                    require(rule["category"] in self.categories, f"Unknown rule category {rule['category']}")
        self.title_rules = sorted(self.rules["title_rules"], key=lambda x: x["id"])

    @staticmethod
    def compile_patterns(patterns):
        return [re.compile(p, re.IGNORECASE) for p in patterns]

    def path(self, cid):
        return " / ".join(self.categories[c]["label"] for c in reversed(self.ancestors(cid)))

    def ancestors(self, cid):
        result = []
        while cid is not None:
            require(cid not in result, f"Category cycle at {cid}")
            require(cid in self.categories, f"Unknown category parent {cid}")
            result.append(cid)
            cid = self.categories[cid]["parent"]
        return result

    def compatible_categories(self, left, right):
        return left in self.ancestors(right) or right in self.ancestors(left)

    def categorize(self, row):
        title = row.get("title", "")
        split = self.boundary.search(title)
        before_reference = title[:split.start()] if split else title
        inclusion = self.inclusion_boundary.search(before_reference)
        subject = before_reference[:inclusion.start()] if inclusion else before_reference
        hint = self.hints.get(normalized(row.get("source_category", "")))
        hits = []
        excluded = []
        for rule in self.rules["exclude_rules"] + self.title_rules:
            matches = [m for pattern in rule["_any"] if (m := pattern.search(subject))]
            if not matches or any(p.search(subject) for p in rule["_none"]):
                continue
            match = min(matches, key=lambda m: (m.start(), -len(m.group())))
            evidence = {
                "record_key": row["record_key"],
                "field": "title",
                "start": match.start(),
                "end": match.end(),
                "text": title[match.start():match.end()],
            }
            hit = {"rule_id": f"{rule['id']}@{self.rules['version']}", "evidence": evidence}
            if "category" in rule:
                hits.append({**hit, "category": rule["category"], "priority": rule["priority"]})
            else:
                excluded.append(hit)
        category = None
        if excluded:
            status = "out_of_scope" if not hits else "ambiguous"
        elif hits:
            best_priority = max(h["priority"] for h in hits)
            best = sorted({h["category"] for h in hits if h["priority"] == best_priority})
            deepest = [
                cid for cid in best
                if all(other in self.ancestors(cid) for other in best)
            ]
            if len(deepest) != 1:
                status = "ambiguous"
            else:
                category = deepest[0]
                status = (
                    "title_only" if not hint else
                    "title_corroborated" if self.compatible_categories(category, hint) else
                    "title_overrides_source"
                )
        elif hint:
            status = "source_hint_only"
        else:
            status = "unmapped"
        composition = any(p.search(before_reference) for p in self.bundle_patterns)
        return {
            "record_key": row["record_key"],
            "dataset": row.get("dataset", ""),
            "merchant": row.get("merchant", ""),
            "title": title,
            "source_category": row.get("source_category", ""),
            "source_hint": hint,
            "proposed_category": category,
            "profile": self.categories[category]["profile"] if category else None,
            "status": status,
            "needs_review": True,
            "composition_review": composition,
            "subject_text": subject,
            "reference_text": title[split.start():] if split else "",
            "included_text": before_reference[inclusion.start():] if inclusion else "",
            "rule_hits": hits + excluded,
            "source_hint_evidence": (
                {"field": "source_category", "raw_value": row.get("source_category", ""),
                 "rule_id": f"source-category-hint@{self.crosswalk_version}"}
                if hint else None
            ),
            "categories_sha256": self.digest,
        }
