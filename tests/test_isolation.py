"""The four domains stay separate: a domain may import taxo.*, never another domain; core knows no domain."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOMAINS = ("food", "fragrance", "cars", "car_parts")


def imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_domains_do_not_import_each_other():
    for d in DOMAINS:
        for f in (ROOT / "domains" / d).glob("*.py"):
            bad = {m for m in imports(f) if m.startswith("domains.") and not m.startswith(f"domains.{d}")}
            assert not bad, f"{f.relative_to(ROOT)} imports another domain: {bad}"


RUNNERS = {"codex.py", "codex_tools.py"}   # run any Agents SDK agent on the Codex CLI: the SDK, but no role or domain


def test_core_knows_no_domain_and_no_agent():
    for f in (ROOT / "taxo" / "core").glob("*.py"):
        banned = ("domains", "taxo.roles") if f.name in RUNNERS else ("domains", "taxo.roles", "agents")
        bad = {m for m in imports(f) if m.startswith(banned)}
        assert not bad, f"{f.relative_to(ROOT)} imports {bad}"
