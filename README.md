# Swing Scout

A research copilot for swing trading. You keep a watchlist; it pulls real
daily price data, computes the technical picture deterministically, and has
Claude write risk-first research notes — entry zone, stop, targets, earnings
risk — ranked across your list. **It never trades**: no broker connection,
no orders, no options. It just makes you a better-informed swing trader.

## Setup

Already done on this machine (venv lives in `.venv/`). The only thing the
deep-research command needs is an Anthropic API key:

1. Create a key at <https://console.anthropic.com/settings/keys>
2. Put it in a `.env` file next to `./scout`:

       ANTHROPIC_API_KEY=sk-ant-...

`scan` works without any key.

## Usage

    ./scout add AAPL MSFT NVDA     # build your watchlist
    ./scout remove MSFT
    ./scout list

    ./scout scan                   # free, instant: indicator screen table
    ./scout web                    # local chart dashboard at http://localhost:8137
    ./scout research               # Claude deep research, whole watchlist
    ./scout research NVDA          # ... or just the symbols you name

    ./scout buy VRT 10 250.00 2026-04-15 --note "breakout"   # log a fill
    ./scout sell VRT 5 320.00 2026-06-20                     # date defaults to today
    ./scout trades [VRT]           # the trade log
    ./scout pnl                    # positions, P&L, cash, account value
    ./scout deposit 500 [DATE]     # add trading cash (data/cash.json)
    ./scout withdraw 200 [DATE]

`research` prints a ranked digest (long setups first, by conviction) and
writes the full markdown report to `reports/YYYY-MM-DD_HHMM.md`.

The dashboard shows candles with SMA 20/50/200 overlays, volume, dashed
support/resistance lines, stat tiles, and a rule-based **"Setups to watch —
next session"** panel (breakout / pullback / support-bounce / breakdown
geometry from the latest close — free and deterministic, no API key; the
Claude analyst remains the opinionated layer). `#SYMBOL` in the URL
deep-links a symbol.

## Trade log

Log fills from the CLI (above) or straight from the dashboard — each
symbol page has a "Log fill" row (side, qty, price, date, note; price
placeholder shows the last close, blank date means today).

Fills live in `data/trades.json` (plain JSON, safe to hand-edit;
gitignored along with the watchlist and cash ledger — see
`data/*.example.json` for the formats). Positions are derived FIFO: buys stack lots, sells consume
the oldest first. Symbols you hold get extra dashboard tiles (position,
unrealized, realized), an AVG COST line, and B/S arrows on the chart at
each fill. When a researched symbol has an open position, the analyst is
told about it and frames the note around managing the holding
(hold / add / trim / exit) instead of a fresh entry.

Held symbols also get a **Position plan** card, recomputed from each day's
close on every page load: a stance (HOLD / CAUTION / REDUCE from trend vs.
the 20/50/200-day averages) with the levels that should trigger action —
reassess stop, hard stop, add trigger, targets, a trim zone (highest
overhead resistance up to the 52-week high, for selling part into
strength), a full-profit mark one ATR past that zone (drawn on the chart
as a TAKE PROFIT line), and the P&L banked at each. Chart math only; pair
it with `scout research` for the news-aware version.

Symbols you *don't* hold get an **Entry read** verdict instead: SETUP
(take the flagged trigger, sized to risk 1–2%), WAIT (right trend wrong
price, or no trend at all), or AVOID (downtrend — includes the reclaim
level that would flip the verdict).

## Cash

Deposits/withdrawals live in `data/cash.json`; the balance is derived
(deposits − withdrawals − buys + sells), so logging a fill moves cash
automatically. Buys are validated against the balance on their date —
log the funding first. The dashboard sidebar shows cash / positions /
account value (click it to deposit or withdraw), SETUP entry reads show
how many shares cash covers, and when cash can't cover a single share
the card suggests the capital-recycling move: trim your best winner into
its trim zone rather than depositing to chase.

## What the analyst gets and does

- **Ground truth from real data** (Yahoo Finance daily bars, cached per
  day): SMA 20/50/200, RSI(14), ATR(14), 52-week range position,
  swing-level support/resistance, volume trend, last 15 sessions of OHLCV.
- **Web search** for what price data can't tell you: news, catalysts,
  upcoming earnings dates, analyst moves.
- **Risk-first instructions**: every setup needs a stop; "watch" and
  "avoid" are encouraged answers; binary events (earnings inside the hold
  window) get flagged with a ⚠ in the digest.

## Costs

`scan` is free. `research` uses Claude Opus with web search — typically
roughly $0.10–$0.30 per symbol per run (varies with news volume). Each
report footer shows actual token usage. A 5-symbol watchlist researched
twice a week lands around $5–15/month.

## Suggested rhythm

- `scan` any time — it's free. Sort out what's trending, what's oversold.
- `research` on Sunday evening (plan the week) and midweek if something
  moved. Cron example (Mon 7am market prep):

      0 7 * * 1 cd ~/Claude/Projects/swing-scout && ./scout research >> logs/cron.log 2>&1

## Honest limitations

This is decision support, not alpha. Claude reasons well about the data and
news it's given, but nothing here predicts prices. Judge it like an analyst:
keep the reports, check the calls after a month, and only weight its
conviction scores as much as its track record has earned. If the calls prove
consistently useful, a paper-trading execution arm is a sensible v2.
