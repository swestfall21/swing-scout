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


def setups(snap: dict, levels: dict, bars: list[dict]) -> list[dict]:
    """Rule-based setups worth watching in the next session, judged from the
    latest close. Deterministic screening of price/level/indicator geometry —
    not trade advice; the Claude analyst (`scout research`) is the layer that
    weighs news and forms an opinion.

    Each setup: name, bias ("long" | "caution" | "neutral"), trigger (what has
    to happen tomorrow), stop (suggested invalidation price or None), note.
    """
    out: list[dict] = []
    price = snap["price"]
    atr = snap["atr14"] or price * 0.02
    rsi = snap["rsi14"]
    trend = snap["trend"]
    prev_high = round(bars[-1]["high"], 2)
    prev_low = round(bars[-1]["low"], 2)
    supports, resistances = levels["support"], levels["resistance"]
    sup = supports[0] if supports else None
    res = resistances[0] if resistances else None
    vol_hot = (snap["volume_ratio_20d_60d"] or 1.0) >= 1.2

    def near(level: float | None, atr_mult: float) -> bool:
        return level is not None and abs(level - price) <= atr * atr_mult

    if trend == "uptrend" and near(res, 1.5):
        out.append({
            "name": "Breakout watch", "bias": "long",
            "trigger": f"close above resistance {res}"
                       + (" — volume already running hot" if vol_hot
                          else " on above-average volume"),
            "stop": round(res - atr, 2),
            "note": "Uptrend pressing its nearest ceiling; a rejection here "
                    "often retests the 20-day line first.",
        })

    if trend == "uptrend" and (rsi is None or rsi < 65):
        for n in (20, 50):
            ma = snap[f"sma{n}"]
            if ma and abs(price - ma) <= atr * 0.75:
                out.append({
                    "name": f"Pullback to SMA {n}", "bias": "long",
                    "trigger": f"hold the {n}-day line ({ma}) and push back "
                               f"above yesterday's high {prev_high}",
                    "stop": round(ma - atr * 0.75, 2),
                    "note": "Trend-following entry: buy the bounce, not the "
                            "touch — let the reversal print first.",
                })
                break  # nearest MA only; don't stack both

    if near(sup, 1.0):
        if trend == "downtrend":
            nxt = supports[1] if len(supports) > 1 else None
            out.append({
                "name": "Breakdown watch", "bias": "caution",
                "trigger": f"close below support {sup}"
                           + (f" opens the door to {nxt}" if nxt else ""),
                "stop": None,
                "note": "Downtrend sitting on its nearest floor — no long "
                        "until it reclaims the 20-day line "
                        f"({snap['sma20']}); a bounce before that is a "
                        "countertrend scalp at best.",
            })
        else:
            out.append({
                "name": "Support bounce", "bias": "long",
                "trigger": f"defend {sup}, then push above yesterday's "
                           f"high {prev_high}",
                "stop": round(sup - atr * 0.5, 2),
                "note": "Buying a tested floor; if the level cracks intraday "
                        "and doesn't recover, the setup is void.",
            })

    if rsi is not None and rsi <= 30:
        out.append({
            "name": "Oversold snapback", "bias": "long",
            "trigger": f"reversal close above yesterday's high {prev_high} "
                       f"(RSI {rsi})",
            "stop": round(prev_low - atr * 0.5, 2),
            "note": "Countertrend mean-reversion — small size, quick exit; "
                    "oversold can stay oversold.",
        })
    elif rsi is not None and rsi >= 70 and near(res, 1.0):
        out.append({
            "name": "Extended at resistance", "bias": "neutral",
            "trigger": f"no chase: RSI {rsi} into resistance {res}",
            "stop": None,
            "note": "Better entries usually come on the pullback or after a "
                    "clean breakout-and-hold above the level.",
        })

    return out


def entry_read(snap: dict, levels: dict, setup_list: list[dict]) -> dict:
    """Should-new-money-go-here verdict for a symbol with no open position:
    "setup" (take the trigger), "wait" (no edge at this price), or "avoid"
    (fighting the tape), with the level that would flip the verdict.
    Chart geometry only, same as setups() and position_plan().
    """
    sma20 = snap["sma20"]
    sup, res = levels["support"], levels["resistance"]
    s1 = sup[0] if sup else None
    r1 = res[0] if res else None
    longs = [s for s in setup_list if s["bias"] == "long"]

    if snap["trend"] == "downtrend":
        flip = (next((r for r in res if r >= sma20), round(sma20, 2))
                if sma20 else r1)
        why = ("Downtrend — sellers are in control below the falling averages, "
               "so a new long is fighting the tape"
               + (f"; nothing to do until it closes back above {flip}" if flip else "")
               + ".")
        if longs:
            why += (f" The {longs[0]['name'].lower()} flagged below is "
                    "countertrend — small size and a quick exit, if at all.")
        return {"stance": "avoid", "headline": "No new money here", "why": why,
                "flip_above": flip, "support": s1, "resistance": r1}

    if longs:
        stop = next((s["stop"] for s in longs if s.get("stop") is not None), None)
        names = " / ".join(s["name"].lower() for s in longs)
        return {
            "stance": "setup", "headline": "Worth a starter — on the trigger only",
            "why": (f"{snap['trend'].capitalize()} tape with an actionable "
                    f"{names} flagged below. Take the trigger, don't front-run "
                    "it, and size so the stop costs no more than 1–2% of the "
                    "account."),
            "stop_if_triggered": stop, "support": s1, "resistance": r1,
        }

    if snap["trend"] == "uptrend":
        return {
            "stance": "wait", "headline": "Right trend, wrong price",
            "why": ("Uptrend but no edge at this price — chasing mid-air buys "
                    "someone else's exit. Wait for a pullback toward the 20-day"
                    + (f" ({sma20})" if sma20 else "")
                    + (f" or a breakout through {r1}" if r1 else "") + "."),
            "pullback_zone": sma20, "breakout_above": r1,
            "support": s1, "resistance": r1,
        }

    return {
        "stance": "wait", "headline": "No trend, no trade",
        "why": ("Range-bound — no trend to lean on, so the range edges are the "
                "only edges" + (f": support {s1}" if s1 else "")
                + (f", resistance {r1}" if r1 else "")
                + ". Wait for a tested bounce or a clean break."),
        "support": s1, "resistance": r1,
    }


