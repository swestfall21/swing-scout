"""Portfolio performance: the account equity curve and per-holding returns.

The account value series is cash + market value of open positions, sampled
on trading days (union of bar dates across every symbol ever traded, with
closes forward-filled across per-symbol gaps). Returns are time-weighted:
each day's return is computed net of that day's external cash flows
(deposits/withdrawals), then chained — so funding the account never shows
up as performance. Per-holding returns use the same math with the position
as the sub-account: its buys and sells are the external flows.

Flows dated on non-trading days count on the next trading day, matching how
fill markers snap on the chart. Everything is "as of" the last close in the
data — flows dated after it (e.g. a deposit that settles Monday) are not in
the window.
"""

import datetime as dt

from . import data, trades

RANGE_DAYS = {"1m": 30, "3m": 91, "6m": 182, "1y": 365}
RANGES = ("1m", "3m", "6m", "ytd", "1y", "all")


def window_start(range_key: str, first_activity: str, today: dt.date) -> str:
    if range_key == "all":
        return first_activity
    if range_key == "ytd":
        return dt.date(today.year, 1, 1).isoformat()
    return (today - dt.timedelta(days=RANGE_DAYS[range_key])).isoformat()


def _yahoo_range(start: str, today: dt.date) -> str:
    days = (today - dt.date.fromisoformat(start)).days + 7
    for cap, key in ((350, "1y"), (715, "2y"), (1800, "5y"), (3600, "10y")):
        if days <= cap:
            return key
    return "max"


def _forward_fill(bars: list[dict], dates: list[str]) -> list[float | None]:
    """Close for each date in `dates`, carrying the last close across gaps.
    None before the symbol's first bar."""
    out, i, last = [], 0, None
    for d in dates:
        while i < len(bars) and bars[i]["date"] <= d:
            last = bars[i]["close"]
            i += 1
        out.append(last)
    return out


def _qty_series(fills: list[dict], dates: list[str]) -> list[float]:
    """Open quantity as of each date's close (fills sorted date, id)."""
    out, i, qty = [], 0, 0.0
    for d in dates:
        while i < len(fills) and fills[i]["date"] <= d:
            qty += fills[i]["qty"] * (1 if fills[i]["side"] == "buy" else -1)
            i += 1
        out.append(qty)
    return out


def _flow_series(flows: list[tuple[str, float]], dates: list[str]) -> list[float]:
    """Net external flow attributed to each date: everything since the prior
    date (so weekend-dated flows land on the next trading day). Flows dated
    before the first date are folded into it — they're the opening balance."""
    out, i = [], 0
    flows = sorted(flows)
    for d in dates:
        f = 0.0
        while i < len(flows) and flows[i][0] <= d:
            f += flows[i][1]
            i += 1
        out.append(f)
    return out


def _twr_pnl(values: list[float], flows: list[float]) -> tuple[float | None, float]:
    """Chained time-weighted return (%) and net P&L ($) over aligned series."""
    growth, chained, pnl, prev = 1.0, False, 0.0, None
    for v, f in zip(values, flows):
        if prev is not None:
            pnl += v - prev - f
            if prev > 1e-9:
                growth *= (v - f) / prev
                chained = True
        prev = v
    return (round((growth - 1) * 100, 2) if chained else None), round(pnl, 2)


def build(range_key: str) -> dict:
    """Everything the portfolio view needs for one time window."""
    if range_key not in RANGES:
        raise ValueError(f"range must be one of {', '.join(RANGES)}")
    fills = sorted(trades.load(), key=lambda t: (t["date"], t["id"]))
    cash_flows = trades.load_cash()
    if not fills and not cash_flows:
        return {"range": range_key, "empty": True}

    today = dt.date.today()
    first_activity = min(x["date"] for x in fills + cash_flows)
    start = max(window_start(range_key, first_activity, today), first_activity)
    fetch_range = _yahoo_range(start, today)

    symbols = sorted({t["symbol"] for t in fills})
    bars_by_symbol, missing = {}, []
    for s in symbols:
        try:
            bars_by_symbol[s] = data.fetch_daily(s, range_=fetch_range)
        except data.DataError:
            missing.append(s)

    all_dates = sorted({b["date"] for bars in bars_by_symbol.values() for b in bars})
    # Keep one trading day before the window as the pct=0 baseline.
    i0 = next((i for i, d in enumerate(all_dates) if d >= start), len(all_dates))
    dates = all_dates[max(i0 - 1, 0):]
    if not dates:
        return {"range": range_key, "empty": True}

    prices = {s: _forward_fill(bars_by_symbol[s], dates) for s in bars_by_symbol}
    qtys = {s: _qty_series([t for t in fills if t["symbol"] == s], dates)
            for s in bars_by_symbol}
    # External flows for the *account* are deposits/withdrawals only; buys and
    # sells just move value between cash and stock.
    ext = _flow_series([(e["date"], e["amount"]) for e in cash_flows], dates)
    cash = _flow_series(
        [(e["date"], e["amount"]) for e in cash_flows]
        + [(t["date"], t["qty"] * t["price"] * (-1 if t["side"] == "buy" else 1))
           for t in fills],
        dates)
    for i in range(1, len(cash)):
        cash[i] += cash[i - 1]

    values = [c + sum(qtys[s][i] * (prices[s][i] or 0) for s in prices)
              for i, c in enumerate(cash)]
    deposits = list(ext)
    for i in range(1, len(deposits)):
        deposits[i] += deposits[i - 1]

    series, growth, chained = [], 1.0, False
    for i, d in enumerate(dates):
        if i and values[i - 1] > 1e-9:
            growth *= (values[i] - ext[i]) / values[i - 1]
            chained = True
        series.append({"t": d, "v": round(values[i], 2),
                       "p": round((growth - 1) * 100, 2) if chained else 0.0,
                       "d": round(deposits[i], 2)})
    _, window_pnl = _twr_pnl(values, ext)

    holdings = []
    for s in symbols:
        pos = trades.position(s, fills)
        if not pos["qty"]:
            continue
        if s not in bars_by_symbol:
            continue  # listed in `missing`
        pos = trades.enrich(pos, prices[s][-1], dates[-1])
        pvals = [qtys[s][i] * (prices[s][i] or 0) for i in range(len(dates))]
        pflows = _flow_series(
            [(t["date"], t["qty"] * t["price"] * (1 if t["side"] == "buy" else -1))
             for t in fills if t["symbol"] == s], dates)
        ret, pnl = _twr_pnl(pvals, pflows)
        pos["window_return_pct"] = ret
        pos["window_pnl"] = pnl
        holdings.append(pos)
    positions_value = sum(h["market_value"] for h in holdings)
    for h in holdings:
        h["weight_pct"] = (round(h["market_value"] / positions_value * 100, 1)
                           if positions_value else None)
    holdings.sort(key=lambda h: -h["market_value"])

    return {
        "range": range_key, "empty": False,
        "start": dates[0], "as_of": dates[-1],
        "series": series,
        "summary": {
            "account_value": series[-1]["v"],
            "cash": round(cash[-1], 2),
            "positions_value": round(positions_value, 2),
            "window_return_pct": series[-1]["p"] if chained else None,
            "window_pnl": window_pnl,
            "net_deposits": series[-1]["d"],
            "total_pnl": round(series[-1]["v"] - series[-1]["d"], 2),
        },
        "holdings": holdings,
        "missing": missing,
    }
