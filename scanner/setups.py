"""Daily (swing) setups, detected on the close of bar i for the next session.

Each setup is a plan you can check: a trigger price, a stop, targets in R
(1R = trigger - stop), the key level it is built around, a 0..1 quality and the
plain-English reasons. Long and short versions of each:

  breakout        tight base just under the 20-day high, in an uptrend
  pullback        uptrend pulling back into the rising 20 EMA and holding it
  gap_go          gap of 3%+ on heavy volume that held into the close
  episodic_pivot  gap of 8%+ on 3x volume (usually news or earnings)
  oversold_bounce long-term uptrend, 2-day RSI washed out (mean reversion)
  breakdown / failed_rally / gap_down / overbought_fade: the short mirrors
"""

from .indicators import slope


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _plan(name, direction, entry, stop, atr, level, quality, reasons, hold, kind="stop"):
    risk = abs(entry - stop)
    if risk <= 0 or atr is None or atr <= 0:
        return None
    sign = 1 if direction == "long" else -1
    return {
        "setup": name, "direction": direction,
        "entry": round(entry, 4), "stop": round(stop, 4), "entry_type": kind,
        "risk_per_share": round(risk, 4), "risk_atr": round(risk / atr, 2),
        "targets": [round(entry + sign * r * risk, 4) for r in (1, 2, 3)],
        "level": round(level, 4) if level is not None else None,
        "quality": round(_clip(quality), 3), "reasons": reasons, "hold": hold,
    }


def _bound_stop(direction, entry, structural, atr, lo=0.5, hi=2.0):
    """Keep the stop between lo and hi ATRs from the entry."""
    if direction == "long":
        return min(max(structural, entry - hi * atr), entry - lo * atr)
    return max(min(structural, entry + hi * atr), entry + lo * atr)


def trend_score(p, i, direction):
    """0..1: how cleanly the trend structure favours this direction."""
    c = p.bars.c[i]
    e20, s50, s200 = p.ema20[i], p.sma50[i], p.sma200[i]
    checks = []
    if e20 is not None:
        checks.append(("close above 20 EMA", c > e20))
    if None not in (e20, s50):
        checks.append(("20 EMA above 50 SMA", e20 > s50))
    if None not in (s50, s200):
        checks.append(("50 SMA above 200 SMA", s50 > s200))
    if s200 is not None:
        checks.append(("close above 200 SMA", c > s200))
    sl = slope(p.sma50, i, 10)
    if sl is not None:
        checks.append(("50 SMA rising", sl > 0))
    if p.roc63[i] is not None:
        checks.append(("3-month return positive", p.roc63[i] > 0))
    if p.hi252[i] is not None and p.lo252[i] is not None and p.hi252[i] > p.lo252[i]:
        pos = (c - p.lo252[i]) / (p.hi252[i] - p.lo252[i])
        checks.append(("upper half of 52-week range", pos > 0.5))
    if not checks:
        return 0.0, []
    if direction == "short":
        checks = [(k.replace("above", "below").replace("rising", "falling")
                   .replace("positive", "negative").replace("upper", "lower"), not v) for k, v in checks]
    score = sum(1 for _, v in checks if v) / len(checks)
    a = p.adx14[i]
    if a is not None:
        score = score * (0.85 + 0.15 * _clip((a - 15) / 20))   # trending markets get full credit
    return round(score, 3), [k for k, v in checks if v]


def participation(p, i, gap_pct=None):
    """0..1 from relative volume, liquidity and the gap."""
    rv = p.rvol20[i] or 0.0
    dv = p.dollar_vol20[i] or 0.0
    s = 0.55 * _clip((rv - 0.8) / 1.7) + 0.25 * _clip((dv / 1e6 - 20) / 280)
    if gap_pct is not None:
        s += 0.2 * _clip(abs(gap_pct) / 6)
    return round(_clip(s), 3), rv


