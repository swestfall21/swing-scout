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

`research` prints a ranked digest (long setups first, by conviction) and
writes the full markdown report to `reports/YYYY-MM-DD_HHMM.md`.

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
