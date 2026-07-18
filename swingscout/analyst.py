"""Claude analyst — per-symbol swing-trade research grounded in real data.

Each symbol gets one deep-research call through the Claude Code CLI
(`claude -p`, headless mode), which bills the user's Claude subscription —
no API key needed. The deterministic indicator snapshot and recent price
action are provided as ground truth, and Claude uses web search for news,
catalysts, and upcoming earnings. The response is a markdown research note
ending in a machine-readable JSON verdict.
"""

import json
import re
import shutil
import subprocess
import sys

MODEL = "opus"
TIMEOUT_S = 900  # per-symbol ceiling; opus + web search runs a few minutes

SYSTEM_PROMPT = """\
You are an experienced swing-trade analyst producing research notes for a \
single retail trader managing a small stock-only account (no options, no \
shorting unless flagged as such, holds of roughly 3-30 trading days).

Principles:
- Ground every technical claim in the indicator snapshot and price history \
provided in the message — do not invent levels. Use web search for what the \
data can't tell you: recent news, upcoming earnings dates, analyst moves, \
sector context, and catalysts.
- Risk first. Every setup needs a stop and the reasoning behind it. If the \
honest answer is "no edge here right now", say so — "watch" and "avoid" are \
good answers. Do not manufacture a trade.
- Check for imminent binary events (earnings within the horizon, FDA dates, \
court rulings). Flag them prominently — holding a swing position through \
earnings is a choice the trader must make deliberately.
- Be concrete: entry zone, stop, one or two targets, expected holding period.

Structure the note as markdown with these sections:
## <SYMBOL> — <one-line stance>
### Technical picture
### News & catalysts
### The setup  (or "Why there's no trade here")
### Risks

End with exactly one fenced ```json block (no prose after it):
{
  "symbol": "...",
  "stance": "long_setup" | "watch" | "avoid" | "short_setup",
  "conviction": 1-5,
  "entry_zone": [low, high] or null,
  "stop": number or null,
  "targets": [number, ...] or null,
  "horizon_days": number or null,
  "earnings_risk": "none_in_horizon" | "YYYY-MM-DD" | "unknown",
  "summary": "one sentence"
}
"""


class ConfigError(Exception):
    pass


class ResearchError(Exception):
    pass


def require_claude_cli() -> None:
    if not shutil.which("claude"):
        raise ConfigError(
            "the `claude` CLI is not on PATH. Research runs through Claude Code "
            "(billed to your Claude subscription, no API key): install it from "
            "https://claude.com/claude-code and sign in once with `claude login`."
        )


def _run_claude(prompt: str) -> tuple[str, dict]:
    """One headless research run; returns (note_text, {input, output} tokens)."""
    cmd = [
        "claude", "-p", prompt,
        "--system-prompt", SYSTEM_PROMPT,
        "--exclude-dynamic-system-prompt-sections",
        "--model", MODEL,
        "--allowedTools", "WebSearch", "WebFetch",
        "--output-format", "json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise ResearchError(detail[-1] if detail else f"claude exited {proc.returncode}")
    out = json.loads(proc.stdout)
    if out.get("is_error"):
        raise ResearchError(out.get("result") or out.get("subtype") or "unknown error")
    usage = out.get("usage") or {}
    return out.get("result") or "", {
        "input": usage.get("input_tokens", 0),
        "output": usage.get("output_tokens", 0),
    }


def _build_user_message(snap: dict, bars: list[dict], pos: dict | None = None) -> str:
    recent = bars[-15:]
    lines = ["date        open     high     low      close    volume"]
    for b in recent:
        lines.append(
            f"{b['date']}  {b['open']:<8.2f} {b['high']:<8.2f} "
            f"{b['low']:<8.2f} {b['close']:<8.2f} {b['volume']}"
        )
    position_block = ""
    if pos and pos["qty"]:
        position_block = (
            f"\n\nIMPORTANT — the trader ALREADY HOLDS {pos['qty']:g} shares at "
            f"average cost {pos['avg_cost']:.2f} (opened {pos['opened']}, "
            f"unrealized {pos['unrealized_pct']:+.1f}%, realized to date "
            f"{pos['realized_pnl']:+.2f}). Frame the note around managing this "
            "holding — hold, add, trim, or exit, with concrete levels — not a "
            "fresh entry. Map the JSON stance to the go-forward action: "
            "long_setup = add/hold with conviction, watch = hold with a defined "
            "stop, avoid = exit or reduce."
        )
    return (
        f"Research {snap['symbol']} for a swing trade as of {snap['date']}.\n\n"
        f"Indicator snapshot (computed from real daily data):\n"
        f"{json.dumps(snap, indent=2)}\n\n"
        f"Last 15 trading days:\n" + "\n".join(lines)
        + position_block + "\n\n"
        "Search the web for current news, upcoming earnings, and catalysts "
        "before forming the thesis."
    )


def _extract_verdict(text: str) -> dict | None:
    fences = re.findall(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not fences:
        return None
    try:
        return json.loads(fences[-1])
    except json.JSONDecodeError:
        return None


def research_symbols(symbols: list[str]) -> list[dict]:
    from . import data, indicators
    from . import trades as trades_mod

    trade_log = trades_mod.load()
    results = []
    for sym in symbols:
        print(f"Researching {sym} ...", flush=True)
        try:
            bars = data.fetch_daily(sym)
        except data.DataError as e:
            print(f"  ! {e}", file=sys.stderr)
            continue
        snap = indicators.snapshot(sym, bars)
        tlog = [t for t in trade_log if t["symbol"] == sym]
        pos = (trades_mod.enrich(trades_mod.position(sym, tlog),
                                 bars[-1]["close"], bars[-1]["date"])
               if tlog else None)
        try:
            text, usage = _run_claude(_build_user_message(snap, bars, pos))
        except (ResearchError, subprocess.TimeoutExpired,
                json.JSONDecodeError, OSError) as e:
            print(f"  ! {sym}: research failed — {e}", file=sys.stderr)
            continue

        verdict = _extract_verdict(text)
        if verdict is None:
            print(f"  ! {sym}: no parseable verdict block; keeping prose only", file=sys.stderr)
        results.append({
            "symbol": sym,
            "snapshot": snap,
            "note": text,
            "verdict": verdict,
            "usage": usage,
        })
    return results
