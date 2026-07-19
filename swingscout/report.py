"""Report output — ranked digest for the terminal, full markdown to reports/.

The digest leads with what clears the conviction bar (long/short setups at
conviction ≥ threshold); everything else is listed below it as watch-only.
Each run's structured verdicts are merged into data/research.json so the
dashboard can show the analyst's latest call per symbol.
"""

import datetime as dt
import json
from pathlib import Path

from . import DATA_DIR, REPORTS_DIR, conviction_threshold

RESEARCH_FILE = DATA_DIR / "research.json"

_STANCE_ORDER = {"long_setup": 0, "short_setup": 1, "watch": 2, "avoid": 3}
_STANCE_LABEL = {
    "long_setup": "LONG SETUP", "short_setup": "SHORT SETUP",
    "watch": "WATCH", "avoid": "AVOID",
}


def is_actionable(verdict: dict | None, threshold: int) -> bool:
    return bool(verdict) and verdict.get("stance") in ("long_setup", "short_setup") \
        and (verdict.get("conviction") or 0) >= threshold


def _sort_key(result: dict):
    v = result.get("verdict") or {}
    return (
        _STANCE_ORDER.get(v.get("stance"), 9),
        -(v.get("conviction") or 0),
        result["symbol"],
    )


def _entry_lines(result: dict) -> list[str]:
    v = result.get("verdict")
    if not v:
        return [f"  {result['symbol']:<6} (no structured verdict — see full note)"]
    stance = _STANCE_LABEL.get(v.get("stance"), str(v.get("stance")))
    parts = [f"  {result['symbol']:<6} {stance:<11} conviction {v.get('conviction', '?')}/5"]
    if v.get("entry_zone"):
        lo, hi = (v["entry_zone"] + [None, None])[:2]
        parts.append(f"entry {lo}-{hi}")
    if v.get("stop") is not None:
        parts.append(f"stop {v['stop']}")
    if v.get("targets"):
        parts.append("targets " + "/".join(str(t) for t in v["targets"]))
    if v.get("earnings_risk") not in (None, "none_in_horizon"):
        parts.append(f"⚠ earnings {v['earnings_risk']}")
    lines = ["  ".join(parts)]
    if v.get("summary"):
        lines.append(f"         {v['summary']}")
    return lines


def digest_text(results: list[dict]) -> str:
    threshold = conviction_threshold()
    ranked = sorted(results, key=_sort_key)
    actionable = [r for r in ranked if is_actionable(r.get("verdict"), threshold)]
    rest = [r for r in ranked if not is_actionable(r.get("verdict"), threshold)]

    lines = [f"Actionable (long/short setup, conviction ≥ {threshold}/5):"]
    if actionable:
        for r in actionable:
            lines.extend(_entry_lines(r))
    else:
        closest = next((r for r in ranked if r.get("verdict")), None)
        note = "  none — nothing clears the bar this run"
        if closest:
            v = closest["verdict"]
            note += (f" (closest: {closest['symbol']} "
                     f"{_STANCE_LABEL.get(v.get('stance'), '?').lower()} "
                     f"{v.get('conviction', '?')}/5)")
        lines.append(note)
    if rest:
        lines.append("Below the bar — watch, don't chase:")
        for r in rest:
            lines.extend(_entry_lines(r))
    return "\n".join(lines)


def load_verdicts() -> dict:
    try:
        return json.loads(RESEARCH_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_verdicts(results: list[dict], report_path: str) -> None:
    """Merge this run's verdicts into data/research.json (per-symbol latest)."""
    store = load_verdicts()
    today = f"{dt.date.today():%Y-%m-%d}"
    for r in results:
        v = r.get("verdict")
        if not v:
            continue
        store[r["symbol"]] = {**v, "date": today, "report": Path(report_path).name}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESEARCH_FILE.write_text(json.dumps(store, indent=2) + "\n")


def write_report(results: list[dict]) -> str:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now()
    path = REPORTS_DIR / f"{now:%Y-%m-%d_%H%M}.md"

    total_in = sum(r["usage"]["input"] for r in results)
    total_out = sum(r["usage"]["output"] for r in results)

    parts = [
        f"# Swing Scout research — {now:%Y-%m-%d %H:%M}",
        "",
        "```",
        digest_text(results),
        "```",
        "",
        f"_Symbols: {len(results)} · tokens {total_in:,} in / {total_out:,} out_",
        "",
        "---",
        "",
    ]
    for r in sorted(results, key=_sort_key):
        parts.append(r["note"])
        parts.append("\n---\n")
    path.write_text("\n".join(parts))
    return str(path)
