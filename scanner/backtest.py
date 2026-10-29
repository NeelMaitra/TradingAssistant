"""Backtest the daily setups so you know which ones earn their place.

For every symbol and every historical day it runs the same detect() the live
scan uses (indicators only see past bars), scores the technical part of the
confluence (regime, trend, setup, participation; history has no headlines or
point-in-time fundamentals), then simulates the plan:

  stop entries fill if price trades through the trigger within `fill_window`
  bars (at the open if it gaps through); close entries fill at the next open.
  Exit at the stop, the target (default 2R) or the close after `max_hold` bars.
  If one bar hits both stop and target, the stop is assumed (conservative).
  Slippage is charged on entry and exit.

Results are in R (multiples of the planned risk), by setup, by score bucket,
and split in-sample / out-of-sample by date, so you can see whether a higher
confluence score really meant better trades, and whether it held up later.
"""

import bisect
import datetime

from . import config, data, regime, scoring, setups
from .indicators import Pack


def simulate(b, i, plan, target_r=2.0, max_hold=10, fill_window=3, slippage_bps=5.0):
    """Trade one plan detected on bar i. Returns a result dict or None if never filled."""
    n = len(b)
    d = 1 if plan["direction"] == "long" else -1
    slip = slippage_bps / 10000.0
    stop = plan["stop"]
    entry_px = fill_j = None
    if plan.get("entry_type") == "close":
        if i + 1 >= n:
            return None
        fill_j, entry_px = i + 1, b.o[i + 1]
    else:
        trig = plan["entry"]
        for j in range(i + 1, min(n, i + 1 + fill_window)):
            if d == 1:
                if b.o[j] >= trig:
                    entry_px, fill_j = b.o[j], j
                elif b.h[j] >= trig:
                    entry_px, fill_j = trig, j
            else:
                if b.o[j] <= trig:
                    entry_px, fill_j = b.o[j], j
                elif b.l[j] <= trig:
                    entry_px, fill_j = trig, j
            if fill_j is not None:
                break
    if fill_j is None:
        return None
    entry_px *= (1 + d * slip)
    risk = (entry_px - stop) * d
    if risk <= 0:             # gapped beyond the stop on the fill: skip, counts as unfilled
        return None
    if plan["setup"] in ("oversold_bounce", "overbought_fade"):
        target = plan["targets"][0]
        if (target - entry_px) * d <= 0:
            target = entry_px + d * 0.5 * risk
    else:
        target = entry_px + d * target_r * risk
    exit_px = exit_j = None
    reason = "time"
    for j in range(fill_j, min(n, fill_j + max_hold)):
        hit_stop = (b.l[j] <= stop) if d == 1 else (b.h[j] >= stop)
        hit_tgt = (b.h[j] >= target) if d == 1 else (b.l[j] <= target)
        # bar order is unknown on daily data: a bar touching both counts as a stop
        if hit_stop:
            gap_open = (b.o[j] < stop) if d == 1 else (b.o[j] > stop)
            exit_px, exit_j, reason = (b.o[j] if gap_open and j > fill_j else stop), j, "stop"
            break
        if hit_tgt:
            gap_open = (b.o[j] > target) if d == 1 else (b.o[j] < target)
            exit_px, exit_j, reason = (b.o[j] if gap_open and j > fill_j else target), j, "target"
            break
    if exit_px is None:
        exit_j = min(n - 1, fill_j + max_hold - 1)
        if exit_j < fill_j:
            return None
        exit_px = b.c[exit_j]
        if exit_j == n - 1 and exit_j - fill_j + 1 < max_hold:
            reason = "open"
    exit_px *= (1 - d * slip)
    r = (exit_px - entry_px) * d / risk
    return {"entry_date": b.t[fill_j].date().isoformat(), "exit_date": b.t[exit_j].date().isoformat(),
            "entry": round(entry_px, 4), "exit": round(exit_px, 4), "stop": round(stop, 4),
            "r": round(r, 3), "bars": exit_j - fill_j + 1, "exit_reason": reason, "exit_j": exit_j}


