"""Deterministic technical indicators computed from daily bars.

Everything here is plain math on OHLCV — no network, no LLM. The snapshot
this module produces is both the `scan` table and the grounding data handed
to the Claude analyst so it reasons from real numbers instead of memory.
"""


def sma(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def rsi14(closes: list[float]) -> float | None:
    """Wilder-smoothed RSI over 14 periods."""
    n = 14
    if len(closes) < n + 1:
        return None
    gains, losses = [], []
    for prev, cur in zip(closes[:-1], closes[1:]):
        change = cur - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:n]) / n
    avg_loss = sum(losses[:n]) / n
    for g, l in zip(gains[n:], losses[n:]):
        avg_gain = (avg_gain * (n - 1) + g) / n
        avg_loss = (avg_loss * (n - 1) + l) / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def atr14(bars: list[dict]) -> float | None:
    """Wilder-smoothed average true range over 14 periods."""
    n = 14
    if len(bars) < n + 1:
        return None
    trs = []
    for prev, cur in zip(bars[:-1], bars[1:]):
        trs.append(max(
            cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]),
        ))
    atr = sum(trs[:n]) / n
    for tr in trs[n:]:
        atr = (atr * (n - 1) + tr) / n
    return atr


def swing_levels(bars: list[dict], lookback: int = 120, wing: int = 3) -> tuple[list[float], list[float]]:
    """Local swing highs/lows: a bar whose high/low is the extreme of its ±wing window."""
    window = bars[-lookback:]
    highs, lows = [], []
    for i in range(wing, len(window) - wing):
        segment = window[i - wing:i + wing + 1]
        if window[i]["high"] == max(b["high"] for b in segment):
            highs.append(window[i]["high"])
        if window[i]["low"] == min(b["low"] for b in segment):
            lows.append(window[i]["low"])
    return highs, lows


def key_levels(bars: list[dict], max_each: int = 3) -> dict:
    """Support/resistance levels for charting: swing levels below/above the
    current price, deduped so levels closer than half an ATR merge (keeping
    the one touched most recently)."""
    price = bars[-1]["close"]
    atr = atr14(bars) or price * 0.02
    highs, lows = swing_levels(bars)

    def dedupe(levels: list[float]) -> list[float]:
        out: list[float] = []
        for lvl in levels:  # iterate most-recent-last; later touches win
            out = [k for k in out if abs(k - lvl) > atr / 2]
            out.append(lvl)
        return out

    supports = sorted(dedupe([l for l in lows if l < price]), reverse=True)[:max_each]
    resistances = sorted(dedupe([h for h in highs if h > price]))[:max_each]
    return {
        "support": [round(s, 2) for s in supports],
        "resistance": [round(r, 2) for r in resistances],
    }


def sma_series(bars: list[dict], n: int) -> list[dict]:
    """Rolling SMA aligned to bar dates, for chart overlays."""
    closes = [b["close"] for b in bars]
    out = []
    running = 0.0
    for i, b in enumerate(bars):
        running += closes[i]
        if i >= n:
            running -= closes[i - n]
        if i >= n - 1:
            out.append({"time": b["date"], "value": round(running / n, 4)})
    return out


def snapshot(symbol: str, bars: list[dict]) -> dict:
    closes = [b["close"] for b in bars]
    volumes = [b["volume"] for b in bars]
    price = closes[-1]

    sma20, sma50, sma200 = sma(closes, 20), sma(closes, 50), sma(closes, 200)
    year_high = max(b["high"] for b in bars[-252:])
    year_low = min(b["low"] for b in bars[-252:])
    swing_highs, swing_lows = swing_levels(bars)
    resistance = min((h for h in swing_highs if h > price), default=None)
    support = max((l for l in swing_lows if l < price), default=None)

    above = [m for m in (sma20, sma50, sma200) if m is not None and price > m]
    below = [m for m in (sma20, sma50, sma200) if m is not None and price < m]
    if len(above) >= 2 and sma20 and sma50 and sma20 > sma50:
        trend = "uptrend"
    elif len(below) >= 2 and sma20 and sma50 and sma20 < sma50:
        trend = "downtrend"
    else:
        trend = "sideways"

    vol20, vol60 = sma([float(v) for v in volumes], 20), sma([float(v) for v in volumes], 60)

    def pct(a, b):
        return round((a / b - 1) * 100, 2) if a is not None and b else None

    atr = atr14(bars)
    return {
        "symbol": symbol,
        "date": bars[-1]["date"],
        "price": price,
        "change_5d_pct": pct(price, closes[-6] if len(closes) > 5 else None),
        "change_20d_pct": pct(price, closes[-21] if len(closes) > 20 else None),
        "sma20": round(sma20, 2) if sma20 else None,
        "sma50": round(sma50, 2) if sma50 else None,
        "sma200": round(sma200, 2) if sma200 else None,
        "trend": trend,
        "rsi14": round(rsi14(closes), 1) if rsi14(closes) is not None else None,
        "atr14": round(atr, 2) if atr else None,
        "atr_pct": round(atr / price * 100, 2) if atr else None,
        "year_high": round(year_high, 2),
        "year_low": round(year_low, 2),
        "off_year_high_pct": pct(price, year_high),
        "support": round(support, 2) if support else None,
        "resistance": round(resistance, 2) if resistance else None,
        "volume_ratio_20d_60d": round(vol20 / vol60, 2) if vol20 and vol60 else None,
    }
