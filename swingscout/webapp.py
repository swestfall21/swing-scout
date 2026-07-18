"""Local web dashboard — stdlib HTTP server, no external dependencies.

GET  /                      the dashboard page
GET  /lightweight-charts.js vendored chart library
GET  /api/watchlist         ["NVDA", ...]
POST /api/watchlist         {"action": "add"|"remove", "symbol": "..."}
POST /api/trades            {"symbol", "side", "qty", "price", "date"?, "note"?}
GET  /api/chart/<SYMBOL>    {bars, snapshot, levels, sma, setups, position, trades, ...}
GET  /api/account           {cash, positions_value, account_value}
GET  /api/performance?range=1m|3m|6m|ytd|1y|all   equity curve + holdings returns
POST /api/cash              {"amount": +deposit/-withdrawal, "date"?, "note"?}
"""

import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import data, indicators, performance, trades
from . import watchlist as wl

WEB_DIR = Path(__file__).parent / "web"

# The server only listens on 127.0.0.1, but the *browser* will happily reach
# it on behalf of any website (DNS rebinding for reads, cross-site form POSTs
# for writes). Requests must be addressed to us and, when a browser says where
# they came from, they must come from our own page.
ALLOWED_HOSTS = ("localhost", "127.0.0.1")
MAX_BODY_BYTES = 1_000_000  # API bodies are tiny JSON; anything big is abuse


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet default logging
        pass

    def _cross_site_blocked(self) -> bool:
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ALLOWED_HOSTS:
            self._json({"error": "forbidden host"}, 403)
            return True
        origin = self.headers.get("Origin")
        if origin and self.command == "POST":
            if urllib.parse.urlparse(origin).hostname not in ALLOWED_HOSTS:
                self._json({"error": "forbidden origin"}, 403)
                return True
        return False

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, status: int = 200) -> None:
        self._send(status, json.dumps(obj).encode(), "application/json")

    def do_GET(self):
        if self._cross_site_blocked():
            return
        path = self.path.split("?")[0]
        if path == "/":
            self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/lightweight-charts.js":
            self._send(200, (WEB_DIR / "lightweight-charts.js").read_bytes(),
                       "application/javascript")
        elif path == "/api/watchlist":
            self._json(wl.load())
        elif path == "/api/account":
            self._json(_account_summary())
        elif path == "/api/performance":
            self._performance()
        elif path.startswith("/api/chart/"):
            self._chart(path.removeprefix("/api/chart/"))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self._cross_site_blocked():
            return
        path = self.path.split("?")[0]
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._json({"error": "bad Content-Length"}, 400)
            return
        if not 0 <= length <= MAX_BODY_BYTES:
            self._json({"error": "body too large"}, 413)
            return
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as e:
            self._json({"error": str(e)}, 400)
            return
        if path == "/api/watchlist":
            self._watchlist_post(body)
        elif path == "/api/trades":
            self._trades_post(body)
        elif path == "/api/cash":
            self._cash_post(body)
        else:
            self._json({"error": "not found"}, 404)

    def _watchlist_post(self, body: dict):
        try:
            symbol = wl.normalize(body["symbol"])
            action = body["action"]
        except (KeyError, ValueError) as e:
            self._json({"error": str(e)}, 400)
            return
        if action == "add":
            # Validate against real data before accepting, so typos bounce.
            try:
                data.fetch_daily(symbol)
            except data.DataError as e:
                self._json({"error": str(e)}, 400)
                return
            wl.add([symbol])
        elif action == "remove":
            wl.remove([symbol])
        else:
            self._json({"error": f"unknown action {action!r}"}, 400)
            return
        self._json(wl.load())

    def _trades_post(self, body: dict):
        try:
            trade = trades.record(
                body["symbol"], body["side"],
                float(body["qty"]), float(body["price"]),
                date=body.get("date") or None,
                note=(body.get("note") or "").strip(),
            )
        except KeyError as e:
            self._json({"error": f"missing field {e}"}, 400)
            return
        except (trades.TradeError, ValueError, TypeError) as e:
            self._json({"error": str(e)}, 400)
            return
        self._json({"ok": True, "trade": trade})

    def _cash_post(self, body: dict):
        try:
            entry = trades.record_cash(
                float(body["amount"]), date=body.get("date") or None,
                note=(body.get("note") or "").strip())
        except KeyError as e:
            self._json({"error": f"missing field {e}"}, 400)
            return
        except (trades.TradeError, ValueError, TypeError) as e:
            self._json({"error": str(e)}, 400)
            return
        self._json({"ok": True, "entry": entry, "account": _account_summary()})

    def _performance(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        range_key = (query.get("range") or ["all"])[0].lower()
        try:
            self._json(performance.build(range_key))
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except data.DataError as e:
            self._json({"error": str(e)}, 502)

    def _chart(self, raw_symbol: str):
        try:
            symbol = wl.normalize(raw_symbol)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
            return
        try:
            # 2y of data so SMA200 has history across the whole visible year.
            bars = data.fetch_daily(symbol, range_="2y")
        except data.DataError as e:
            self._json({"error": str(e)}, 502)
            return
        snap = indicators.snapshot(symbol, bars)
        levels = indicators.key_levels(bars)
        setup_list = indicators.setups(snap, levels, bars)
        tlog = [t for t in trades.load() if t["symbol"] == symbol]
        pos = (trades.enrich(trades.position(symbol, tlog),
                             bars[-1]["close"], bars[-1]["date"])
               if tlog else None)
        plan = indicators.position_plan(snap, levels, pos)
        entry = None if plan else indicators.entry_read(snap, levels, setup_list)
        if entry and entry["stance"] == "setup":
            _add_funding_context(entry, snap["price"])
        self._json({
            "symbol": symbol,
            "bars": [{"time": b["date"], **{k: b[k] for k in
                      ("open", "high", "low", "close", "volume")}} for b in bars],
            "snapshot": snap,
            "levels": levels,
            "sma": {str(n): indicators.sma_series(bars, n) for n in (20, 50, 200)},
            "setups": setup_list,
            "position": pos,
            "trades": tlog,
            "plan": plan,
            "entry": entry,
            "account": _account_summary(),
        })


def _held_positions() -> list[dict]:
    """Open positions enriched with last cached price; skips fetch failures."""
    out = []
    for p in trades.portfolio():
        if not p["qty"]:
            continue
        try:
            bars = data.fetch_daily(p["symbol"])
        except data.DataError:
            continue
        out.append(trades.enrich(p, bars[-1]["close"], bars[-1]["date"]))
    return out


def _account_summary() -> dict:
    cash = trades.cash_balance()
    mv = sum(p["market_value"] for p in _held_positions())
    return {"cash": round(cash, 2), "positions_value": round(mv, 2),
            "account_value": round(cash + mv, 2),
            "held": [p["symbol"] for p in trades.portfolio() if p["qty"]]}


def _add_funding_context(entry: dict, price: float) -> None:
    """Attach cash/affordability to a SETUP entry read; when cash can't buy
    a single share, point at the best winner as the capital-recycling trim
    (sell strength at structure, don't deposit to chase)."""
    cash = trades.cash_balance()
    entry["cash"] = round(cash, 2)
    entry["affordable_shares"] = int(cash // price) if price else 0
    # Risk-based size: most shares whose loss at the stop stays within 2% of
    # account value (cash + open positions). Governs sizing; "affordable" is
    # just raw cash reach and is usually the looser of the two.
    acct = cash + sum(p["market_value"] for p in _held_positions())
    trig, stop = entry.get("entry_if_triggered"), entry.get("stop_if_triggered")
    if trig and stop and trig > stop:
        entry["risk_max_shares"] = int(0.02 * acct // (trig - stop))
    if entry["affordable_shares"] >= 1:
        return
    winners = [p for p in _held_positions() if (p["unrealized_pct"] or 0) >= 10]
    if winners:
        w = max(winners, key=lambda p: p["unrealized_pct"])
        entry["funding_hint"] = (
            f"Cash (${cash:,.2f}) doesn't cover a single share. Rather than "
            f"depositing to chase, the capital-recycling move is trimming "
            f"{w['symbol']} ({w['unrealized_pct']:+.1f}% winner) — ideally "
            "into its trim zone, not at market.")


def serve(port: int = 8137) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Swing Scout dashboard: http://localhost:{port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
