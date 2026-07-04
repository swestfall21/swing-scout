"""Claude analyst — per-symbol swing-trade research grounded in real data.

Each symbol gets one deep-research call: the deterministic indicator
snapshot and recent price action are provided as ground truth, and Claude
uses web search for news, catalysts, and upcoming earnings. The response is
a markdown research note ending in a machine-readable JSON verdict.
"""

import json
import os
import re
import sys

MODEL = "claude-opus-4-8"

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


def require_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise ConfigError(
            "ANTHROPIC_API_KEY is not set. Create a key at "
            "https://console.anthropic.com/settings/keys and either export it "
            "or put ANTHROPIC_API_KEY=sk-ant-... in a .env file next to ./scout"
        )


def _build_user_message(snap: dict, bars: list[dict]) -> str:
    recent = bars[-15:]
    lines = ["date        open     high     low      close    volume"]
    for b in recent:
        lines.append(
            f"{b['date']}  {b['open']:<8.2f} {b['high']:<8.2f} "
            f"{b['low']:<8.2f} {b['close']:<8.2f} {b['volume']}"
        )
    return (
        f"Research {snap['symbol']} for a swing trade as of {snap['date']}.\n\n"
        f"Indicator snapshot (computed from real daily data):\n"
        f"{json.dumps(snap, indent=2)}\n\n"
        f"Last 15 trading days:\n" + "\n".join(lines) + "\n\n"
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
    import anthropic

    from . import data, indicators

    client = anthropic.Anthropic()
    results = []
    for sym in symbols:
        print(f"Researching {sym} ...", flush=True)
        try:
            bars = data.fetch_daily(sym)
        except data.DataError as e:
            print(f"  ! {e}", file=sys.stderr)
            continue
        snap = indicators.snapshot(sym, bars)
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=16000,
                thinking={"type": "adaptive"},
                system=SYSTEM_PROMPT,
                tools=[{
                    "type": "web_search_20260209",
                    "name": "web_search",
                    "max_uses": 6,
                }],
                messages=[{"role": "user", "content": _build_user_message(snap, bars)}],
            ) as stream:
                message = stream.get_final_message()
        except anthropic.APIError as e:
            print(f"  ! {sym}: API error — {e}", file=sys.stderr)
            continue

        text = "\n".join(b.text for b in message.content if b.type == "text")
        verdict = _extract_verdict(text)
        if verdict is None:
            print(f"  ! {sym}: no parseable verdict block; keeping prose only", file=sys.stderr)
        usage = message.usage
        results.append({
            "symbol": sym,
            "snapshot": snap,
            "note": text,
            "verdict": verdict,
            "usage": {"input": usage.input_tokens, "output": usage.output_tokens},
        })
    return results