def _dates_index(bars):
    return [t.date() for t in bars.t]


def _idx_at(dates, day):
    """Index of the last bar on or before day, or None."""
    k = bisect.bisect_right(dates, day) - 1
    return k if k >= 0 else None


def stats(trades):
    closed = [t for t in trades if t["exit_reason"] != "open"]
    if not closed:
        return {"n": 0}
    rs = [t["r"] for t in closed]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    eq, peak, mdd = 0.0, 0.0, 0.0
    for t in sorted(closed, key=lambda x: x["exit_date"]):
        eq += t["r"]
        peak = max(peak, eq)
        mdd = min(mdd, eq - peak)
    gl = -sum(losses)
    return {"n": len(closed), "win_rate": round(100.0 * len(wins) / len(closed), 1),
            "avg_r": round(sum(rs) / len(rs), 3), "total_r": round(sum(rs), 1),
            "avg_win": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "profit_factor": round(sum(wins) / gl, 2) if gl > 0 else None,
            "max_drawdown_r": round(mdd, 1), "avg_bars": round(sum(t["bars"] for t in closed) / len(closed), 1)}


def run(cfg, fetcher, symbols, years=5, only=None, target_r=2.0, max_hold=10, fill_window=3,
        slippage_bps=5.0, oos_frac=0.3, log=print):
    rng = "10y" if years > 5 else "5y" if years > 2 else "2y"
    sp = {}
    try:
        from . import universe
        sp = universe.sp500(fetcher)
    except Exception:
        pass
    gauges = sorted(set(regime.MARKET) | set(config.SECTOR_ETFS))
    log("loading %d symbols (%s daily)..." % (len(set(symbols) | set(gauges)), rng))
    bars = data.many(fetcher, sorted(set(symbols) | set(gauges)), data.daily, range_=rng)
    gp = {s: Pack(bars[s]) for s in gauges if s in bars and len(bars[s]) >= 70}
    gdates = {s: _dates_index(p.bars) for s, p in gp.items()}
    cutoff = datetime.date.today() - datetime.timedelta(days=int(365.25 * years))

    reg_cache, sec_cache = {}, {}

    def regime_on(day):
        if day not in reg_cache:
            idx = {s: _idx_at(gdates[s], day) for s in gp}
            reg_cache[day] = regime.market_at(gp, idx)
            secs = regime.sectors_at(gp, idx)
            sec_cache[day] = {r["etf"]: r for r in secs}
        return reg_cache[day], sec_cache[day]

    trades, unfilled, signals = [], 0, 0
    for s in symbols:
        b = bars.get(s)
        if b is None or len(b) < 260:
            continue
        p = Pack(b)
        kind = "future" if s.endswith("=F") else "etf" if (s in config.SECTOR_ETFS or s in config.INDEX_ETFS) else "stock"
        sector_etf = config.GICS_TO_ETF.get((sp.get(s) or {}).get("sector", ""))
        busy_until = {}
        for i in range(210, len(b) - 1):
            day = b.t[i].date()
            if day < cutoff:
                continue
            if kind == "stock":
                dv = p.dollar_vol20[i]
                if b.c[i] < cfg["universe"]["min_price"] or dv is None or dv < cfg["universe"]["min_avg_dollar_volume"]:
                    continue
            found = setups.detect(p, i, cfg)
            if only:
                found = [f for f in found if f["setup"] in only]
            if not found:
                continue
            mkt, secmap = regime_on(day)
            for pl in found:
                key = pl["setup"]
                if busy_until.get(key, -1) >= i:
                    continue
                signals += 1
                d = pl["direction"]
                reg_v, _ = regime.alignment(d, mkt, secmap.get(sector_etf), kind)
                tr_v, _ = setups.trend_score(p, i, d)
                pa_v, _ = setups.participation(p, i, pl.get("gap_pct"))
                sc, gr, _ = scoring.combine({"regime": reg_v, "trend": tr_v, "setup": pl["quality"],
                                             "participation": pa_v}, cfg, "future")
                res = simulate(b, i, pl, target_r, max_hold, fill_window, slippage_bps)
                if res is None:
                    unfilled += 1
                    continue
                busy_until[key] = res["exit_j"]
                res.update({"symbol": s, "setup": key, "direction": d, "signal_date": day.isoformat(),
                            "score": sc, "grade": gr, "regime": mkt["label"]})
                res.pop("exit_j", None)
                trades.append(res)
    trades.sort(key=lambda t: t["entry_date"])
    split = None
    if trades:
        k = int(len(trades) * (1 - oos_frac))
        split = trades[k]["entry_date"] if k < len(trades) else None
    by_setup = {}
    for t in trades:
        by_setup.setdefault(t["setup"], []).append(t)
    buckets = [("75+", 75, 101), ("60-75", 60, 75), ("45-60", 45, 60), ("<45", -1, 45)]
    by_score = {name: stats([t for t in trades if lo <= t["score"] < hi]) for name, lo, hi in buckets}
    by_regime = {}
    for t in trades:
        by_regime.setdefault(t["regime"], []).append(t)
    return {
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "params": {"years": years, "target_r": target_r, "max_hold": max_hold, "fill_window": fill_window,
                   "slippage_bps": slippage_bps, "symbols": len(symbols), "setups": only or "all"},
        "signals": signals, "unfilled": unfilled, "overall": stats(trades),
        "in_sample": stats([t for t in trades if split and t["entry_date"] < split]),
        "out_of_sample": stats([t for t in trades if split and t["entry_date"] >= split]),
        "oos_from": split,
        "by_setup": {k: stats(v) for k, v in sorted(by_setup.items())},
        "by_setup_oos": {k: stats([t for t in v if split and t["entry_date"] >= split]) for k, v in sorted(by_setup.items())},
        "by_score": by_score,
        "by_regime": {k: stats(v) for k, v in by_regime.items()},
        "trades": trades,
        "errors": fetcher.errors[:40],
    }


