"""Settings from the environment (.env). Model names and data paths live here, never in code."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def data_dir() -> Path:
    d = os.environ.get("TAXO_DATA_DIR")
    if not d:
        raise RuntimeError("TAXO_DATA_DIR is not set (see .env.example)")
    return Path(d)


def model(role: str) -> str:
    """role: placer | validator | improver | proposer | judge_fast | judge_strong"""
    return os.environ.get(f"TAXO_MODEL_{role.upper()}", "gpt-6-luna")


RUNS_DIR = ROOT / "runs"
MEMORY_DIR = ROOT / "memory"
DOMAINS_DIR = ROOT / "domains"
