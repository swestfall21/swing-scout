"""Report output — ranked digest for the terminal, full markdown to reports/."""

import datetime as dt

from . import REPORTS_DIR

_STANCE_ORDER = {"long_setup": 0, "short_setup": 1, "watch": 2, "avoid": 3}
_STANCE_LABEL = {
    "long_setup": "LONG SETUP", "short_setup": "SHORT SETUP",
    "watch": "WATCH", "avoid": "AVOID",
}


def _sort_key(result: dict):
    v = result.get("verdict") or {}
    return (
        _STANCE_ORDER.get(v.get("stance"), 9),
        -(v.get("conviction") or 0),
        result["symbol"],
    )


def digest_text(results: list[dict]) -> str:
    lines = ["Ranked digest:"]
    for r in sorted(results, key=_sort_key):
        v = r.get("verdict")
        if not v:
            lines.append(f"  {r['symbol']:<6} (no structured verdict — see full note)")
            continue
        stance = _STANCE_LABEL.get(v.get("stance"), str(v.get("stance")))
        parts = [f"  {r['symbol']:<6} {stance:<11} conviction {v.get('conviction', '?')}/5"]
        if v.get("entry_zone"):
            lo, hi = (v["entry_zone"] + [None, None])[:2]
            parts.append(f"entry {lo}-{hi}")
        if v.get("stop") is not None:
            parts.append(f"stop {v['stop']}")
        if v.get("targets"):
            parts.append("targets " + "/".join(str(t) for t in v["targets"]))
        if v.get("earnings_risk") not in (None, "none_in_horizon"):
            parts.append(f"⚠ earnings {v['earnings_risk']}")
        lines.append("  ".join(parts))
        if v.get("summary"):
            lines.append(f"         {v['summary']}")
    return "\n".join(lines)


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
