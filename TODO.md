# Swing Scout — Build Checklist

A research copilot for swing trading: maintain a watchlist, pull real price
data, compute indicators deterministically, and have Claude produce
swing-trade research with entry/exit/stop levels. Stocks only — no options,
no broker connection, no order execution. Decided 2026-07-04.

- [ ] 1. Scaffold — venv, anthropic SDK, package layout, `scout` CLI entry
- [ ] 2. Watchlist — add/remove/list symbols, persisted to JSON
- [ ] 3. Data layer — Yahoo Finance daily OHLCV fetch (no key needed),
      local cache, symbol validation
- [ ] 4. Indicators — SMA 20/50/200, RSI(14), ATR(14), 52-week range
      position, volume trend, support/resistance from swing highs/lows,
      trend classification; `scout scan` prints the screen table (works
      without an API key)
- [ ] 5. Claude analyst — per-symbol deep research (Opus 4.8 + web search):
      news/catalysts, swing thesis, entry zone / stop / targets / horizon,
      conviction score; graceful "no API key" handling
- [ ] 6. Reports — markdown report per run in `reports/`, ranked digest
      across the watchlist; `scout research [SYMBOL]`
- [ ] 7. Verify end-to-end — scan with real data; research live if an API
      key is available, otherwise verify prompt assembly + error path
- [ ] 8. README — usage, API key setup, cost expectations, cron suggestion

Notes: PDT rules make sub-$25k accounts swing-trade naturally (days–weeks
holds), which is exactly the cadence this tool targets. If its calls look
good after months of use, a paper-trading execution arm can be a v2.
