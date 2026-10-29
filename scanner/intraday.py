"""Intraday layer (5-minute bars): the levels and triggers for today's session.

For each name on the watchlist it works out
  prior day high / low / close, premarket high / low, the opening range,
  session VWAP, high / low of day, intraday relative volume (vs the same time
  of day on recent sessions) and relative strength vs SPY,
then checks the triggers (long and short mirrors):
  orb        close beyond the opening range, on the right side of VWAP
  vwap       reclaim (or loss) of VWAP held for 2 bars
  pdh / pdl  break of the prior day high / low
  pmh / pml  break of the premarket high / low
Before the open it returns the levels and pending plans instead.
Bars are ~15 minutes delayed on free data: confirm on your broker's chart.
"""

from .data import session_parts, trading_days
from .indicators import vwap as vwap_fn, atr as atr_fn


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _r(x, n=4):
    return None if x is None else round(x, n)


def prior_session(b, day):
    days = trading_days(b)
    prev = [d for d in days if d < day]
    if not prev:
        return None
    pd = prev[-1]
    _, reg, _ = session_parts(b, pd)
    if not reg:
        return None
    return {"date": pd.isoformat(), "high": max(b.h[i] for i in reg), "low": min(b.l[i] for i in reg),
            "close": b.c[reg[-1]]}


def cum_volume_profile(b, days, minute_of_day):
    """Average cumulative regular-session volume up to minute_of_day over `days`."""
    vals = []
    for d in days:
        _, reg, _ = session_parts(b, d)
        if not reg:
            continue
        vals.append(sum(b.v[i] for i in reg if b.t[i].hour * 60 + b.t[i].minute <= minute_of_day))
    vals = [v for v in vals if v > 0]
    return sum(vals) / len(vals) if vals else None


