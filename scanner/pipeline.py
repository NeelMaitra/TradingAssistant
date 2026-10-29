"""The scan, start to finish.

  1. find today's stocks in play (news feeds, screeners, live 8-Ks)
  2. load daily bars for the universe + in-play names + market gauges
  3. regime: market score, breadth, sector ranks
  4. detect setups on the last completed daily bar for every symbol
  5. preliminary score (regime, trend, setup, participation) for everything
  6. for the shortlist: earnings calendar, headlines + 8-Ks, SEC fundamentals
  7. final confluence score, grade, sizing, flags; build the intraday watchlist
"""

import datetime
import json
import os

from . import catalysts, config, data, fundamentals, inplay, regime, scoring, setups, universe
from .headlines import TickerMatcher
from .indicators import Pack


def _today_ny():
    return data.now_ny().date()


def drop_partial(bars_map, phase, today):
    """Swing setups use completed daily bars only: drop today's bar before the close."""
    if phase not in ("premarket", "open"):
        return
    for s, b in bars_map.items():
        if len(b) and b.t[-1].date() >= today:
            bars_map[s] = b.slice(0, len(b) - 1)


def liquid(info, b, p, cfg):
    if info.get("kind") != "stock":
        return True
    u = cfg["universe"]
    if b.c[-1] < u["min_price"]:
        return False
    dv = p.dollar_vol20[-1]
    if dv is None or dv < u["min_avg_dollar_volume"]:
        return False
    a = p.atr14[-1]
    return a is not None and 100.0 * a / b.c[-1] >= u.get("min_atr_pct", 0.8)


