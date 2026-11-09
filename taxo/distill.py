"""Distillation (SPEC §5.3, Loop C): gather every team member's rounds from every branch and turn the gated ones into
lessons with a scope and a record.

runs/ stays outside Git, so a round travels as a *round record*: one small JSON file in memory/rounds/<domain>/ with
the KPI row and the gate's decision (counts and rates only, never a listing or a label). One file per round, so
branches merge without conflicts. The gate writes it; `export` backfills rounds made before that.

    uv run python -m taxo.distill export fragrance [--runs runs/fragrance]   KPI history + gate files -> round records
    uv run python -m taxo.distill collect [--no-fetch]                       every origin branch -> lessons/, docs/DISTILL.md

A lesson groups rounds by their `lesson` id (set with --lesson on the gate; the same id in two domains is how a shape
is said to transfer), else by their change text. Kept in two domains -> global; kept in one -> that domain; never
kept -> dropped. Lessons are written by code from the records; a person edits a lesson's claim, never its record.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import defaultdict
from pathlib import Path

import yaml

from taxo.core.config import MEMORY_DIR, ROOT, RUNS_DIR

ROUNDS_DIR = MEMORY_DIR / "rounds"
LESSONS_DIR = ROOT / "lessons"
REPORT = ROOT / "docs" / "DISTILL.md"
_PREFIX = re.compile(r"^(gate (KEPT|DROPPED): |DROPPED on dev \([^)]*\): )")
_ROUND = re.compile(r"^(drive |edu )?r\d+: ")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, encoding="utf-8",
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "unnamed"


def _decision(label: str, gate: dict | None) -> tuple[bool | None, str | None]:
    """(keep, decided on): from the gate file, else from the label the gate or a person wrote."""
    if gate is not None:
        return gate["keep"], "sealed"
    if label.startswith("gate KEPT"):
        return True, "sealed"
    if label.startswith("gate DROPPED"):
        return False, "sealed"
    if label.startswith("DROPPED on dev"):
        return False, "dev"
    return None, None


def gate_label(label: str) -> str:
    """The label the gate was given: 'gate KEPT: drive r3: brand_site rung' -> 'drive r3: brand_site rung'."""
    return _PREFIX.sub("", label)


def change_of(label: str) -> str:
    """The change itself, without the gate's prefix or the round tag: '... drive r3: brand_site rung' -> 'brand_site rung'."""
    return _ROUND.sub("", gate_label(label)).strip()


