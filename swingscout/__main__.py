"""Swing Scout CLI."""

import argparse
import sys

from . import load_env
from . import watchlist as wl


def cmd_add(args) -> int:
    added, present = wl.add(args.symbols)
    if added:
        print("Added:", ", ".join(added))
    if present:
        print("Already on watchlist:", ", ".join(present))
    return 0


def cmd_remove(args) -> int:
    removed, missing = wl.remove(args.symbols)
    if removed:
        print("Removed:", ", ".join(removed))
    if missing:
        print("Not on watchlist:", ", ".join(missing))
    return 0


def cmd_list(_args) -> int:
    symbols = wl.load()
    if not symbols:
        print("Watchlist is empty. Add symbols with:  ./scout add AAPL MSFT")
        return 0
    print("\n".join(symbols))
    return 0


def cmd_scan(_args) -> int:
    from . import data, indicators

    symbols = wl.load()
    if not symbols:
        print("Watchlist is empty. Add symbols with:  ./scout add AAPL MSFT")
        return 1

    cols = [
        ("SYMBOL", "symbol", "{}"), ("PRICE", "price", "{:.2f}"),
        ("5D%", "change_5d_pct", "{:+.1f}"), ("20D%", "change_20d_pct", "{:+.1f}"),
        ("TREND", "trend", "{}"), ("RSI", "rsi14", "{:.0f}"),
        ("ATR%", "atr_pct", "{:.1f}"), ("OFF-HI%", "off_year_high_pct", "{:+.1f}"),
        ("SUPPORT", "support", "{:.2f}"), ("RESIST", "resistance", "{:.2f}"),
        ("VOL20/60", "volume_ratio_20d_60d", "{:.2f}"),
    ]
    rows = []
    for sym in symbols:
        try:
            snap = indicators.snapshot(sym, data.fetch_daily(sym))
        except data.DataError as e:
            print(f"  ! {e}", file=sys.stderr)
            continue
        rows.append([
            fmt.format(snap[key]) if snap[key] is not None else "-"
            for _, key, fmt in cols
        ])

    if not rows:
        print("No data for any watchlist symbol.", file=sys.stderr)
        return 1
    headers = [h for h, _, _ in cols]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    print("  ".join(h.rjust(w) for h, w in zip(headers, widths)))
    for r in rows:
        print("  ".join(cell.rjust(w) for cell, w in zip(r, widths)))
    return 0