def position_plan(snap: dict, levels: dict, pos: dict) -> dict | None:
    """Rule-based management plan for an open position: a stance plus the
    levels that should trigger action (reassess stop, hard stop, add trigger,
    targets). Same spirit as setups() — chart geometry only, recomputed from
    each day's close; news and earnings are the Claude analyst's job.
    """
    if not pos or not pos.get("qty"):
        return None
    price = snap["price"]
    atr = snap["atr14"] or price * 0.02
    sma20, sma50, sma200 = snap["sma20"], snap["sma50"], snap["sma200"]
    trend = snap["trend"]
    sup, res = levels["support"], levels["resistance"]
    s1 = sup[0] if sup else round(price - 2 * atr, 2)
    s2 = sup[1] if len(sup) > 1 else round(s1 - atr, 2)

    if trend == "uptrend" and sma20 and price > sma20:
        stance, headline = "hold", "Trend intact — let it work"
        why = (f"Uptrend holding above the 20-day line ({sma20}). Sit tight "
               f"and trail the stop up behind each new support as it forms.")
        ref = None  # adds come on strength through the nearest ceiling
    elif (sma200 is None or price > sma200) and trend != "downtrend":
        stance, headline = "hold", "Hold, with a line in the sand"
        state = []
        if sma200:
            state.append(f"above the 200-day ({sma200})")
        if sma50 and price < sma50:
            state.append(f"still below the 50-day ({sma50})")
        why = ("Recovery, not a resumed uptrend — "
               + (" but ".join(state) or "not enough history for the long averages")
               + f". Hold while {s1} holds; a close below it says the repair is failing.")
        ref = sma50 if sma50 and sma50 > price else None
    elif sma200 is None or price > sma200:
        stance, headline = "caution", "Correction inside a bigger uptrend — tighten up"
        why = (f"Falling under the shorter averages but still above the 200-day "
               f"({sma200}). Hold only with the line at {s1}; a close below it "
               "and you're holding hope, not a thesis.")
        ref = sma20 if sma20 and sma20 > price else None
    else:
        stance, headline = "reduce", "Downtrend below the 200-day — protect the capital"
        why = (f"Under the 200-day ({sma200}) with the shorter averages pointing "
               f"down. Bounces into resistance are exits, not add points, until "
               f"the 20-day ({sma20}) is reclaimed.")
        ref = sma20 if sma20 and sma20 > price else None

    if ref is not None:
        add_above = next((r for r in res if r >= ref), round(ref, 2))
    else:
        add_above = res[0] if res else None
    targets = [r for r in res if add_above is None or r > add_above][:2]

    # Sell-into-strength levels: trim part into the biggest overhead shelf
    # (highest tracked resistance up to the 52-week high); if the breakout
    # pop carries a full ATR past that zone, take the rest.
    zone_lo = res[-1] if res else snap["year_high"]
    zone_hi = max(snap["year_high"], zone_lo)
    full_profit = round(zone_hi + atr, 2)

    plan = {
        "stance": stance, "headline": headline, "why": why,
        "stop_reassess": s1, "stop_hard": s2,
        "add_above": add_above, "targets": targets,
        "trim_zone": [zone_lo, zone_hi], "full_profit": full_profit,
        "notes": [],
    }
    if pos.get("avg_cost"):
        ac = pos["avg_cost"]
        hp = round((s2 / ac - 1) * 100, 1)
        plan["hard_stop_pnl_pct"] = hp
        if hp > 0:
            plan["notes"].append(
                f"Even the hard stop banks {hp:+.1f}% — don't let a winner round-trip.")
        elif (pos.get("unrealized_pct") or 0) < 0 and stance in ("caution", "reduce"):
            plan["notes"].append(
                "Underwater with the trend against you — honor the hard stop; "
                "don't average down.")
        plan["trim_pnl_pct"] = round((zone_lo / ac - 1) * 100, 1)
        plan["full_profit_pnl_pct"] = round((full_profit / ac - 1) * 100, 1)
        plan["notes"].append(
            f"First touch of the trim zone banks {plan['trim_pnl_pct']:+.1f}% "
            f"from cost; the full-profit mark {plan['full_profit_pnl_pct']:+.1f}%. "
            "A spike 3+ ATR above the 20-day line is a sell-into-strength "
            "signal wherever it happens.")
    return plan


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
