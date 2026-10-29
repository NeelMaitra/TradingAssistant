"""Runs the intraday layer over the watchlist and lines it up with the daily layer.

The strongest signal is confluence across layers: a daily A/B setup whose
intraday trigger fires in the same direction while the stock is on the right
side of VWAP and beating SPY. Those are marked "aligned".
"""

import json
import os

from . import config, data, intraday, scoring, universe


def _state_path():
    return os.path.join(config.out_dir(), "intraday_state.json")


def run(cfg, fetcher, watchlist, now=None):
    now = now or data.now_ny()
    syms = [w["symbol"] for w in watchlist]
    ic = cfg["intraday"]
    want = sorted(set(syms) | {"SPY"})
    bars = data.many(fetcher, want, data.intraday, interval=ic["interval"], range_="1mo", prepost=True)
    spy = intraday.analyze(bars["SPY"], cfg) if "SPY" in bars else None
    spy_chg = spy.get("change_pct") if spy else None
    rows = []
    for w in watchlist:
        b = bars.get(w["symbol"])
        if b is None:
            continue
        a = intraday.analyze(b, cfg, spy_change=spy_chg, daily_atr=w.get("atr"))
        if a is None:
            continue
        a["display"] = universe.display(w["symbol"])
        a["daily"] = {k: w.get(k) for k in ("direction", "grade", "score", "setup", "source")}
        best = None
        for t in a["triggers"]:
            t["aligned"] = bool(w.get("direction") == t["direction"] and w.get("grade") in ("A", "B"))
            q = a.get("score_long") if t["direction"] == "long" else a.get("score_short")
            t["intraday_quality"] = q
            t["sizing"] = scoring.size(dict(t, entry=t["entry"]), cfg, w["symbol"])
            rank = (t["aligned"], q or 0)
            if best is None or rank > best[0]:
                best = (rank, t)
        a["best"] = best[1] if best else None
        for pl in a["plans"]:
            pl["sizing"] = scoring.size(pl, cfg, w["symbol"])
        rows.append(a)
    rows.sort(key=lambda r: ((r["best"] or {}).get("aligned", False),
                             (r["best"] or {}).get("intraday_quality") or 0), reverse=True)
    return {"generated_at": now.isoformat(timespec="seconds"), "phase": data.market_phase(now),
            "spy": spy, "rows": rows, "errors": fetcher.errors[:30]}


def new_triggers(result):
    """Triggers not seen earlier today (for alerts in --loop mode)."""
    path = _state_path()
    try:
        with open(path, encoding="utf-8") as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    day = result["generated_at"][:10]
    if st.get("day") != day:
        st = {"day": day, "seen": []}
    fresh = []
    for r in result["rows"]:
        for t in r["triggers"]:
            key = "%s|%s" % (r["symbol"], t["trigger"])
            if key not in st["seen"]:
                st["seen"].append(key)
                fresh.append((r, t))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(st, fh)
    return fresh