def detect(p, i, cfg):
    """All setups that fire on bar i. p is an indicators.Pack."""
    b = p.bars
    if i < 60 or p.atr14[i] is None or p.ema20[i] is None or p.sma50[i] is None:
        return []
    sc = cfg["setups"]
    o, h, l, c = b.o, b.h, b.l, b.c
    atr = p.atr14[i]
    rv = p.rvol20[i] or 0.0
    gap = 100.0 * (o[i] / c[i - 1] - 1) if c[i - 1] else 0.0
    rng = h[i] - l[i]
    close_pos = (c[i] - l[i]) / rng if rng > 0 else 0.5
    tight = (p.atr10[i] / p.atr50[i]) if p.atr10[i] and p.atr50[i] else 1.0
    e20, s50, s200 = p.ema20[i], p.sma50[i], p.sma200[i]
    s50_up = (slope(p.sma50, i, 10) or 0) > 0
    uptrend = c[i] > s50 and e20 > s50 and s50_up
    downtrend = c[i] < s50 and e20 < s50 and not s50_up
    # bases flatten the 20 EMA into the 50, so breakouts only need price above a rising 50 (and the 200)
    bo_up = c[i] > s50 and s50_up and (s200 is None or c[i] > s200)
    bo_down = c[i] < s50 and not s50_up and (s200 is None or c[i] < s200)
    n = sc["breakout_lookback"]
    prior_hi = max(h[i - n:i])
    prior_lo = min(l[i - n:i])
    out = []

    # ---------------- breakout / breakdown from a tight base
    base_lo, base_hi = min(l[i - 7:i + 1]), max(h[i - 7:i + 1])
    if bo_up and c[i] >= prior_hi * 0.97 and tight < sc["contraction_ratio"] + 0.15:
        pivot = max(prior_hi, h[i])
        entry = pivot + 0.05 * atr
        stop = _bound_stop("long", entry, base_lo - 0.05 * atr, atr, 0.75, 2.0)
        q = 0.35 * _clip((sc["contraction_ratio"] + 0.15 - tight) / 0.4) + 0.25 * _clip(close_pos) \
            + 0.25 * _clip((rv - 0.7) / 1.3) + 0.15 * (1.0 if c[i] > prior_hi else 0.5)
        why = ["%s the %d-day high %.2f" % ("closed above" if c[i] > prior_hi else "%.1f%% under" %
                                             (100 * (1 - c[i] / prior_hi)), n, prior_hi),
               "volatility contracting (ATR10/ATR50 %.2f)" % tight, "rel. volume %.1fx" % rv]
        pl = _plan("breakout", "long", entry, stop, atr, pivot, q, why, "swing 3-15 days")
        if pl:
            out.append(pl)
    if bo_down and c[i] <= prior_lo * 1.03 and tight < sc["contraction_ratio"] + 0.15:
        pivot = min(prior_lo, l[i])
        entry = pivot - 0.05 * atr
        stop = _bound_stop("short", entry, base_hi + 0.05 * atr, atr, 0.75, 2.0)
        q = 0.35 * _clip((sc["contraction_ratio"] + 0.15 - tight) / 0.4) + 0.25 * _clip(1 - close_pos) \
            + 0.25 * _clip((rv - 0.7) / 1.3) + 0.15 * (1.0 if c[i] < prior_lo else 0.5)
        why = ["%s the %d-day low %.2f" % ("closed below" if c[i] < prior_lo else "within 3% of", n, prior_lo),
               "volatility contracting (ATR10/ATR50 %.2f)" % tight, "rel. volume %.1fx" % rv]
        pl = _plan("breakdown", "short", entry, stop, atr, pivot, q, why, "swing 3-15 days")
        if pl:
            out.append(pl)

    # ---------------- pullback to the 20 EMA / failed rally into it
    band = sc["pullback_atr_band"] * atr
    touched_lo = min(l[i - 2:i + 1])
    touched_hi = max(h[i - 2:i + 1])
    r14 = p.rsi14[i] or 50
    if uptrend and touched_lo <= e20 + band and c[i] > e20 and 35 <= r14 <= 62 and c[i] < prior_hi:
        entry = h[i] + 0.05 * atr
        stop = _bound_stop("long", entry, min(touched_lo, e20) - 0.1 * atr, atr, 0.5, 2.0)
        adx = p.adx14[i] or 15
        q = 0.3 * _clip((adx - 15) / 20) + 0.3 * _clip(close_pos) + 0.2 * _clip((62 - r14) / 20) \
            + 0.2 * (1.0 if c[i] > o[i] else 0.4)
        why = ["uptrend pulled back to the rising 20 EMA (%.2f) and held" % e20,
               "RSI(14) reset to %.0f" % r14, "ADX %.0f" % adx]
        pl = _plan("pullback", "long", entry, stop, atr, e20, q, why, "swing 2-10 days")
        if pl:
            out.append(pl)
    if downtrend and touched_hi >= e20 - band and c[i] < e20 and 38 <= r14 <= 65 and c[i] > prior_lo:
        entry = l[i] - 0.05 * atr
        stop = _bound_stop("short", entry, max(touched_hi, e20) + 0.1 * atr, atr, 0.5, 2.0)
        adx = p.adx14[i] or 15
        q = 0.3 * _clip((adx - 15) / 20) + 0.3 * _clip(1 - close_pos) + 0.2 * _clip((r14 - 38) / 20) \
            + 0.2 * (1.0 if c[i] < o[i] else 0.4)
        why = ["downtrend rallied into the falling 20 EMA (%.2f) and failed" % e20,
               "RSI(14) %.0f" % r14, "ADX %.0f" % adx]
        pl = _plan("failed_rally", "short", entry, stop, atr, e20, q, why, "swing 2-10 days")
        if pl:
            out.append(pl)

    # ---------------- gaps that held (gap & go / episodic pivot)
    if gap >= sc["gap_pct"] and rv >= sc["rvol_high"] and close_pos >= 0.5 and c[i] > o[i] * 0.99:
        ep = gap >= sc["episodic_gap_pct"] and rv >= 3
        entry = h[i] + 0.05 * atr
        stop = _bound_stop("long", entry, l[i] - 0.05 * atr, atr, 0.75, 2.5)
        q = 0.35 * _clip(gap / 12) + 0.35 * _clip((rv - 1.5) / 3) + 0.3 * _clip(close_pos)
        why = ["gapped up %.1f%% on %.1fx volume and held (closed in top %.0f%% of range)"
               % (gap, rv, 100 * (1 - close_pos) if close_pos < 1 else 0)]
        if ep:
            why.append("episodic pivot size: check the news or earnings behind it")
        pl = _plan("episodic_pivot" if ep else "gap_go", "long", entry, stop, atr, l[i], q, why,
                   "swing 3-20 days" if ep else "1-5 days")
        if pl:
            out.append(pl)
    if gap <= -sc["gap_pct"] and rv >= sc["rvol_high"] and close_pos <= 0.5 and c[i] < o[i] * 1.01:
        entry = l[i] - 0.05 * atr
        stop = _bound_stop("short", entry, h[i] + 0.05 * atr, atr, 0.75, 2.5)
        q = 0.35 * _clip(-gap / 12) + 0.35 * _clip((rv - 1.5) / 3) + 0.3 * _clip(1 - close_pos)
        why = ["gapped down %.1f%% on %.1fx volume and stayed weak" % (-gap, rv)]
        pl = _plan("gap_down", "short", entry, stop, atr, h[i], q, why, "1-5 days")
        if pl:
            out.append(pl)

    # ---------------- mean reversion inside the bigger trend
    r2 = p.rsi2[i]
    if r2 is not None and s200 is not None:
        if c[i] > s200 and r2 < 10 and c[i] < (p.ema8[i] or c[i]):
            entry = c[i]
            stop = entry - 1.5 * atr
            q = 0.5 * _clip((10 - r2) / 10) + 0.5 * _clip((c[i] / s200 - 1) * 10)
            why = ["above the 200 SMA but 2-day RSI %.1f (washed out)" % r2,
                   "target: back to the 8 EMA (%.2f)" % (p.ema8[i] or 0)]
            pl = _plan("oversold_bounce", "long", entry, stop, atr, s200, q, why, "1-5 days", kind="close")
            if pl:
                pl["targets"][0] = round(max(p.ema8[i] or entry, entry + 0.5 * atr), 4)
                out.append(pl)
        if c[i] < s200 and r2 > 90 and c[i] > (p.ema8[i] or c[i]):
            entry = c[i]
            stop = entry + 1.5 * atr
            q = 0.5 * _clip((r2 - 90) / 10) + 0.5 * _clip((1 - c[i] / s200) * 10)
            why = ["below the 200 SMA but 2-day RSI %.1f (stretched)" % r2,
                   "target: back to the 8 EMA (%.2f)" % (p.ema8[i] or 0)]
            pl = _plan("overbought_fade", "short", entry, stop, atr, s200, q, why, "1-5 days", kind="close")
            if pl:
                pl["targets"][0] = round(min(p.ema8[i] or entry, entry - 0.5 * atr), 4)
                out.append(pl)
    for pl in out:
        pl["gap_pct"] = round(gap, 2)
        pl["rvol"] = round(rv, 2)
    return out


def key_levels(p, i):
    """Levels worth knowing for any symbol, nearest first is up to the caller."""
    b = p.bars
    lv = {"prior_high": b.h[i], "prior_low": b.l[i], "prior_close": b.c[i],
          "high_20d": p.hi20[i], "low_20d": p.lo20[i], "high_52w": p.hi252[i], "low_52w": p.lo252[i],
          "ema20": p.ema20[i], "sma50": p.sma50[i], "sma200": p.sma200[i]}
    return {k: round(v, 4) for k, v in lv.items() if v is not None}
