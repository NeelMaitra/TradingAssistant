"""Two logs that make the tool something you can trade consistently:

  out/signals.csv  every A/B signal each scan produced (automatic). `journal review`
                   grades them later against real prices with the backtest's rules,
                   so the scanner keeps a live, forward-tested track record.
  out/trades.csv   the trades you actually took (`journal add` / `journal close`),
                   with grade and setup, so you can see whether you follow the A's
                   and how your execution compares with the signals.
"""

import csv
import datetime
import os

from . import config, data
from .backtest import simulate, stats

SIGNAL_FIELDS = ["date", "symbol", "setup", "direction", "grade", "score", "entry", "stop", "t1", "t2", "t3",
                 "entry_type", "flags", "status", "fill_date", "fill", "exit_date", "exit", "r", "exit_reason"]
TRADE_FIELDS = ["id", "opened", "symbol", "side", "setup", "grade", "score", "entry", "stop", "target", "size",
                "closed", "exit", "r", "pnl", "followed_plan", "notes"]


def _path(name):
    return os.path.join(config.out_dir(), name)


def _read(name, fields):
    p = _path(name)
    if not os.path.isfile(p):
        return []
    with open(p, newline="", encoding="utf-8") as fh:
        return [dict(r) for r in csv.DictReader(fh)]


def _write(name, fields, rows):
    p = _path(name)
    tmp = p + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    os.replace(tmp, p)


def log_signals(scan, grades=("A", "B")):
    """Append this scan's A/B setups (once per symbol/setup/date)."""
    rows = _read("signals.csv", SIGNAL_FIELDS)
    have = {(r["date"], r["symbol"], r["setup"]) for r in rows}
    added = 0
    for c in scan["candidates"]:
        if c["grade"] not in grades:
            continue
        p = c["plan"]
        key = (c["date"], c["symbol"], p["setup"])
        if key in have:
            continue
        have.add(key)
        rows.append({"date": c["date"], "symbol": c["symbol"], "setup": p["setup"], "direction": p["direction"],
                     "grade": c["grade"], "score": c["score"], "entry": p["entry"], "stop": p["stop"],
                     "t1": p["targets"][0], "t2": p["targets"][1], "t3": p["targets"][2],
                     "entry_type": p.get("entry_type", "stop"), "flags": "; ".join(c["flags"]), "status": "pending"})
        added += 1
    if added:
        _write("signals.csv", SIGNAL_FIELDS, rows)
    return added


def review(cfg, fetcher, target_r=2.0, max_hold=10, fill_window=3):
    """Grade pending/open signals against the daily bars that came after them."""
    rows = _read("signals.csv", SIGNAL_FIELDS)
    todo = [r for r in rows if r["status"] in ("pending", "open")]
    bars = data.many(fetcher, sorted({r["symbol"] for r in todo}), data.daily, range_="6mo")
    for r in todo:
        b = bars.get(r["symbol"])
        if b is None:
            continue
        day = datetime.date.fromisoformat(r["date"])
        idx = [k for k, t in enumerate(b.t) if t.date() == day]
        if not idx:
            continue
        i = idx[0]
        plan = {"direction": r["direction"], "entry": float(r["entry"]), "stop": float(r["stop"]),
                "targets": [float(r["t1"]), float(r["t2"]), float(r["t3"])], "setup": r["setup"],
                "entry_type": r.get("entry_type") or "stop"}
        res = simulate(b, i, plan, target_r, max_hold, fill_window, slippage_bps=0)
        if res is None:
            waited = len(b) - 1 - i
            if waited >= fill_window:
                r["status"] = "no fill"
            continue
        r.update({"fill_date": res["entry_date"], "fill": res["entry"], "exit_date": res["exit_date"],
                  "exit": res["exit"], "r": res["r"], "exit_reason": res["exit_reason"],
                  "status": "open" if res["exit_reason"] == "open" else "closed"})
    _write("signals.csv", SIGNAL_FIELDS, rows)
    return summary(rows)


def summary(rows=None):
    rows = rows if rows is not None else _read("signals.csv", SIGNAL_FIELDS)
    closed = [{"r": float(r["r"]), "bars": 1, "exit_reason": r["exit_reason"], "exit_date": r["exit_date"],
               "grade": r["grade"], "setup": r["setup"]} for r in rows if r["status"] == "closed" and r["r"]]
    out = {"signals": len(rows), "pending": sum(r["status"] == "pending" for r in rows),
           "open": sum(r["status"] == "open" for r in rows), "no_fill": sum(r["status"] == "no fill" for r in rows),
           "all": stats(closed)}
    for g in ("A", "B"):
        out["grade_" + g] = stats([t for t in closed if t["grade"] == g])
    out["by_setup"] = {}
    for t in closed:
        out["by_setup"].setdefault(t["setup"], []).append(t)
    out["by_setup"] = {k: stats(v) for k, v in out["by_setup"].items()}
    return out


# ------------------------------------------------------------- your trades

def add_trade(symbol, side, entry, stop, target=None, size=None, setup="", grade="", score="", notes=""):
    rows = _read("trades.csv", TRADE_FIELDS)
    nid = str(max([int(r["id"]) for r in rows if r["id"].isdigit()] or [0]) + 1)
    rows.append({"id": nid, "opened": datetime.date.today().isoformat(), "symbol": symbol.upper(),
                 "side": side, "setup": setup, "grade": grade, "score": score, "entry": entry, "stop": stop,
                 "target": target or "", "size": size or "", "notes": notes})
    _write("trades.csv", TRADE_FIELDS, rows)
    return nid


def close_trade(tid, exit_price, followed_plan="", notes=""):
    rows = _read("trades.csv", TRADE_FIELDS)
    for r in rows:
        if r["id"] == str(tid):
            e, s, x = float(r["entry"]), float(r["stop"]), float(exit_price)
            d = 1 if r["side"] in ("long", "buy") else -1
            risk = abs(e - s)
            r["closed"] = datetime.date.today().isoformat()
            r["exit"] = x
            r["r"] = round((x - e) * d / risk, 3) if risk else ""
            if r.get("size"):
                try:
                    r["pnl"] = round((x - e) * d * float(r["size"]), 2)
                except ValueError:
                    pass
            r["followed_plan"] = followed_plan
            if notes:
                r["notes"] = (r.get("notes") + " | " if r.get("notes") else "") + notes
            _write("trades.csv", TRADE_FIELDS, rows)
            return r
    raise KeyError("no trade with id %s" % tid)


def trade_stats():
    rows = [r for r in _read("trades.csv", TRADE_FIELDS) if r.get("closed") and r.get("r") not in ("", None)]
    closed = [{"r": float(r["r"]), "bars": 1, "exit_reason": "closed", "exit_date": r["closed"],
               "grade": r.get("grade")} for r in rows]
    out = {"all": stats(closed)}
    for g in ("A", "B", "C", ""):
        sub = [t for t in closed if (t["grade"] or "") == g]
        if sub:
            out["grade_" + (g or "none")] = stats(sub)
    followed = [float(r["r"]) for r in rows if r.get("followed_plan", "").lower() in ("y", "yes", "true")]
    broke = [float(r["r"]) for r in rows if r.get("followed_plan", "").lower() in ("n", "no", "false")]
    if followed:
        out["followed_plan_avg_r"] = round(sum(followed) / len(followed), 3)
    if broke:
        out["broke_plan_avg_r"] = round(sum(broke) / len(broke), 3)
    return out