def render(res):
    out = ["BACKTEST  %s" % res["generated_at"],
           "params: %s" % ", ".join("%s=%s" % kv for kv in res["params"].items()),
           "signals %d, filled %d, unfilled %d" % (res["signals"], res["overall"].get("n", 0), res["unfilled"]), ""]

    def line(name, s):
        if not s.get("n"):
            return "  %-18s %5s" % (name, "0")
        return ("  %-18s %5d  win %5.1f%%  avg %+6.3fR  PF %5s  total %+7.1fR  maxDD %6.1fR  bars %4.1f"
                % (name, s["n"], s["win_rate"], s["avg_r"], s["profit_factor"] if s["profit_factor"] is not None else "-",
                   s["total_r"], s["max_drawdown_r"], s["avg_bars"]))
    out.append(line("ALL", res["overall"]))
    out.append(line("in-sample", res["in_sample"]))
    out.append(line("out-of-sample", res["out_of_sample"]) + ("   (from %s)" % res["oos_from"] if res["oos_from"] else ""))
    out.append("")
    out.append("by setup (all | out-of-sample):")
    for k, s in res["by_setup"].items():
        out.append(line(k, s))
        out.append(line("   oos", res["by_setup_oos"].get(k, {})))
    out.append("")
    out.append("by technical confluence score (does a higher score mean better trades?):")
    for k, s in res["by_score"].items():
        out.append(line(k, s))
    out.append("")
    out.append("by market regime at the signal:")
    for k, s in res["by_regime"].items():
        out.append(line(k, s))
    out.append("")
    out.append("Past results on free daily data, with simple fills. Treat small samples (n < 30) as noise.")
    return "\n".join(out)
