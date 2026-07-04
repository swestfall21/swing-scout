"""Daily OHLCV data from Yahoo Finance's chart API (no API key required).

Bars are cached per symbol per calendar day under data/cache/ so repeated
scans within a day don't re-hit the network.
"""

import datetime as dt
import json
import urllib.error
import urllib.request

from . import CACHE_DIR

_UA = "Mozilla/5.0 (X11; Linux x86_64) swing-scout/1.0"
_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?range={range}&interval=1d"


class DataError(Exception):
    pass


def fetch_daily(symbol: str, range_: str = "1y") -> list[dict]:
    """Return daily bars: [{date, open, high, low, close, volume}, ...] oldest first."""
    cached = _cache_read(symbol, range_)
    if cached is not None:
        return cached

    url = _CHART_URL.format(symbol=urllib.request.quote(symbol), range=range_)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise DataError(f"{symbol}: unknown symbol (Yahoo returned 404)") from e
        raise DataError(f"{symbol}: Yahoo Finance HTTP {e.code}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise DataError(f"{symbol}: network error fetching data ({e})") from e

    chart = payload.get("chart", {})
    if chart.get("error"):
        raise DataError(f"{symbol}: {chart['error'].get('description', 'Yahoo error')}")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise DataError(f"{symbol}: no data returned")

    timestamps = result.get("timestamp") or []
    quote = result["indicators"]["quote"][0]
    bars = []
    for i, ts in enumerate(timestamps):
        o, h, l, c, v = (quote[k][i] for k in ("open", "high", "low", "close", "volume"))
        if None in (o, h, l, c):
            continue  # halted/partial days come through as nulls
        bars.append({
            "date": dt.date.fromtimestamp(ts).isoformat(),
            "open": round(o, 4), "high": round(h, 4),
            "low": round(l, 4), "close": round(c, 4),
            "volume": int(v or 0),
        })
    # Recent IPOs are allowed with a short history — indicators that need a
    # longer window (SMA50/200, RSI, ATR) degrade to "-" until it accrues.
    if len(bars) < 10:
        raise DataError(f"{symbol}: only {len(bars)} bars of history — too new to chart")

    _cache_write(symbol, range_, bars)
    return bars


def _cache_path(symbol: str, range_: str):
    return CACHE_DIR / f"{symbol}_{range_}_{dt.date.today().isoformat()}.json"


def _cache_read(symbol: str, range_: str):
    path = _cache_path(symbol, range_)
    if path.exists():
        return json.loads(path.read_text())
    return None


def _cache_write(symbol: str, range_: str, bars: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Drop stale cache files for this symbol from earlier days.
    for old in CACHE_DIR.glob(f"{symbol}_{range_}_*.json"):
        old.unlink()
    _cache_path(symbol, range_).write_text(json.dumps(bars))
