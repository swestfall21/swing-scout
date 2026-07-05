"""Trade log persistence and P&L accounting.

Trades live in data/trades.json as a flat list of fills:
    {"id": 3, "date": "2026-05-12", "symbol": "VRT", "side": "buy",
     "qty": 10, "price": 250.0, "note": "breakout over 240"}

Positions are derived, never stored: buys stack FIFO lots, sells consume
them oldest-first, and realized P&L is the sum of (sell - lot cost) * qty
over consumed lots. Deleting or editing the JSON by hand is fine — ids only
need to be unique.

Cash lives in data/cash.json as deposits/withdrawals:
    {"id": 1, "date": "2024-07-14", "amount": 2732.95, "note": "funding"}
The balance is derived the same way: deposits − withdrawals − buys + sells.
Buys are validated against the balance on their date, so log deposits first.
"""

import datetime as dt
import json

from . import DATA_DIR
from . import watchlist as wl

TRADES_FILE = DATA_DIR / "trades.json"
CASH_FILE = DATA_DIR / "cash.json"


class TradeError(Exception):
    pass


def load() -> list[dict]:
    if not TRADES_FILE.exists():
        return []
    return json.loads(TRADES_FILE.read_text())


def save(trades: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    trades.sort(key=lambda t: (t["date"], t["id"]))
    TRADES_FILE.write_text(json.dumps(trades, indent=2) + "\n")


def _parse_date(raw: str | None) -> str:
    if raw is None:
        return dt.date.today().isoformat()
    try:
        return dt.date.fromisoformat(raw).isoformat()
    except ValueError:
        raise TradeError(f"{raw!r} is not a YYYY-MM-DD date")


def load_cash() -> list[dict]:
    if not CASH_FILE.exists():
        return []
    return json.loads(CASH_FILE.read_text())


def save_cash(entries: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    entries.sort(key=lambda e: (e["date"], e["id"]))
    CASH_FILE.write_text(json.dumps(entries, indent=2) + "\n")


def cash_balance(as_of: str | None = None) -> float:
    """Deposits − withdrawals − buys + sells, optionally as of a date."""
    fills = load()
    flows = load_cash()
    if as_of:
        fills = [t for t in fills if t["date"] <= as_of]
        flows = [e for e in flows if e["date"] <= as_of]
    bal = sum(e["amount"] for e in flows)
    for t in fills:
        bal += t["qty"] * t["price"] * (1 if t["side"] == "sell" else -1)
    return round(bal, 2)


def record_cash(amount: float, date: str | None = None, note: str = "") -> dict:
    """Log a deposit (positive) or withdrawal (negative)."""
    if not amount:
        raise TradeError("amount must be nonzero")
    date = _parse_date(date)
    if amount < 0 and cash_balance(as_of=date) + amount < -1e-6:
        raise TradeError(
            f"can't withdraw {-amount:.2f}: cash on {date} is "
            f"{cash_balance(as_of=date):.2f}")
    entries = load_cash()
    entry = {"id": max((e["id"] for e in entries), default=0) + 1,
             "date": date, "amount": round(amount, 2)}
    if note:
        entry["note"] = note
    entries.append(entry)
    save_cash(entries)
    return entry


def record(symbol: str, side: str, qty: float, price: float,
           date: str | None = None, note: str = "") -> dict:
    """Validate and append one fill; returns the stored trade."""
    symbol = wl.normalize(symbol)
    if side not in ("buy", "sell"):
        raise TradeError(f"side must be buy or sell, not {side!r}")
    if qty <= 0:
        raise TradeError("qty must be positive")
    if price <= 0:
        raise TradeError("price must be positive")
    date = _parse_date(date)

    trades = load()
    if side == "sell":
        held = position(symbol, [t for t in trades if t["date"] <= date])["qty"]
        if qty > held + 1e-9:
            raise TradeError(
                f"can't sell {qty:g} {symbol}: only {held:g} held on {date} "
                "per the trade log (log the buy first?)")
    else:
        bal = cash_balance(as_of=date)
        if qty * price > bal + 1e-6:
            raise TradeError(
                f"buy costs {qty * price:.2f} but cash on {date} is {bal:.2f} "
                "— log the funding first (./scout deposit AMOUNT [DATE])")

    trade = {
        "id": max((t["id"] for t in trades), default=0) + 1,
        "date": date, "symbol": symbol, "side": side,
        "qty": qty, "price": price,
    }
    if note:
        trade["note"] = note
    trades.append(trade)
    save(trades)
    return trade


def position(symbol: str, trades: list[dict] | None = None) -> dict:
    """FIFO position for one symbol: open qty/avg cost plus realized P&L."""
    if trades is None:
        trades = load()
    fills = sorted((t for t in trades if t["symbol"] == symbol),
                   key=lambda t: (t["date"], t["id"]))
    lots: list[dict] = []  # {"qty", "price", "date"}
    realized = 0.0
    first_open: str | None = None
    for t in fills:
        if t["side"] == "buy":
            lots.append({"qty": t["qty"], "price": t["price"], "date": t["date"]})
            if first_open is None:
                first_open = t["date"]
        else:
            remaining = t["qty"]
            while remaining > 1e-9 and lots:
                lot = lots[0]
                take = min(lot["qty"], remaining)
                realized += (t["price"] - lot["price"]) * take
                lot["qty"] -= take
                remaining -= take
                if lot["qty"] <= 1e-9:
                    lots.pop(0)
            if not lots:
                first_open = None
    qty = sum(l["qty"] for l in lots)
    cost = sum(l["qty"] * l["price"] for l in lots)
    return {
        "symbol": symbol,
        "qty": round(qty, 6),
        "avg_cost": round(cost / qty, 4) if qty else None,
        "cost_basis": round(cost, 2),
        "realized_pnl": round(realized, 2),
        "opened": first_open if qty else None,
        "trades": len(fills),
    }


def portfolio(trades: list[dict] | None = None) -> list[dict]:
    """Position summaries for every symbol that appears in the log."""
    if trades is None:
        trades = load()
    symbols = sorted({t["symbol"] for t in trades})
    return [position(s, trades) for s in symbols]


def enrich(pos: dict, last_price: float, as_of: str) -> dict:
    """Add market-value / unrealized fields to a position() dict."""
    out = dict(pos)
    out["last_price"] = last_price
    out["as_of"] = as_of
    if pos["qty"]:
        mv = pos["qty"] * last_price
        out["market_value"] = round(mv, 2)
        out["unrealized_pnl"] = round(mv - pos["cost_basis"], 2)
        out["unrealized_pct"] = round((mv / pos["cost_basis"] - 1) * 100, 2)
    else:
        out["market_value"] = 0.0
        out["unrealized_pnl"] = None
        out["unrealized_pct"] = None
    return out
