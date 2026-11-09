"""Shared installed-Codex-CLI transport. All domains/roles use the same FAST pin."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from jsonschema import Draft202012Validator

from taxo.core.config import ROOT

LOCK = Path(__file__).with_name("validator_cli.lock.json")  # Historical name; shared by every role.


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def fingerprint(path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.resolve()), "sha256": digest, "bytes": path.stat().st_size}


def load_pin():
    return json.loads(LOCK.read_text(encoding="utf-8"))


def invoke(prompt: str, schema: dict, output: Path, *, web: bool = False) -> dict:
    """One CLI call, refusing invalid output. Reasoning content is never persisted."""
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    start = time.monotonic()
    pin = load_pin()
    manifest = {"status": "running", "pin": pin, "transport": fingerprint(Path(__file__)),
                "lock": fingerprint(LOCK), "git_head": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "web": web, "cost": None, "actual_served_tier": None, "usage": [], "retries": 0}
    try:
        executable = shutil.which("codex")
        if not executable:
            raise RuntimeError("Installed Codex CLI missing; no SDK/API fallback")
        version = subprocess.check_output([executable, "--version"], text=True).strip()
        manifest.update(cli_version=version, executable=fingerprint(Path(executable)))
        if version != pin["cli_version"]:
            raise RuntimeError(f"CLI version {version!r} differs from pin {pin['cli_version']!r}")
        (output / "prompt.txt").write_text(prompt, encoding="utf-8")
        write(output / "schema.json", schema)
        with tempfile.TemporaryDirectory(prefix="taxo-cli-") as isolated:
            command = [executable, "exec", "--ignore-user-config", "--strict-config", "--ephemeral",
                       "--sandbox", "read-only", "--skip-git-repo-check", "--cd", isolated,
                       "--model", pin["model"], "-c", f'model_reasoning_effort="{pin["reasoning_effort"]}"',
                       "-c", f'service_tier="{pin["service_tier"]}"', "-c", 'model_reasoning_summary="none"',
                       "-c", f'web_search="{"live" if web else "disabled"}"', "--json", "--color", "never",
                       "--output-schema", str(output / "schema.json"),
                       "--output-last-message", str(output / "final.json"), "-"]
            write(output / "command.json", command)
            result = subprocess.run(command, input=prompt, text=True, encoding="utf-8", errors="replace",
                                    capture_output=True, timeout=pin["timeout_seconds"])
        events, forbidden = [], []
        for line in result.stdout.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind, item = event.get("type"), event.get("item") or {}
            item_type = item.get("type")
            if item_type and item_type not in ("reasoning", "agent_message", "web_search"):
                forbidden.append(item_type)
            if item_type == "web_search":
                if not web:
                    forbidden.append(item_type)
                else:
                    events.append(event)
            if kind in ("thread.started", "turn.started", "turn.completed", "turn.failed", "error"):
                events.append(event)
            if kind == "turn.completed":
                manifest["usage"].append(event.get("usage"))
        write(output / "events.json", events)
        manifest.update(returncode=result.returncode, forbidden_tool_types=forbidden, stderr_retained=False)
        if result.returncode or forbidden:
            raise RuntimeError(f"CLI call failed: exit={result.returncode}, forbidden tools={forbidden}; see events.json")
        answer = json.loads((output / "final.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(answer)
        manifest["status"] = "completed"
        return answer
    except Exception as error:
        manifest["status"] = "failed"
        write(output / "error.json", {"type": type(error).__name__, "message": str(error)})
        raise
    finally:
        manifest["elapsed_seconds"] = round(time.monotonic() - start, 3)
        manifest["artifacts"] = [fingerprint(p) for p in sorted(output.iterdir()) if p.is_file() and p.name != "manifest.json"]
        write(output / "manifest.json", manifest)