def analyze(b, cfg, spy_change=None, daily_atr=None):
    """b: intraday Bars (with pre/post). Returns levels, state, triggers."""
    if not len(b):
        return None
    ic = cfg["intraday"]
    day = b.t[-1].date()
    pre, reg, _post = session_parts(b, day)
    prior = prior_session(b, day)
    out = {"symbol": b.symbol, "date": day.isoformat(), "last": _r(b.c[-1]),
           "last_time": b.t[-1].strftime("%H:%M"), "phase": "premarket" if not reg else "regular",
           "levels": {}, "triggers": [], "plans": []}
    lv = out["levels"]
    if prior:
        lv.update({"pdh": _r(prior["high"]), "pdl": _r(prior["low"]), "pdc": _r(prior["close"])})
    if pre:
        lv.update({"pmh": _r(max(b.h[i] for i in pre)), "pml": _r(min(b.l[i] for i in pre))})
    ref_close = prior["close"] if prior else None
    if ref_close:
        out["change_pct"] = _r(100 * (b.c[-1] / ref_close - 1), 2)
        first_px = b.o[reg[0]] if reg else (b.c[pre[-1]] if pre else b.c[-1])
        out["gap_pct"] = _r(100 * (first_px / ref_close - 1), 2)
    if spy_change is not None and out.get("change_pct") is not None:
        out["rs_vs_spy"] = _r(out["change_pct"] - spy_change, 2)

    # 5-minute ATR over recent bars, for stop padding
    a5 = atr_fn(b.h, b.l, b.c, 14)
    atr5 = a5[-1] if a5 and a5[-1] else (b.h[-1] - b.l[-1]) or 0.01
    pad = 0.25 * atr5

    if not reg:
        # ---- before the open: levels to watch and conditional plans
        long_lv = lv.get("pmh") or lv.get("pdh")
        short_lv = lv.get("pml") or lv.get("pdl")
        if long_lv:
            stop = max(lv.get("pml") or 0, long_lv - 2 * (daily_atr or atr5 * 4) * 0.25)
            out["plans"].append(_trig("pending_long", "long", long_lv + 0.01, min(stop, long_lv - pad), atr5,
                                      ["long only if it breaks and holds above %.2f (%s) after the open, above VWAP"
                                       % (long_lv, "premarket high" if lv.get("pmh") else "prior day high")]))
        if short_lv:
            stop = min(lv.get("pmh") or 1e12, short_lv + 2 * (daily_atr or atr5 * 4) * 0.25)
            out["plans"].append(_trig("pending_short", "short", short_lv - 0.01, max(stop, short_lv + pad), atr5,
                                      ["short only if it loses %.2f (%s) after the open, below VWAP"
                                       % (short_lv, "premarket low" if lv.get("pml") else "prior day low")]))
        out["score_long"] = out["score_short"] = None
        return out

    # ---- regular session
    vw = vwap_fn(b.h, b.l, b.c, b.v, reg)
    last = reg[-1]
    out["vwap"] = _r(vw[last])
    lv["hod"], lv["lod"] = _r(max(b.h[i] for i in reg)), _r(min(b.l[i] for i in reg))
    orn = ic["opening_range_minutes"]
    open_min = b.t[reg[0]].hour * 60 + b.t[reg[0]].minute
    or_idx = [i for i in reg if (b.t[i].hour * 60 + b.t[i].minute) < open_min + orn]
    or_done = (b.t[last].hour * 60 + b.t[last].minute) >= open_min + orn
    if or_idx:
        lv["orh"], lv["orl"] = _r(max(b.h[i] for i in or_idx)), _r(min(b.l[i] for i in or_idx))
    now_min = b.t[last].hour * 60 + b.t[last].minute
    prev_days = [d for d in trading_days(b) if d < day][-ic["rvol_days"]:]
    avg_cum = cum_volume_profile(b, prev_days, now_min)
    cum = sum(b.v[i] for i in reg)
    out["rvol"] = _r(cum / avg_cum, 2) if avg_cum else None

    c = b.c
    above_vwap = c[last] > vw[last]
    trig = out["triggers"]
    # ORB
    if or_done and or_idx and len(reg) > len(or_idx):
        orh, orl = lv["orh"], lv["orl"]
        first_break_up = next((i for i in reg[len(or_idx):] if c[i] > orh), None)
        first_break_dn = next((i for i in reg[len(or_idx):] if c[i] < orl), None)
        if first_break_up is not None and c[last] > orh and above_vwap:
            trig.append(_trig("orb_long", "long", orh, max(orl, vw[last] - pad) if vw[last] < orh else orl, atr5,
                              ["broke the %d-min opening range high %.2f at %s, holding above VWAP"
                               % (orn, orh, b.t[first_break_up].strftime("%H:%M"))]))
        if first_break_dn is not None and c[last] < orl and not above_vwap:
            trig.append(_trig("orb_short", "short", orl, min(orh, vw[last] + pad) if vw[last] > orl else orh, atr5,
                              ["broke the %d-min opening range low %.2f at %s, holding below VWAP"
                               % (orn, orl, b.t[first_break_dn].strftime("%H:%M"))]))
    # VWAP reclaim / loss (2 bars on the new side after at least 2 on the old)
    if len(reg) >= 5:
        a, bb, cc, dd = reg[-4], reg[-3], reg[-2], reg[-1]
        if c[a] < vw[a] and c[bb] < vw[bb] and c[cc] > vw[cc] and c[dd] > vw[dd]:
            low = min(b.l[i] for i in (cc, dd))
            trig.append(_trig("vwap_reclaim", "long", c[dd], min(low, vw[dd]) - pad, atr5,
                              ["reclaimed VWAP %.2f and held 2 bars" % vw[dd]]))
        if c[a] > vw[a] and c[bb] > vw[bb] and c[cc] < vw[cc] and c[dd] < vw[dd]:
            high = max(b.h[i] for i in (cc, dd))
            trig.append(_trig("vwap_loss", "short", c[dd], max(high, vw[dd]) + pad, atr5,
                              ["lost VWAP %.2f and stayed under 2 bars" % vw[dd]]))
    # level breaks (only the first time today, and only if still beyond the level)
    for key, name, side in (("pdh", "prior day high", "long"), ("pmh", "premarket high", "long"),
                            ("pdl", "prior day low", "short"), ("pml", "premarket low", "short")):
        L = lv.get(key)
        if L is None:
            continue
        if side == "long" and c[last] > L and any(c[i] <= L for i in reg[:-1]) and above_vwap:
            trig.append(_trig(key + "_break", "long", L, max(vw[last] - pad, L - 3 * atr5) if vw[last] < L else L - 2 * atr5,
                              atr5, ["broke and holding above the %s %.2f" % (name, L)]))
        if side == "short" and c[last] < L and any(c[i] >= L for i in reg[:-1]) and not above_vwap:
            trig.append(_trig(key + "_break", "short", L, min(vw[last] + pad, L + 3 * atr5) if vw[last] > L else L + 2 * atr5,
                              atr5, ["broke and holding below the %s %.2f" % (name, L)]))

    # intraday quality per direction
    rs = out.get("rs_vs_spy") or 0.0
    rv = out.get("rvol") or 1.0
    hl = _higher_lows(b, reg)
    base = 0.25 * _clip((rv - 0.8) / 1.7)
    out["score_long"] = _r(_clip(base + 0.3 * (1.0 if above_vwap else 0.0) + 0.25 * _clip(0.5 + rs / 4)
                                 + 0.2 * hl), 3)
    out["score_short"] = _r(_clip(base + 0.3 * (0.0 if above_vwap else 1.0) + 0.25 * _clip(0.5 - rs / 4)
                                  + 0.2 * (1 - hl)), 3)
    out["above_vwap"] = above_vwap
    return out


def _higher_lows(b, reg, k=6):
    """Fraction of the last k swings that made higher lows (0.5 = flat)."""
    idx = reg[-(k + 1):]
    if len(idx) < 3:
        return 0.5
    ups = sum(1 for x, y in zip(idx, idx[1:]) if b.l[y] >= b.l[x])
    return ups / (len(idx) - 1)


def _trig(name, direction, entry, stop, atr5, reasons):
    """Stops closer than one 5-minute ATR get stopped by noise: widen them to 1 ATR."""
    risk = abs(entry - stop)
    floor = atr5 or 0.01
    if risk < floor:
        risk = floor
        stop = entry - risk if direction == "long" else entry + risk
    sign = 1 if direction == "long" else -1
    return {"trigger": name, "direction": direction, "entry": _r(entry), "stop": _r(stop),
            "risk_per_share": _r(risk), "targets": [_r(entry + sign * k * risk) for k in (1, 2, 3)],
            "reasons": reasons, "setup": name, "risk_atr": None}
