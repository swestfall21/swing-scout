# Swing Scout — Build Checklist

A research copilot for swing trading: maintain a watchlist, pull real price
data, compute indicators deterministically, and have Claude produce
swing-trade research with entry/exit/stop levels. Stocks only — no options,
no broker connection, no order execution. Decided 2026-07-04.

- [x] 1. Scaffold — venv, anthropic SDK, package layout, `scout` CLI entry
- [x] 2. Watchlist — add/remove/list symbols, persisted to JSON
- [x] 3. Data layer — Yahoo Finance daily OHLCV fetch (no key needed),
      local cache, symbol validation
- [x] 4. Indicators — SMA 20/50/200, RSI(14), ATR(14), 52-week range
      position, volume trend, support/resistance from swing highs/lows,
      trend classification; `scout scan` prints the screen table (works
      without an API key)
- [x] 5. Claude analyst — per-symbol deep research (Opus 4.8 + web search):
      news/catalysts, swing thesis, entry zone / stop / targets / horizon,
      conviction score; graceful "no API key" handling
- [x] 6. Reports — markdown report per run in `reports/`, ranked digest
      across the watchlist; `scout research [SYMBOL]`
- [x] 7. Verify end-to-end (scan live w/ AAPL-MSFT-NVDA; research error paths + mocked report render — live research pending API key) — scan with real data; research live if an API
      key is available, otherwise verify prompt assembly + error path
- [x] 8. README — usage, API key setup, cost expectations, cron suggestion

Notes: PDT rules make sub-$25k accounts swing-trade naturally (days–weeks
holds), which is exactly the cadence this tool targets. If its calls look
good after months of use, a paper-trading execution arm can be a v2.

- [x] 9. Web dashboard — `./scout web` serves http://localhost:8137:
      candlestick chart (lightweight-charts v5, vendored) with SMA 20/50/200
      overlays, volume, dashed support/resistance level lines, stat tiles,
      add/remove symbols from the sidebar (validated against real data),
      3M/6M/1Y/2Y ranges, light + dark ✓ 2026-07-04, verified via headless
      screenshots in both modes, no console errors

- [x] 10. Dashboard setups panel — rule-based "Setups to watch — next
      session" card (`indicators.setups`): breakout watch, pullback to
      SMA 20/50, support bounce, breakdown watch, RSI extremes; badge per
      bias (LONG/CAUTION/WATCH), trigger + invalidation levels, honest
      empty state; `#SYMBOL` URL deep-link ✓ 2026-07-04, verified with
      headless screenshots (VRT caution case, AMZN empty case) in both
      modes

- [x] 11. Trade log & P&L — `scout buy/sell/trades/pnl`, fills persisted
      to `data/trades.json` (committed, hand-editable), FIFO lot
      accounting with realized/unrealized P&L, oversell rejected against
      log history; dashboard shows position/unrealized/realized tiles,
      AVG COST price line, B/S markers at fills; analyst prompt includes
      open-position context and shifts to hold/add/trim/exit framing
      ✓ 2026-07-04, verified via CLI run-through (FIFO math checked by
      hand) + headless screenshot

- [x] 12. Web trade entry — "Log fill" form on each symbol page
      (side/qty/price/date/note, blank date = today, price placeholder =
      last close) posting to `POST /api/trades`; inline success/error
      feedback, view refreshes tiles + markers after logging; oversell
      and missing-field errors surfaced from the same `trades.record`
      validation as the CLI ✓ 2026-07-04, API paths verified by curl,
      form rendering verified via headless screenshots light + dark

- [x] 13. Position plan card — `indicators.position_plan`: stance
      (hold / hold-with-line / caution / reduce, from trend vs SMA
      20/50/200) plus action levels (reassess stop = nearest support,
      hard stop = next support, add trigger snapped to resistance above
      the relevant MA, targets, P&L banked at hard stop); shown on held
      symbols, recomputed from the latest close on every page load
      ✓ 2026-07-04, all four stance branches exercised (AMZN/AAPL/VRT/
      MSFT/SPCX incl. no-history degradation), screenshots light + dark;
      trim zone (top resistance shelf → 52w high) + full-profit mark
      (zone + 1 ATR, drawn as TAKE PROFIT line) with % banked from cost
      added same day, degenerate at-the-highs case verified

- [x] 14. Entry read — `indicators.entry_read`: SETUP / WAIT / AVOID
      verdict card for non-held symbols (downtrend → avoid with the
      resistance-snapped reclaim level that flips it; actionable long
      setups → take-the-trigger with stop; uptrend-no-edge and
      range-bound → wait with the levels to wait for); shares the
      verdict-card renderer with the position plan ✓ 2026-07-04, all
      six non-held symbols verified, VRT/AAPL screenshots, AMZN plan
      card render byte-identical after refactor

- [x] 15. Cash ledger — `data/cash.json` deposits/withdrawals
      (`scout deposit/withdraw`, or click the sidebar account box);
      balance derived (deposits − withdrawals − buys + sells) so fills
      move cash automatically; date-aware validation (buys need funding,
      withdrawals need balance); `scout pnl` shows cash + account value;
      sidebar shows cash/positions/account; SETUP entry reads get a
      "cash covers N sh" chip and, when cash can't buy one share, a
      capital-recycling hint to trim the best winner into its trim zone
      ✓ 2026-07-04, seeded backfilled deposit ($2,732.95 → $1,600 today),
      validations + buy/sell cash flow exercised end-to-end and test
      entries removed, screenshot verified
