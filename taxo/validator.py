"""The validator (SPEC §5.2), run through the Codex CLI: `codex exec` in a read-only sandbox, started in an empty folder
so it sees only the prompt (never the pipeline's answer or the gold label). One call labels a whole round.

    uv run python -m taxo.validator fragrance V3            runs/<d>/loopb/V3-blind.jsonl -> V3-validator.jsonl

The card is domains/<d>/validator.yaml: task text plus a checklist of steps (active ones go in the prompt). An answer
that does not parse, or names an id that was not asked, is refused and logged, never patched.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

from taxo.core.config import DOMAINS_DIR, RUNS_DIR
from taxo.lattice.vocab import tokens

SCHEMA = {"type": "object", "additionalProperties": False, "required": ["labels"],
          "properties": {"labels": {"type": "array", "items": {
              "type": "object", "additionalProperties": False, "required": ["id", "path", "why"],
              "properties": {"id": {"type": "string"}, "path": {"type": "array", "items": {"type": "string"}},
                             "why": {"type": "string"}}}}}}


def card(domain: str) -> dict:
    return yaml.safe_load((DOMAINS_DIR / domain / "validator.yaml").read_text(encoding="utf-8"))


def prompt(c: dict, items: list[dict], base: bool = False) -> str:
    """`base`: the card without its checklist (the version-1 validator), for an A/B on the same sample."""
    steps = [] if base else [s["text"] for s in c.get("checklist") or [] if s.get("status", "active") == "active"]
    rows = [{k: it.get(k) for k in c.get("inputs") or ["title", "brand"]} | {"id": it["id"]} for it in items]
    return (c["task"].strip()
            + ("\n\nChecklist:\n" + "\n".join(f"- {s}" for s in steps) if steps else "")
            + "\n\nAnswer every listing below, in order, with its id. Do not run commands or read files; use only "
              "this text.\n\n" + json.dumps(rows, ensure_ascii=False, indent=0))


def label(domain: str, items: list[dict], log: Path, base: bool = False, timeout: int = 1800,
          c: dict | None = None) -> list[dict]:
    """One `codex exec` call over `items` (id, title, brand, source, url, menu). Returns one label per answered item:
    {id, path (brand first, the brand as given), why, card, validator}. A malformed answer raises; it is never patched.
    `c`: a candidate card to try instead of domains/<d>/validator.yaml (the improver's A/B)."""
    c = c or card(domain)
    exe = shutil.which("codex") or "codex"
    with tempfile.TemporaryDirectory() as tmp:     # empty working root: nothing to read but the prompt
        t = Path(tmp)
        (t / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
        # --ignore-user-config: the user's default model and MCP servers stay out (the ChatGPT sign-in still applies)
        cmd = [exe, "exec", "--ignore-user-config", "--sandbox", "read-only", "--skip-git-repo-check", "--ephemeral",
               "--color", "never", "-C", tmp, "--output-schema", str(t / "schema.json"), "-o", str(t / "out.json")]
        if c.get("model"):
            cmd += ["-m", c["model"]]
        p = subprocess.run(cmd + ["-"], input=prompt(c, items, base), capture_output=True, text=True, encoding="utf-8",
                           timeout=timeout)
        raw = (t / "out.json").read_text(encoding="utf-8") if (t / "out.json").exists() else ""
    model = next((ln.split(":", 1)[1].strip() for ln in p.stderr.splitlines() if ln.startswith("model:")),
                 c.get("model") or "default")
    card_v = "v1" if base else f"v{c.get('version', 1)}"
    log.write_text(f"exit {p.returncode}\n--- stderr\n{p.stderr[-4000:]}\n--- answer\n{raw}", encoding="utf-8")
    try:
        answers = json.loads(raw)["labels"]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise SystemExit(f"validator answer refused ({e}); see {log}")
    asked = {it["id"]: it for it in items}
    out = []
    for lab in answers:
        it = asked.get(lab.get("id"))
        if it is None or not isinstance(lab.get("path"), list):
            continue
        path = [s.strip() for s in lab["path"] if isinstance(s, str) and s.strip()]
        if path and tokens(path[0]) == tokens(it["brand"]):
            path = path[1:]
        out.append({"id": it["id"], "path": [it["brand"]] + path,  # the brand is given, never the validator's to change
                    "why": lab.get("why", ""), "card": card_v, "validator": f"codex-cli:{model}"})
    print(f"{len(out)} labels, {len(answers) - len(out)} refused, {len(items) - len(answers)} missing")
    return out


def run(domain: str, version: str, timeout: int = 1800, base: bool = False) -> Path:
    """Label a Loop B round's blind file -> runs/<d>/loopb/<V>-validator[-base].jsonl."""
    d = RUNS_DIR / domain / "loopb"
    items = [json.loads(x) for x in open(d / f"{version}-blind.jsonl", encoding="utf-8")]
    tag = "-base" if base else ""
    labels = label(domain, items, d / f"{version}-validator{tag}.log", base, timeout)
    out = d / f"{version}-validator{tag}.jsonl"
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in labels), encoding="utf-8")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="taxo.validator")
    ap.add_argument("domain")
    ap.add_argument("version")
    ap.add_argument("--base", action="store_true", help="run the card without its checklist (v1) -> <V>-validator-base.jsonl")
    a = ap.parse_args()
    run(a.domain, a.version, base=a.base)


if __name__ == "__main__":
    main()
