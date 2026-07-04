"""Local web dashboard — stdlib HTTP server, no external dependencies.

GET  /                      the dashboard page
GET  /lightweight-charts.js vendored chart library
GET  /api/watchlist         ["NVDA", ...]
POST /api/watchlist         {"action": "add"|"remove", "symbol": "..."}
GET  /api/chart/<SYMBOL>    {bars, snapshot, levels, sma: {20,50,200}}
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import data, indicators
from . import watchlist as wl

WEB_DIR = Path(__file__).parent / "web"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet default logging
        pass

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
        path = self.path.split("?")[0]
        if path == "/":
            self._send(200, (WEB_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/lightweight-charts.js":
            self._send(200, (WEB_DIR / "lightweight-charts.js").read_bytes(),
                       "application/javascript")
        elif path == "/api/watchlist":
            self._json(wl.load())
        elif path.startswith("/api/chart/"):
            self._chart(path.removeprefix("/api/chart/"))
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path.split("?")[0] != "/api/watchlist":
            self._json({"error": "not found"}, 404)
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            symbol = wl.normalize(body["symbol"])
            action = body["action"]
        except (json.JSONDecodeError, KeyError, ValueError) as e:
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
        self._json({
            "symbol": symbol,
            "bars": [{"time": b["date"], **{k: b[k] for k in
                      ("open", "high", "low", "close", "volume")}} for b in bars],
            "snapshot": indicators.snapshot(symbol, bars),
            "levels": indicators.key_levels(bars),
            "sma": {str(n): indicators.sma_series(bars, n) for n in (20, 50, 200)},
        })


def serve(port: int = 8137) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Swing Scout dashboard: http://localhost:{port}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
