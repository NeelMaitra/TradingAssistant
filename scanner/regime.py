"""Market and sector regime: is the tide in or out, and which sectors lead.

Score runs -1 (risk-off) to +1 (risk-on), built from parts you can read:
SPY / QQQ / IWM trend structure, VIX level and direction, credit (HYG),
and breadth (% of the scanned universe above its 50-day average).
"""

from . import config
from .indicators import Pack, slope

MARKET = ["SPY", "QQQ", "IWM", "^VIX", "HYG"]


def _trend_points(p, i):
    """-1..+1 from the moving-average stack of one index ETF."""
    c = p.bars.c[i]
    pts, parts = 0.0, []
    checks = [
        ("above 20 EMA", p.ema20[i] is not None and c > p.ema20[i]),
        ("20 EMA above 50 SMA", None not in (p.ema20[i], p.sma50[i]) and p.ema20[i] > p.sma50[i]),
        ("above 200 SMA", p.sma200[i] is not None and c > p.sma200[i]),
        ("50 SMA rising", (slope(p.sma50, i, 10) or 0) > 0),
    ]
    for label, ok in checks:
        pts += 0.25 if ok else -0.25
        parts.append((label, ok))
    return pts, parts


def market(bars, breadth=None):
    """bars: symbol -> Bars (needs SPY; QQQ, IWM, ^VIX, HYG optional).
    breadth: fraction 0..1 of universe stocks above their 50 SMA (optional)."""
    packs = {s: Pack(b) for s, b in bars.items() if s in MARKET and len(b) >= 30}
    idx = {s: len(p.bars) - 1 for s, p in packs.items()}
    return market_at(packs, idx, breadth)


def market_at(packs, idx, breadth=None):
    """Same score from precomputed packs at bar indexes idx[sym] (the backtest uses this
    to score every historical day without look-ahead)."""
    if "SPY" not in packs or idx.get("SPY") is None:
        return {"score": 0.0, "label": "Unknown", "reasons": ["no SPY data"], "parts": {}}
    parts, reasons, total, weight = {}, [], 0.0, 0.0
    for sym, w in (("SPY", 0.35), ("QQQ", 0.15), ("IWM", 0.10)):
        p, i = packs.get(sym), idx.get(sym)
        if p is None or i is None or i < 59:
            continue
        pts, checks = _trend_points(p, i)
        parts[sym] = {"points": round(pts, 2), "close": round(p.bars.c[i], 2),
                      "checks": {k: v for k, v in checks},
                      "roc20": round(p.roc20[i], 2) if p.roc20[i] is not None else None}
        total += pts * w
        weight += w
        good = [k for k, v in checks if v]
        reasons.append("%s %s (%s)" % (sym, "uptrend" if pts > 0.4 else "downtrend" if pts < -0.4 else "mixed",
                                       ", ".join(good) if good else "below every average"))
    if packs.get("^VIX") is not None and (idx.get("^VIX") or 0) > 5:
        v = packs["^VIX"].bars.c
        i = idx["^VIX"]
        lvl, chg = v[i], 100 * (v[i] / v[i - 5] - 1)
        pts = 0.5 if lvl < 16 else 0.15 if lvl < 20 else -0.3 if lvl < 25 else -0.7 if lvl < 32 else -1.0
        if chg > 20:
            pts -= 0.3
        elif chg < -15:
            pts += 0.2
        pts = max(-1.0, min(1.0, pts))
        parts["VIX"] = {"level": round(lvl, 2), "chg5d": round(chg, 1), "points": round(pts, 2)}
        total += pts * 0.2
        weight += 0.2
        reasons.append("VIX %.1f (%+.0f%% in 5 days)" % (lvl, chg))
    if packs.get("HYG") is not None and (idx.get("HYG") or 0) > 25:
        p, i = packs["HYG"], idx["HYG"]
        ok = p.ema20[i] is not None and p.bars.c[i] > p.ema20[i]
        parts["credit"] = {"hyg_above_20ema": ok}
        total += (0.5 if ok else -0.5) * 0.1
        weight += 0.1
        reasons.append("credit (HYG) %s its 20 EMA" % ("above" if ok else "below"))
    if breadth is not None:
        pts = max(-1.0, min(1.0, (breadth - 0.5) * 4))
        parts["breadth"] = {"pct_above_50sma": round(100 * breadth, 1), "points": round(pts, 2)}
        total += pts * 0.15
        weight += 0.15
        reasons.append("%.0f%% of stocks above their 50-day" % (100 * breadth))
    score = total / weight if weight else 0.0
    label = "Risk-on" if score >= 0.35 else "Risk-off" if score <= -0.35 else "Neutral"
    return {"score": round(score, 3), "label": label, "reasons": reasons, "parts": parts}


def breadth(packs):
    """Fraction of stock packs whose last close is above the 50 SMA."""
    up = n = 0
    for p in packs:
        s = p.sma50[-1]
        if s is None:
            continue
        n += 1
        up += p.bars.c[-1] > s
    return (up / n) if n else None


def sectors(bars):
    """Sector ETFs ranked by relative strength vs SPY (20 and 63 day)."""
    packs = {s: Pack(b) for s, b in bars.items()
             if (s == "SPY" or s in config.SECTOR_ETFS) and len(b) >= 70}
    return sectors_at(packs, {s: len(p.bars) - 1 for s, p in packs.items()})


def sectors_at(packs, idx):
    if "SPY" not in packs or idx.get("SPY") is None:
        return []
    spy, si = packs["SPY"], idx["SPY"]
    s20, s63 = spy.roc20[si] or 0, spy.roc63[si] or 0
    rows = []
    for sym, name in config.SECTOR_ETFS.items():
        p, i = packs.get(sym), idx.get(sym)
        if p is None or i is None:
            continue
        r20, r63 = p.roc20[i], p.roc63[i]
        if r20 is None or r63 is None:
            continue
        rs = 0.6 * (r20 - s20) + 0.4 * (r63 - s63)
        rows.append({"etf": sym, "sector": name, "rs": round(rs, 2), "roc20": round(r20, 2),
                     "roc63": round(r63, 2),
                     "above_50sma": p.sma50[i] is not None and p.bars.c[i] > p.sma50[i]})
    rows.sort(key=lambda r: r["rs"], reverse=True)
    n = len(rows)
    for k, r in enumerate(rows):
        r["rank"] = k + 1
        r["status"] = "leading" if k < n / 3 else "lagging" if k >= 2 * n / 3 else "middle"
    return rows


def alignment(direction, mkt, sector_row=None, kind="stock"):
    """0..1: how much the tide helps this trade, with the reasons."""
    s = mkt.get("score", 0.0)
    m = (s + 1) / 2 if direction == "long" else (1 - s) / 2   # 0..1
    reasons = ["market %s (%+.2f)" % (mkt.get("label", "?"), s)]
    if sector_row is None or kind != "stock":
        return round(m, 3), reasons
    st = sector_row["status"]
    if direction == "long":
        sec = 1.0 if st == "leading" else 0.5 if st == "middle" else 0.1
    else:
        sec = 1.0 if st == "lagging" else 0.5 if st == "middle" else 0.1
    reasons.append("%s %s (#%d RS)" % (sector_row["sector"], st, sector_row["rank"]))
    return round(0.6 * m + 0.4 * sec, 3), reasons