def record(domain: str, kpi: dict, gate: dict | None = None, lesson: str | None = None, kind: str | None = None,
           branch: str | None = None, author: str | None = None) -> Path | None:
    """Write one round record; None when it is already there (same domain, time, label and code)."""
    keep, decided = _decision(kpi["label"], gate)
    rid = hashlib.sha256(json.dumps([domain, kpi["ts"], kpi["label"], kpi.get("code")]).encode()).hexdigest()[:10]
    path = ROUNDS_DIR / domain / f"{kpi['ts'].replace(':', '').replace('-', '')}-{rid}.json"
    if path.exists():
        return None
    g = None
    if gate:
        g = {k: gate.get(k) for k in ("touched", "better", "worse", "why", "agent_before", "agent_after")}
        g |= {side: {k: gate[side].get(k) for k in ("accept_rows", "exact_rate", "right_or_shallower", "harm_rate")}
              for side in ("before", "after")}
        if gate.get("human_sealed"):
            g["human_sealed"] = {k: gate["human_sealed"][k] for k in ("better", "worse")}
    rec = {"id": rid, "domain": domain, "ts": kpi["ts"], "loop": kpi["loop"], "round": kpi["round"],
           "change": change_of(kpi["label"]), "label": kpi["label"], "keep": keep, "decided_on": decided,
           "lesson": lesson, "kind": kind,
           "branch": branch or _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
           "author": author or _git("config", "user.name") or "unknown", "gate": g, "kpi": kpi}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def export(domain: str, runs: Path, branch: str | None = None) -> list[Path]:
    """Backfill: every row of <runs>/kpis.jsonl, with its gate-rN.json where one matches the round and label."""
    gates = {}
    for f in runs.glob("*/gate-r*.json"):
        g = json.loads(f.read_text(encoding="utf-8"))
        gates[(g["round"], g["label"])] = g
    out = []
    for line in (runs / "kpis.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        kpi = json.loads(line)
        gate = gates.get((kpi["round"], gate_label(kpi["label"]))) if kpi["label"].startswith("gate ") else None
        if p := record(domain, kpi, gate, branch=branch):
            out.append(p)
    return out


# --- collect: every branch -> one set of records -> lessons -------------------------------------------------

def _refs() -> list[str]:
    return [r for r in _git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin").splitlines()
            if r not in ("", "origin", "origin/HEAD")]


def _records_on(ref: str) -> list[dict]:
    names = _git("ls-tree", "-r", "--name-only", ref, "--", "memory/rounds").splitlines()
    return [json.loads(_git("show", f"{ref}:{n}")) for n in names if n.endswith(".json")]


def collect(fetch: bool = True) -> dict[str, dict]:
    """Records from this checkout and every origin branch, by id, each with the branches it was seen on."""
    if fetch:
        _git("fetch", "--all", "--prune", "--quiet")
    sources = [("(here)", [json.loads(p.read_text(encoding="utf-8")) for p in ROUNDS_DIR.glob("*/*.json")])]
    sources += [(ref, _records_on(ref)) for ref in _refs()]
    out: dict[str, dict] = {}
    for ref, recs in sources:
        for r in recs:
            out.setdefault(r["id"], r | {"seen_on": []})["seen_on"].append(ref)
    return out


def _delta(a: dict, b: dict, key: str) -> float | None:
    """after - before, or None when a side lacks the rate (records from other domains may carry counts only)."""
    x, y = (a or {}).get(key), (b or {}).get(key)
    return round(x - y, 4) if isinstance(x, (int, float)) and isinstance(y, (int, float)) else None


def lessons(records: dict[str, dict]) -> list[dict]:
    """Group decided rounds into lessons and scope each one by where it was kept (SPEC §5.3 step 4)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in records.values():
        if r["keep"] is not None:
            groups[r["lesson"] or _slug(r["change"])].append(r)
    out = []
    for lid, rs in sorted(groups.items()):
        rs.sort(key=lambda r: r["ts"])
        kept = sorted({r["domain"] for r in rs if r["keep"]})
        rows = []
        for r in rs:
            g = r.get("gate") or {}
            b, a = g.get("before") or {}, g.get("after") or {}
            rows.append({"domain": r["domain"], "loop": r["loop"], "round": r["round"], "branch": r["branch"],
                         "author": r["author"], "keep": r["keep"], "decided_on": r["decided_on"],
                         "better": g.get("better"), "worse": g.get("worse"),
                         "delta_exact": _delta(a, b, "exact_rate"),
                         "delta_harm": _delta(a, b, "harm_rate"),
                         "delta_agent": round(g["agent_after"] - g["agent_before"], 4)
                         if g.get("agent_after") is not None else None,
                         "record": r["id"]})
        out.append({"id": f"lesson/{lid}", "kind": next((r["kind"] for r in rs if r["kind"]), None),
                    "scope": "global" if len(kept) >= 2 else f"domain:{kept[0]}" if kept else None,
                    "status": "active" if kept else "dropped", "claim": rs[-1]["change"], "record": rows})
    return out


def write_lessons(ls: list[dict]) -> None:
    """lessons/<id>.yaml. A claim or kind a person already wrote is kept; the record is always rewritten from the runs."""
    LESSONS_DIR.mkdir(exist_ok=True)
    for i, le in enumerate(ls):
        p = LESSONS_DIR / f"{le['id'].split('/', 1)[1]}.yaml"
        if p.exists():
            old = yaml.safe_load(p.read_text(encoding="utf-8").split("\n", 1)[1]) or {}
            le = le | {k: old[k] for k in ("claim", "kind") if old.get(k)}
            ls[i] = le                                   # the report shows the claim a person wrote
        p.write_text("# Written by taxo.distill from memory/rounds/. Edit the claim or kind; the record is regenerated.\n"
                     + yaml.safe_dump(le, sort_keys=False, allow_unicode=True, width=120), encoding="utf-8")


def _pct(a: dict, b: dict, key: str) -> str:
    d = _delta(a, b, key)
    return f"{d * 100:+.1f}" if d is not None else ""


def report(records: dict[str, dict], ls: list[dict]) -> str:
    rs = sorted(records.values(), key=lambda r: (r["domain"], r["ts"]))
    decided = [r for r in rs if r["keep"] is not None]
    out = ["# Distilled rounds", "",
           "*Generated by `uv run python -m taxo.distill collect` from `memory/rounds/` on every branch. Do not edit.*",
           "", f"{len(rs)} round records ({len(decided)} decided) from {len({r['author'] for r in rs})} people in "
           f"{len({r['domain'] for r in rs})} domains. Deltas are on sealed gold, in points.", "",
           "## Lessons", "", "| Lesson | Scope | Status | Kept in | Dropped in | Rounds |", "|---|---|---|---|---|---:|"]
    for le in ls:
        kept = sorted({x["domain"] for x in le["record"] if x["keep"]})
        dropped = sorted({x["domain"] for x in le["record"] if x["keep"] is False})
        out.append(f"| {le['claim']} | {le['scope'] or '-'} | {le['status']} | {', '.join(kept) or '-'} | "
                   f"{', '.join(dropped) or '-'} | {len(le['record'])} |")
    out += ["", "## Decided rounds", "",
            "| Domain | Branch | Author | Loop/round | Change | Decision | Better / worse | Δ exact | Δ harm | Δ to agent |",
            "|---|---|---|---|---|---|---|---:|---:|---:|"]
    for r in decided:
        g = r.get("gate") or {}
        b, a = g.get("before") or {}, g.get("after") or {}
        bw = f"{g['better']} / {g['worse']}" if g.get("better") is not None else ""
        agent = f"{(g['agent_after'] - g['agent_before']) * 100:+.1f}" if g.get("agent_after") is not None else ""
        out.append(f"| {r['domain']} ({(r.get('kpi') or {}).get('data') or 'edu'}) | {r['branch']} | {r['author']} | {r['loop']}/{r['round']} | {r['change']} | "
                   f"{'kept' if r['keep'] else 'dropped'} ({r['decided_on']}) | {bw} | {_pct(a, b, 'exact_rate')} | "
                   f"{_pct(a, b, 'harm_rate')} | {agent} |")
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.distill")
    sub = ap.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("export")
    ex.add_argument("domain")
    ex.add_argument("--runs", type=Path, help="a runs/<domain> dir (default: this checkout's)")
    ex.add_argument("--branch", help="the branch the runs were made on (default: this checkout's)")
    sub.add_parser("collect").add_argument("--no-fetch", action="store_true")
    a = ap.parse_args()
    if a.cmd == "export":
        paths = export(a.domain, a.runs or RUNS_DIR / a.domain, a.branch)
        print(f"{len(paths)} new round records in {ROUNDS_DIR / a.domain}")
        return
    recs = collect(fetch=not a.no_fetch)
    ls = lessons(recs)
    write_lessons(ls)
    REPORT.write_text(report(recs, ls), encoding="utf-8")
    print(f"{len(recs)} records, {len(ls)} lessons -> {LESSONS_DIR}, {REPORT}")


if __name__ == "__main__":
    main()
