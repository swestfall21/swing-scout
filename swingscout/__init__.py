"""Swing Scout — watchlist research copilot for swing trading (stocks only)."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
REPORTS_DIR = PROJECT_ROOT / "reports"


def conviction_threshold() -> int:
    """Analyst conviction (1-5) a long/short setup needs before it's treated
    as actionable rather than watch-only. Override with SCOUT_CONVICTION_MIN
    (env or .env)."""
    import os

    try:
        return max(1, min(5, int(os.environ.get("SCOUT_CONVICTION_MIN", "4"))))
    except ValueError:
        return 4


def load_env() -> None:
    """Load KEY=VALUE lines from a project-root .env into os.environ (no override)."""
    import os

    env_file = PROJECT_ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
