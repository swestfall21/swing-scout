"""Watchlist persistence — a JSON list of upper-cased ticker symbols."""

import json
import re

from . import DATA_DIR

WATCHLIST_FILE = DATA_DIR / "watchlist.json"
_SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def load() -> list[str]:
    if not WATCHLIST_FILE.exists():
        return []
    return json.loads(WATCHLIST_FILE.read_text())


def save(symbols: list[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    WATCHLIST_FILE.write_text(json.dumps(sorted(set(symbols)), indent=2) + "\n")


def normalize(symbol: str) -> str:
    sym = symbol.strip().upper()
    if not _SYMBOL_RE.match(sym):
        raise ValueError(f"{symbol!r} doesn't look like a ticker symbol")
    return sym


def add(symbols: list[str]) -> tuple[list[str], list[str]]:
    """Returns (added, already_present)."""
    current = load()
    added, present = [], []
    for raw in symbols:
        sym = normalize(raw)
        (present if sym in current else added).append(sym)
        if sym not in current:
            current.append(sym)
    save(current)
    return added, present


def remove(symbols: list[str]) -> tuple[list[str], list[str]]:
    """Returns (removed, not_found)."""
    current = load()
    removed, missing = [], []
    for raw in symbols:
        sym = normalize(raw)
        if sym in current:
            current.remove(sym)
            removed.append(sym)
        else:
            missing.append(sym)
    save(current)
    return removed, missing