def _cmd_trade(args, side: str) -> int:
    from . import trades

    try:
        t = trades.record(args.symbol, side, args.qty, args.price,
                          date=args.date, note=args.note or "")
    except (trades.TradeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    pos = trades.position(t["symbol"])
    print(f"Logged: {t['date']} {side} {t['qty']:g} {t['symbol']} @ {t['price']:.2f}")
    if pos["qty"]:
        print(f"Position: {pos['qty']:g} @ avg {pos['avg_cost']:.2f}"
              f"  (realized so far {pos['realized_pnl']:+.2f})")
    else:
        print(f"Position closed. Realized P&L: {pos['realized_pnl']:+.2f}")
    return 0


def cmd_buy(args) -> int:
    return _cmd_trade(args, "buy")


def cmd_sell(args) -> int:
    return _cmd_trade(args, "sell")


def _cmd_cash(args, sign: int) -> int:
    from . import trades

    try:
        e = trades.record_cash(sign * abs(args.amount), date=args.date,
                               note=args.note or "")
    except trades.TradeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    verb = "Deposited" if e["amount"] > 0 else "Withdrew"
    print(f"{verb} {abs(e['amount']):.2f} on {e['date']}. "
          f"Cash on hand: {trades.cash_balance():.2f}")
    return 0


def cmd_deposit(args) -> int:
    return _cmd_cash(args, +1)


def cmd_withdraw(args) -> int:
    return _cmd_cash(args, -1)


def cmd_trades(args) -> int:
    from . import trades, watchlist

    log = trades.load()
    if args.symbol:
        sym = watchlist.normalize(args.symbol)
        log = [t for t in log if t["symbol"] == sym]
    if not log:
        print("No trades logged yet. Log one with:  ./scout buy VRT 10 250.00 2026-05-12")
        return 0
    for t in log:
        note = f"  # {t['note']}" if t.get("note") else ""
        print(f"{t['date']}  {t['side']:<4} {t['qty']:>8g}  {t['symbol']:<6} "
              f"@ {t['price']:>9.2f}{note}")
    return 0


def cmd_pnl(_args) -> int:
    from . import data, trades

    book = trades.portfolio()
    if not book:
        print("No trades logged yet. Log one with:  ./scout buy VRT 10 250.00 2026-05-12")
        return 0
    rows, tot_real, tot_unreal, tot_mv = [], 0.0, 0.0, 0.0
    for pos in book:
        tot_real += pos["realized_pnl"]
        if not pos["qty"]:
            rows.append([pos["symbol"], "closed", "-", "-", "-", "-",
                         f"{pos['realized_pnl']:+.2f}"])
            continue
        try:
            bars = data.fetch_daily(pos["symbol"])
            pos = trades.enrich(pos, bars[-1]["close"], bars[-1]["date"])
        except data.DataError as e:
            print(f"  ! {e}", file=sys.stderr)
            rows.append([pos["symbol"], f"{pos['qty']:g}", f"{pos['avg_cost']:.2f}",
                         "-", "-", "-", f"{pos['realized_pnl']:+.2f}"])
            continue
        tot_unreal += pos["unrealized_pnl"] or 0.0
        tot_mv += pos["market_value"]
        rows.append([
            pos["symbol"], f"{pos['qty']:g}", f"{pos['avg_cost']:.2f}",
            f"{pos.get('last_price') or 0:.2f}", f"{pos['market_value']:.2f}",
            f"{pos['unrealized_pnl']:+.2f} ({pos['unrealized_pct']:+.1f}%)"
            if pos["unrealized_pnl"] is not None else "-",
            f"{pos['realized_pnl']:+.2f}",
        ])
    headers = ["SYMBOL", "QTY", "AVG COST", "LAST", "MKT VALUE", "UNREALIZED", "REALIZED"]
    widths = [max(len(h), *(len(r[i]) for r in rows)) for i, h in enumerate(headers)]
    print("  ".join(h.rjust(w) for h, w in zip(headers, widths)))
    for r in rows:
        print("  ".join(cell.rjust(w) for cell, w in zip(r, widths)))
    cash = trades.cash_balance()
    print(f"\nOpen market value {tot_mv:.2f} · unrealized {tot_unreal:+.2f}"
          f" · realized {tot_real:+.2f}")
    print(f"Cash on hand {cash:.2f} · account value {cash + tot_mv:.2f}")
    return 0


def cmd_research(args) -> int:
    from . import analyst, report

    symbols = [wl.normalize(s) for s in args.symbols] or wl.load()
    if not symbols:
        print("Watchlist is empty. Add symbols with:  ./scout add AAPL MSFT")
        return 1
    try:
        analyst.require_api_key()
    except analyst.ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    results = analyst.research_symbols(symbols)
    if not results:
        print("No research produced.", file=sys.stderr)
        return 1
    path = report.write_report(results)
    print()
    print(report.digest_text(results))
    print(f"\nFull report: {path}")
    return 0


def cmd_web(args) -> int:
    from . import webapp

    webapp.serve(port=args.port)
    return 0


def main() -> int:
    load_env()
    parser = argparse.ArgumentParser(
        prog="scout",
        description="Swing Scout — watchlist research copilot for swing trading.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="add symbols to the watchlist")
    p_add.add_argument("symbols", nargs="+")
    p_add.set_defaults(func=cmd_add)

    p_rm = sub.add_parser("remove", help="remove symbols from the watchlist")
    p_rm.add_argument("symbols", nargs="+")
    p_rm.set_defaults(func=cmd_remove)

    p_ls = sub.add_parser("list", help="show the watchlist")
    p_ls.set_defaults(func=cmd_list)

    p_scan = sub.add_parser("scan", help="indicator screen for the watchlist (no API key needed)")
    p_scan.set_defaults(func=cmd_scan)

    for side, blurb in (("buy", "log a buy fill"), ("sell", "log a sell fill")):
        p_t = sub.add_parser(side, help=f"{blurb} (date defaults to today)")
        p_t.add_argument("symbol")
        p_t.add_argument("qty", type=float)
        p_t.add_argument("price", type=float)
        p_t.add_argument("date", nargs="?", help="YYYY-MM-DD, default today")
        p_t.add_argument("--note", help="why you took the trade")
        p_t.set_defaults(func=cmd_buy if side == "buy" else cmd_sell)

    for verb, blurb, fn in (("deposit", "add cash to the account", cmd_deposit),
                            ("withdraw", "take cash out of the account", cmd_withdraw)):
        p_c = sub.add_parser(verb, help=f"{blurb} (date defaults to today)")
        p_c.add_argument("amount", type=float)
        p_c.add_argument("date", nargs="?", help="YYYY-MM-DD, default today")
        p_c.add_argument("--note")
        p_c.set_defaults(func=fn)

    p_tr = sub.add_parser("trades", help="show the trade log")
    p_tr.add_argument("symbol", nargs="?")
    p_tr.set_defaults(func=cmd_trades)

    p_pnl = sub.add_parser("pnl", help="positions with unrealized/realized P&L")
    p_pnl.set_defaults(func=cmd_pnl)

    p_res = sub.add_parser("research", help="Claude deep research (whole watchlist, or named symbols)")
    p_res.add_argument("symbols", nargs="*")
    p_res.set_defaults(func=cmd_research)

    p_web = sub.add_parser("web", help="local chart dashboard at http://localhost:8137")
    p_web.add_argument("--port", type=int, default=8137)
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