def scan(cfg, fetcher, tickers=None, use_news=True, use_fundamentals=True, use_inplay=True,
         now=None, log=print):
    now = now or data.now_ny()
    today = now.date()
    phase = data.market_phase(now)
    errors = fetcher.errors

    # ---------- universe and in-play discovery
    sp = universe.sp500(fetcher)
    names = {t: r["name"] for t, r in sp.items()}
    for t in universe.NASDAQ100:
        names.setdefault(t, t)
    t2c, c2t = catalysts.cik_map(fetcher) if fetcher.sec_ua else ({}, {})
    inplay_map = {}
    if use_inplay and not tickers:
        log("finding stocks in play (news feeds, screeners, live 8-Ks)...")
        inplay_map = inplay.discover(fetcher, TickerMatcher(names), c2t,
                                     now=now.astimezone(datetime.timezone.utc),
                                     min_price=cfg["universe"]["min_price"])
    if tickers:
        uni = {t.upper(): {"kind": "future" if t.upper().endswith("=F") else
                           ("etf" if t.upper() in config.SECTOR_ETFS or t.upper() in config.INDEX_ETFS else "stock"),
                           "name": names.get(t.upper(), t.upper()),
                           "sector": (sp.get(t.upper()) or {}).get("sector", ""),
                           "sector_etf": config.GICS_TO_ETF.get((sp.get(t.upper()) or {}).get("sector", ""))}
               for t in tickers}
    else:
        extra = [t for t, r in sorted(inplay_map.items(), key=lambda kv: -kv[1]["score"])[:60]]
        uni = universe.build(cfg, fetcher, extra=extra)

    # ---------- daily bars
    gauges = set(regime.MARKET) | set(config.SECTOR_ETFS)
    symbols = sorted(set(uni) | gauges)
    log("loading daily bars for %d symbols..." % len(symbols))
    bars = data.many(fetcher, symbols, data.daily)
    drop_partial(bars, phase, today)
    last_date = max((b.last_date() for b in bars.values() if len(b)), default=None)

    # ---------- regime
    packs = {s: Pack(b) for s, b in bars.items() if len(b) >= 60}
    stock_packs = [p for s, p in packs.items() if uni.get(s, {}).get("kind") == "stock"]
    br = regime.breadth(stock_packs)
    mkt = regime.market(bars, breadth=br)
    secs = regime.sectors(bars)
    sec_by_etf = {r["etf"]: r for r in secs}

    # ---------- setups + preliminary scores
    cands = []
    for s, info in uni.items():
        p = packs.get(s)
        if p is None or not liquid(info, p.bars, p, cfg):
            continue
        i = len(p.bars) - 1
        for pl in setups.detect(p, i, cfg):
            d = pl["direction"]
            reg_v, reg_why = regime.alignment(d, mkt, sec_by_etf.get(info.get("sector_etf")), info["kind"])
            tr_v, tr_why = setups.trend_score(p, i, d)
            pa_v, rv = setups.participation(p, i, pl.get("gap_pct"))
            parts = {"regime": reg_v, "trend": tr_v, "setup": pl["quality"], "participation": pa_v,
                     "catalyst": None, "fundamentals": None}
            sc, gr, bd = scoring.combine(parts, cfg, info["kind"])
            cands.append({"symbol": s, "display": universe.display(s), "kind": info["kind"],
                          "name": info.get("name"), "sector": info.get("sector"),
                          "sector_etf": info.get("sector_etf"), "price": round(p.bars.c[i], 4),
                          "date": p.bars.t[i].date().isoformat(), "plan": pl, "parts": parts,
                          "why": {"regime": reg_why, "trend": tr_why, "setup": pl["reasons"],
                                  "participation": ["rel. volume %.1fx" % rv]},
                          "score": sc, "grade": gr, "breakdown": bd, "checked": False,
                          "levels": setups.key_levels(p, i), "inplay": inplay_map.get(s),
                          "atr": round(p.atr14[i], 4)})
    cands.sort(key=lambda c: c["score"], reverse=True)

    # ---------- deep checks on the shortlist
    n_short = cfg["fundamentals_shortlist"]
    short = cands[:n_short] + [c for c in cands[n_short:] if c["inplay"] and c["inplay"]["score"] >= 0.4]
    cal = {}
    if use_news and short:
        log("checking the earnings calendar...")
        cal = catalysts.earnings_calendar(fetcher, today)
    news_cache, fund_cache = {}, {}
    if short:
        log("checking news, 8-Ks and fundamentals for %d shortlisted setups..." % len(short))
    for c in short:
        s, d = c["symbol"], c["plan"]["direction"]
        swing = not c["plan"]["setup"].startswith(("gap_go", "gap_down"))
        if c["kind"] != "future" and use_news:
            if s not in news_cache:
                news_cache[s] = catalysts.ticker_news(fetcher, s, t2c, hours=72, name=c.get("name"),
                                                      now=now.astimezone(datetime.timezone.utc))
            items = news_cache[s]
            earn = catalysts.earnings_context(s, cal, today)
            filings = [it for it in items if it.get("kind") == "filing"]
            heads = [it for it in items if it.get("kind") != "filing"]
            if c["inplay"]:
                for f in c["inplay"].get("filings") or []:
                    filings.insert(0, {"important": True, "labels": f["labels"], "items": f["items"]})
                for h in c["inplay"]["headlines"]:
                    heads.append({"title": h["title"], "sentiment": h["sentiment"], "catalysts": [],
                                  "link": h.get("link")})
            cv, cwhy = catalysts.catalyst_score(d, heads, earn, filings, swing=swing,
                                                buffer_days=cfg["setups"]["earnings_buffer_days"])
            c["parts"]["catalyst"] = cv
            c["why"]["catalyst"] = cwhy or ["no fresh news"]
            c["earnings"] = earn
            c["headlines"] = [{"title": it["title"], "link": it.get("link"), "sentiment": it.get("sentiment"),
                               "source": it.get("source"), "kind": it.get("kind"),
                               "time": it["time"].isoformat() if it.get("time") else None}
                              for it in items[:5]]
        if c["kind"] == "stock" and use_fundamentals:
            if s not in fund_cache:
                fund_cache[s] = fundamentals.metrics(fetcher, s, t2c)
            fv, fwhy = fundamentals.score(d, fund_cache[s])
            c["parts"]["fundamentals"] = fv
            c["why"]["fundamentals"] = fwhy
            c["fundamentals"] = fund_cache[s]
        c["score"], c["grade"], c["breakdown"] = scoring.combine(c["parts"], cfg, c["kind"])
        c["checked"] = True

    for c in cands:
        c["sizing"] = scoring.size(c["plan"], cfg, c["symbol"])
        c["flags"] = scoring.flags(c["plan"], cfg, c["parts"]["regime"], c["why"].get("catalyst", []))
        if not (c["sizing"].get("shares") or c["sizing"].get("contracts")):
            c["flags"].append("size 0 at your risk budget")
        if not c["checked"] and c["kind"] != "future":
            c["flags"].append("news/fundamentals not checked (outside shortlist)")
    cands.sort(key=lambda c: (c["checked"] or c["kind"] == "future", c["score"]), reverse=True)

    # ---------- in-play table, joined with daily stats
    ip_rows = []
    for t, r in sorted(inplay_map.items(), key=lambda kv: -kv[1]["score"]):
        p = packs.get(t)
        row = dict(r)
        if p is not None:
            i = len(p.bars) - 1
            row["price"] = round(p.bars.c[i], 2)
            row["daily_rvol"] = round(p.rvol20[i], 2) if p.rvol20[i] else None
            row["atr_pct"] = round(100 * p.atr14[i] / p.bars.c[i], 2) if p.atr14[i] else None
            tr_l, _ = setups.trend_score(p, i, "long")
            row["trend"] = "up" if tr_l >= 0.65 else "down" if tr_l <= 0.35 else "mixed"
        row["setups"] = [c["plan"]["setup"] for c in cands if c["symbol"] == t]
        ip_rows.append(row)
    # the universe's own movers count as in play too (big gap or volume on the last bar)
    for s, p in packs.items():
        if s in inplay_map or uni.get(s, {}).get("kind") != "stock":
            continue
        i = len(p.bars) - 1
        gap = 100 * (p.bars.o[i] / p.bars.c[i - 1] - 1) if p.bars.c[i - 1] else 0
        rv = p.rvol20[i] or 0
        if abs(gap) >= cfg["setups"]["gap_pct"] and rv >= 2 or rv >= 3:
            ip_rows.append({"ticker": s, "score": round(min(1.0, abs(gap) / 10 + rv / 8), 3),
                            "bias": "long" if gap > 0 else "short", "sources": ["volume/gap"],
                            "chg_pct": round(gap, 2), "daily_rvol": round(rv, 2), "price": round(p.bars.c[i], 2),
                            "headlines": [], "catalysts": [], "mentions": 0,
                            "setups": [c["plan"]["setup"] for c in cands if c["symbol"] == s]})
    ip_rows.sort(key=lambda r: r["score"], reverse=True)

    # ---------- intraday watchlist: best graded setups + top in-play + index futures
    wl = []
    for c in cands:
        if c["grade"] in ("A", "B") and c["symbol"] not in [w["symbol"] for w in wl]:
            wl.append({"symbol": c["symbol"], "direction": c["plan"]["direction"], "grade": c["grade"],
                       "score": c["score"], "setup": c["plan"]["setup"], "daily_plan": c["plan"],
                       "atr": c["atr"], "source": "daily setup"})
    n = cfg["intraday"]["watchlist_size"]
    wl = wl[:n]
    for r in ip_rows[:8]:
        if r["ticker"] not in [w["symbol"] for w in wl]:
            wl.append({"symbol": r["ticker"], "direction": r.get("bias"), "grade": None, "score": None,
                       "setup": "in play", "source": "in play", "atr": None})
    for f in ("MES=F", "MNQ=F"):
        if cfg["universe"].get("futures", True) and f not in [w["symbol"] for w in wl]:
            fc = next((c for c in cands if c["symbol"] == f), None)
            wl.append({"symbol": f, "direction": fc["plan"]["direction"] if fc else None,
                       "grade": fc["grade"] if fc else None, "score": fc["score"] if fc else None,
                       "setup": fc["plan"]["setup"] if fc else "index future", "source": "futures",
                       "atr": fc["atr"] if fc else (round(packs[f].atr14[-1], 4) if f in packs and packs[f].atr14[-1] else None)})

    return {
        "generated_at": now.isoformat(timespec="seconds"), "phase": phase,
        "bars_through": last_date.isoformat() if last_date else None,
        "universe_size": len(uni), "loaded": len(bars), "regime": mkt, "sectors": secs,
        "breadth": br, "candidates": cands, "inplay": ip_rows[:40], "watchlist": wl,
        "earnings_today": sorted([t for t, e in cal.items() if e["date"] == today.isoformat()]),
        "errors": errors[:60], "error_count": len(errors),
        "settings": {"account_size": cfg["account_size"], "risk_per_trade_pct": cfg["risk_per_trade_pct"]},
    }


def save(result, name="scan.json"):
    path = os.path.join(config.out_dir(), name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, default=str)
    return path


def load(name="scan.json"):
    path = os.path.join(config.out_dir(), name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)
