"""Shared installed-Codex-CLI transport. All domains/roles use the same FAST pin."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from functools import wraps
from pathlib import Path
from threading import BoundedSemaphore

from jsonschema import Draft202012Validator

from taxo.core.config import ROOT

LOCK = Path(__file__).with_name("validator_cli.lock.json")  # Historical name; shared by every role.
CLI_SLOTS = BoundedSemaphore(20)


def bounded_cli(fn):
    @wraps(fn)
    def call(*args, **kwargs):
        # A full loop can evaluate independent candidates concurrently, with one shared process cap.
        with CLI_SLOTS:
            return fn(*args, **kwargs)
    return call


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def fingerprint(path):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"path": str(path.resolve()), "sha256": digest, "bytes": path.stat().st_size}


def load_pin():
    return json.loads(LOCK.read_text(encoding="utf-8"))


def filtered_events(lines, *, web=False):
    """Separate transport diagnostics from executable tool items; never retain reasoning."""
    events, forbidden, diagnostics = [], [], []
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind, item = event.get('type'), event.get('item') or {}
        item_type = item.get('type')
        if item_type and item_type not in ('reasoning', 'agent_message', 'web_search', 'error'):
            forbidden.append(item_type)
        if kind == 'error' or item_type == 'error':
            # Retain only the diagnostic message, not arbitrary item payload or reasoning fields.
            diagnostic = {'type': 'error', 'source': 'item' if item_type == 'error' else 'event',
                          'message': str(item.get('message', event.get('message', '')))}
            events.append(diagnostic)
            diagnostics.append(diagnostic)
        if item_type == 'web_search':
            if web:
                events.append(event)
            else:
                forbidden.append(item_type)
        if kind in ('thread.started', 'turn.started', 'turn.completed', 'turn.failed'):
            events.append(event)
    return events, forbidden, diagnostics


@bounded_cli
def invoke(prompt: str, schema: dict, output: Path, *, web: bool = False,
           image_paths: list[Path] | None = None) -> dict:
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
        images = [Path(path).resolve(strict=True) for path in image_paths or []]
        if len(images) > 4:
            raise ValueError('At most four explicit local images per CLI call')
        image_records = []
        for path in images:
            if not path.is_file() or not 0 < path.stat().st_size <= 10*1024*1024:
                raise ValueError('Image attachment must be a nonempty file of at most 10 MiB')
            with path.open('rb') as stream:
                header = stream.read(16)
            if not (header.startswith(b'\x89PNG\r\n\x1a\n') or header.startswith(b'\xff\xd8\xff') or
                    header.startswith((b'GIF87a', b'GIF89a')) or
                    header.startswith(b'RIFF') and header[8:12] == b'WEBP'):
                raise ValueError('Unsupported image attachment magic bytes')
            image_records.append(fingerprint(path))
        if images:
            manifest['image_attachments'] = image_records
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
            if images:
                command[-1:-1] = [arg for path in images for arg in ('--image', str(path))]
            write(output / "command.json", command)
            result = subprocess.run(command, input=prompt, text=True, encoding="utf-8", errors="replace",
                                    capture_output=True, timeout=pin["timeout_seconds"])
        if any(fingerprint(path) != record for path, record in zip(images, image_records)):
            raise ValueError('Image attachment changed during CLI execution')
        events, forbidden, diagnostics = filtered_events(result.stdout.splitlines(), web=web)
        for event in events:
            if event['type'] == 'turn.completed':
                manifest['usage'].append(event.get('usage'))
        write(output / "events.json", events)
        completed = any(event['type'] == 'turn.completed' for event in events)
        terminal = [event['type'] for event in events if event['type'] in ('turn.completed', 'turn.failed')]
        manifest.update(returncode=result.returncode, forbidden_tool_types=forbidden, stderr_retained=False,
                        diagnostic_error_count=len(diagnostics),
                        cli_internal_reconnect_events=sum('reconnect' in d['message'].casefold() for d in diagnostics),
                        turn_completed=completed)
        if result.returncode or forbidden:
            raise RuntimeError(f"CLI call failed: exit={result.returncode}, forbidden tools={forbidden}; see events.json")
        if diagnostics and (not completed or terminal[-1] != 'turn.completed'):
            raise RuntimeError('CLI diagnostic errors without a successfully completed turn; see events.json')
        answer = json.loads((output / "final.json").read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(answer)
        manifest['recovered_diagnostic_warnings'] = bool(diagnostics)
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
