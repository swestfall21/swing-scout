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

    p_res = sub.add_parser("research", help="Claude deep research (whole watchlist, or named symbols)")
    p_res.add_argument("symbols", nargs="*")
    p_res.set_defaults(func=cmd_research)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
