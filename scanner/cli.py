"""Command line. Run `python3 -m scanner --help`.

  premarket   morning routine: in-play + full scan + intraday levels + dashboard
  scan        swing scan of the whole universe (daily layer)
  intraday    triggers on the watchlist (5-minute layer); --loop 60 to keep watching
  inplay      just the stocks-in-play finder
  ticker      everything on one symbol, all layers
  regime      market regime and sector ranks
  backtest    test the daily setups on history, in R
  journal     review signals / log your trades / stats
  orders      hand chosen plans to the baseline trader-risk -> trader-broker flow
  dashboard   rebuild out/dashboard.html from the last saved scan
  doctor      check settings and which data sources answer
"""

import argparse
import datetime
import json
import os
import sys
import time

from . import (backtest, catalysts, config, data, fundamentals, intraday, journal, live, pipeline, regime,
               report, scoring, setups, universe)
from .indicators import Pack
from .net import Fetcher, NetError


def _fetcher(a, cfg):
    return Fetcher(cfg, offline=a.offline)


def _print_json(obj):
    print(json.dumps(obj, indent=1, default=str))


def _scan(a, cfg, f, log):
    tickers = [t.strip().upper() for t in a.tickers.split(",")] if getattr(a, "tickers", None) else None
    res = pipeline.scan(cfg, f, tickers=tickers, use_news=not a.no_news,
                        use_fundamentals=not a.no_fundamentals, use_inplay=not a.no_inplay, log=log)
    pipeline.save(res)
    with open(os.path.join(config.out_dir(), "watchlist.json"), "w", encoding="utf-8") as fh:
        json.dump(res["watchlist"], fh, indent=1, default=str)
    if not a.no_log:
        n = journal.log_signals(res)
        if n:
            log("logged %d new A/B signals to out/signals.csv" % n)
    return res


def cmd_scan(a, cfg):
    f = _fetcher(a, cfg)
    log = (lambda *x: None) if a.json else (lambda *x: print(*x, file=sys.stderr))
    res = _scan(a, cfg, f, log)
    path = report.dashboard(res, pipeline.load("intraday.json"))
    if a.json:
        _print_json(res)
    else:
        print(report.text(res, top=a.top))
        print("\ndashboard: %s" % path)


def cmd_premarket(a, cfg):
    f = _fetcher(a, cfg)
    log = (lambda *x: None) if a.json else (lambda *x: print(*x, file=sys.stderr))
    res = _scan(a, cfg, f, log)
    log("loading intraday levels for the %d-name watchlist..." % len(res["watchlist"]))
    intr = live.run(cfg, f, res["watchlist"])
    pipeline.save(intr, "intraday.json")
    path = report.dashboard(res, intr)
    with open(os.path.join(config.out_dir(), "premarket.md"), "w", encoding="utf-8") as fh:
        fh.write(report.markdown(res))
    if a.json:
        _print_json({"scan": res, "intraday": intr})
    else:
        print(report.text(res, intr, top=a.top))
        print("\ndashboard: %s" % path)


def cmd_intraday(a, cfg):
    f = _fetcher(a, cfg)
    if a.tickers:
        wl = [{"symbol": t.strip().upper(), "direction": None, "grade": None, "score": None,
               "setup": "manual", "source": "manual", "atr": None} for t in a.tickers.split(",")]
    else:
        path = os.path.join(config.out_dir(), "watchlist.json")
        if not os.path.isfile(path):
            sys.exit("no watchlist yet: run `python3 -m scanner premarket` (or scan) first, or pass --tickers")
        with open(path, encoding="utf-8") as fh:
            wl = json.load(fh)
    while True:
        f.errors.clear()
        res = live.run(cfg, f, wl)
        pipeline.save(res, "intraday.json")
        scan = pipeline.load()
        if scan:
            report.dashboard(scan, res)
        fresh = live.new_triggers(res)
        if a.json:
            _print_json(res)
        else:
            print(report.intraday_text(res))
            for r, t in fresh:
                print(">>> NEW %s%s %s %s entry %.2f stop %.2f (%s)" % (
                    "ALIGNED " if t.get("aligned") else "", r["display"], t["trigger"], t["direction"],
                    t["entry"], t["stop"], t["reasons"][0]))
                if a.bell:
                    sys.stdout.write("\a")
        if not a.loop:
            break
        if res["phase"] not in ("open", "premarket"):
            print("market %s: stopping the loop" % res["phase"])
            break
        time.sleep(max(30, a.loop))


def cmd_inplay(a, cfg):
    from .headlines import TickerMatcher
    from . import inplay
    f = _fetcher(a, cfg)
    sp = universe.sp500(f)
    names = {t: r["name"] for t, r in sp.items()}
    _t2c, c2t = catalysts.cik_map(f) if f.sec_ua else ({}, {})
    res = inplay.discover(f, TickerMatcher(names), c2t, min_price=cfg["universe"]["min_price"])
    rows = sorted(res.values(), key=lambda r: -r["score"])
    if a.json:
        _print_json({"inplay": rows, "errors": f.errors})
        return
    for r in rows[:a.top]:
        h = (r["headlines"] or [{}])[0].get("title", "")
        print("%-6s %.2f %-7s chg %s  %s  %s" % (r["ticker"], r["score"], r["bias"],
                                                 "-" if r["chg_pct"] is None else "%+.1f%%" % r["chg_pct"],
                                                 ",".join(r["catalysts"][:3]), h[:80]))
    if f.errors:
        print("\nnotes: " + " | ".join(f.errors[:8]), file=sys.stderr)


def cmd_ticker(a, cfg):
    f = _fetcher(a, cfg)
    s = a.symbol.upper()
    now = data.now_ny()
    syms = sorted({s} | set(regime.MARKET) | set(config.SECTOR_ETFS))
    bars = data.many(f, syms, data.daily)
    if s not in bars:
        sys.exit("no data for %s (%s)" % (s, "; ".join(f.errors[:3])))
    pipeline.drop_partial(bars, data.market_phase(now), now.date())
    mkt = regime.market(bars)
    secs = {r["etf"]: r for r in regime.sectors(bars)}
    sp = universe.sp500(f)
    info = sp.get(s, {})
    kind = "future" if s.endswith("=F") else "etf" if s in config.SECTOR_ETFS or s in config.INDEX_ETFS else "stock"
    sector_etf = config.GICS_TO_ETF.get(info.get("sector", ""))
    p = Pack(bars[s])
    i = len(p.bars) - 1
    t2c, _ = catalysts.cik_map(f) if f.sec_ua else ({}, {})
    items = catalysts.ticker_news(f, s, t2c, hours=96, name=info.get("name")) if kind != "future" else []
    cal = catalysts.earnings_calendar(f, now.date()) if kind == "stock" else {}
    earn = catalysts.earnings_context(s, cal, now.date())
    fm = fundamentals.metrics(f, s, t2c) if kind == "stock" else None
    found = setups.detect(p, i, cfg)
    out = {"symbol": s, "name": info.get("name"), "sector": info.get("sector"), "price": p.bars.c[i],
           "date": p.bars.t[i].date().isoformat(), "levels": setups.key_levels(p, i),
           "atr": round(p.atr14[i] or 0, 4), "rsi14": round(p.rsi14[i] or 0, 1), "adx": round(p.adx14[i] or 0, 1),
           "rvol": round(p.rvol20[i] or 0, 2), "regime": mkt["label"], "earnings": earn,
           "headlines": catalysts.items_json(items[:8]), "fundamentals": fm, "setups": []}
    for d in ("long", "short"):
        tv, tw = setups.trend_score(p, i, d)
        out["trend_" + d] = {"score": tv, "checks": tw}
    filings = [it for it in items if it.get("kind") == "filing"]
    heads = [it for it in items if it.get("kind") != "filing"]
    for pl in found:
        d = pl["direction"]
        rv, rw = regime.alignment(d, mkt, secs.get(sector_etf), kind)
        cv, cw = catalysts.catalyst_score(d, heads, earn, filings,
                                          buffer_days=cfg["setups"]["earnings_buffer_days"])
        fv, fw = fundamentals.score(d, fm) if kind == "stock" else (None, [])
        parts = {"regime": rv, "trend": setups.trend_score(p, i, d)[0], "setup": pl["quality"],
                 "participation": setups.participation(p, i, pl.get("gap_pct"))[0], "catalyst": cv,
                 "fundamentals": fv}
        sc, gr, bd = scoring.combine(parts, cfg, kind)
        out["setups"].append({"plan": pl, "score": sc, "grade": gr, "breakdown": bd,
                              "why": {"regime": rw, "catalyst": cw, "fundamentals": fw},
                              "sizing": scoring.size(pl, cfg, s), "flags": scoring.flags(pl, cfg, rv, cw)})
    try:
        ib = data.intraday(f, s, cfg["intraday"]["interval"], "1mo", True)
        spy_ib = data.intraday(f, "SPY", cfg["intraday"]["interval"], "1mo", True)
        spy_a = intraday.analyze(spy_ib, cfg)
        out["intraday"] = intraday.analyze(ib, cfg, spy_change=(spy_a or {}).get("change_pct"),
                                           daily_atr=p.atr14[i])
    except NetError as exc:
        out["intraday"] = {"error": str(exc)}
    if a.json:
        _print_json(out)
        return
    print("%s  %s  %s  close %.2f on %s" % (s, out["name"] or "", out["sector"] or "", out["price"], out["date"]))
    print("regime %s | ATR %.2f | RSI %.0f | ADX %.0f | rel vol %.1fx" % (mkt["label"], out["atr"], out["rsi14"],
                                                                        out["adx"], out["rvol"]))
    print("trend long %.2f (%s)" % (out["trend_long"]["score"], ", ".join(out["trend_long"]["checks"])))
    print("levels: " + "  ".join("%s %.2f" % kv for kv in out["levels"].items()))
    if earn:
        print("earnings: %s %s (%+d trading days)" % (earn["date"], earn["time"], earn["days"]))
    if fm:
        print("fundamentals: rev %s%% y/y, EPS %s%% y/y, op margin %s%%" % (
            fm.get("revenue_growth_yoy"), fm.get("eps_growth_yoy"), fm.get("operating_margin")))
    print()
    if not out["setups"]:
        print("no daily setup today")
    for x in out["setups"]:
        pl = x["plan"]
        print("[%s %.0f] %s %s  entry %.2f stop %.2f 2R %.2f 3R %.2f  %s" % (
            x["grade"], x["score"], pl["setup"], pl["direction"], pl["entry"], pl["stop"], pl["targets"][1],
            pl["targets"][2], report._size(x["sizing"])))
        for r in pl["reasons"] + x["why"]["regime"] + x["why"]["catalyst"] + x["why"]["fundamentals"]:
            print("    - " + r)
        if x["flags"]:
            print("    flags: " + "; ".join(x["flags"]))
    print()
    for h in out["headlines"][:6]:
        print("  [%+.2f] %s  (%s)" % (h.get("sentiment") or 0, h["title"][:100], (h.get("time") or "")[:16]))
    it = out.get("intraday") or {}
    if it and not it.get("error"):
        print()
        print("intraday %s %s: last %s, VWAP %s, levels %s" % (it["date"], it["last_time"], it["last"],
                                                             it.get("vwap"), it["levels"]))
        for t in it["triggers"] + it["plans"]:
            print("  %s %s entry %s stop %s : %s" % (t["trigger"], t["direction"], t["entry"], t["stop"],
                                                    t["reasons"][0]))


def cmd_regime(a, cfg):
    f = _fetcher(a, cfg)
    syms = sorted(set(regime.MARKET) | set(config.SECTOR_ETFS))
    bars = data.many(f, syms, data.daily)
    now = data.now_ny()
    pipeline.drop_partial(bars, data.market_phase(now), now.date())
    mkt, secs = regime.market(bars), regime.sectors(bars)
    if a.json:
        _print_json({"regime": mkt, "sectors": secs})
        return
    print("%s (%+.2f)" % (mkt["label"], mkt["score"]))
    for r in mkt["reasons"]:
        print("  - " + r)
    print()
    for s in secs:
        print("  %2d %-5s %-24s RS %+6.1f  20d %+6.1f%%  %s" % (s["rank"], s["etf"], s["sector"], s["rs"],
                                                             s["roc20"], s["status"]))


def cmd_backtest(a, cfg):
    f = _fetcher(a, cfg)
    if a.tickers:
        syms = [t.strip().upper() for t in a.tickers.split(",")]
    elif a.universe == "sp500":
        syms = sorted(universe.sp500(f))
    elif a.universe == "etfs":
        syms = list(config.INDEX_ETFS) + list(config.SECTOR_ETFS)
    elif a.universe == "futures":
        syms = list(config.FUTURES)
    else:
        syms = list(universe.NASDAQ100)
    only = [s.strip() for s in a.setups.split(",")] if a.setups else None
    res = backtest.run(cfg, f, syms, years=a.years, only=only, target_r=a.target_r, max_hold=a.max_hold,
                       fill_window=a.fill_window, slippage_bps=a.slippage,
                       log=lambda *x: print(*x, file=sys.stderr))
    pipeline.save(res, "backtest.json")
    if a.json:
        res = dict(res, trades=res["trades"][-200:])
        _print_json(res)
    else:
        print(backtest.render(res))
        print("\nall trades: out/backtest.json")


def cmd_journal(a, cfg):
    if a.action == "review":
        f = _fetcher(a, cfg)
        s = journal.review(cfg, f)
        _print_json(s) if a.json else _print_summary(s)
    elif a.action == "stats":
        s = journal.summary()
        t = journal.trade_stats()
        _print_json({"signals": s, "trades": t}) if a.json else (_print_summary(s), print("\nyour trades:", json.dumps(t, indent=1)))
    elif a.action == "add":
        for k in ("symbol", "side", "entry", "stop"):
            if getattr(a, k) is None:
                sys.exit("journal add needs --symbol --side --entry --stop")
        tid = journal.add_trade(a.symbol, a.side, a.entry, a.stop, a.target, a.size, a.setup or "",
                                a.grade or "", a.score or "", a.notes or "")
        print("logged trade #%s" % tid)
    elif a.action == "close":
        if a.id is None or a.exit is None:
            sys.exit("journal close needs --id and --exit")
        r = journal.close_trade(a.id, a.exit, a.followed or "", a.notes or "")
        print("closed #%s at %s: %sR" % (r["id"], r["exit"], r["r"]))


def _print_summary(s):
    print("signals logged %d | pending %d | open %d | no fill %d" % (s["signals"], s["pending"], s["open"], s["no_fill"]))
    for k in ("all", "grade_A", "grade_B"):
        v = s.get(k) or {}
        if v.get("n"):
            print("  %-8s n=%d win %.1f%% avg %+.2fR total %+.1fR" % (k, v["n"], v["win_rate"], v["avg_r"], v["total_r"]))
    for k, v in (s.get("by_setup") or {}).items():
        if v.get("n"):
            print("  %-16s n=%d win %.1f%% avg %+.2fR" % (k, v["n"], v["win_rate"], v["avg_r"]))


def cmd_orders(a, cfg):
    """Write chosen plans as stop orders to trader/orders.json for trader-risk / trader-broker.
    Long stock/ETF plans only (the baseline risk check does not allow shorts or futures)."""
    scan = pipeline.load()
    if not scan:
        sys.exit("no scan yet: run `python3 -m scanner scan` first")
    picks = [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None
    orders, skipped = [], []
    for c in scan["candidates"]:
        if picks is not None and c["display"] not in picks and c["symbol"] not in picks:
            continue
        if picks is None and c["grade"] != "A":
            continue
        p, sz = c["plan"], c.get("sizing") or {}
        if c["kind"] == "future" or p["direction"] != "long" or p.get("entry_type") != "stop":
            skipped.append("%s %s %s" % (c["display"], p["setup"], p["direction"]))
            continue
        if not sz.get("shares"):
            skipped.append("%s: size 0" % c["display"])
            continue
        orders.append({"symbol": c["symbol"], "side": "buy", "qty": str(sz["shares"]), "type": "stop",
                       "stop_price": "%.2f" % p["entry"], "time_in_force": "day",
                       "why": "confluence %s %.0f %s; plan stop %.2f, 2R %.2f" % (
                           c["grade"], c["score"], p["setup"], p["stop"], p["targets"][1])})
        if picks is None and len(orders) >= a.max:
            break
    if not orders:
        sys.exit("nothing to export%s" % (" (skipped: %s)" % "; ".join(skipped) if skipped else ""))
    os.makedirs(os.path.join(config.ROOT, "trader"), exist_ok=True)
    path = os.path.join(config.ROOT, "trader", "orders.json")
    doc = {"created_by": "confluence-scanner", "created_at": datetime.datetime.now().replace(microsecond=0).isoformat(),
           "status": "proposed", "paper": bool(cfg.get("paper", True)),
           "note": "Proposals only. Nothing is placed until trader-risk passes each order and you say yes in the chat. "
                   "Protective stops are NOT attached: place your stop right after any fill.",
           "source": "out/scan.json", "orders": orders}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
    print("wrote %d proposed orders to trader/orders.json" % len(orders))
    for o in orders:
        print("  buy %s %s, stop entry %s (%s)" % (o["qty"], o["symbol"], o["stop_price"], o["why"]))
    if skipped:
        print("skipped (not exportable): " + "; ".join(skipped))
    print("next: /trader-risk, then /trader-broker. Nothing is placed without your yes.")


def cmd_dashboard(a, cfg):
    scan = pipeline.load()
    if not scan:
        sys.exit("no saved scan")
    print(report.dashboard(scan, pipeline.load("intraday.json")))


def cmd_doctor(a, cfg):
    f = _fetcher(a, cfg)
    print("python %s" % sys.version.split()[0])
    print("config: %s" % ("config.json" if os.path.isfile(os.path.join(config.ROOT, "config.json")) else "defaults (copy config.example.json to config.json)"))
    print("SEC user agent: %s" % ("set" if f.sec_ua else "MISSING (8-Ks, fundamentals and the live 8-K feed are skipped)"))
    print("account $%s, risk %s%% per trade" % (cfg["account_size"], cfg["risk_per_trade_pct"]))
    checks = [("Yahoo daily bars", lambda: data.daily(f, "SPY")),
              ("Yahoo intraday bars", lambda: data.intraday(f, "SPY")),
              ("Nasdaq earnings calendar", lambda: f.json(catalysts.NASDAQ_EARNINGS % datetime.date.today().isoformat(),
                                                          "doctor_earn", ttl=0, headers=catalysts.NASDAQ_HEADERS)),
              ("Yahoo headlines RSS", lambda: f.get(catalysts.YAHOO_RSS % "AAPL", "doctor_rss", ttl=0))]
    if f.sec_ua:
        checks.append(("SEC EDGAR", lambda: f.get(catalysts.SEC_CURRENT, "doctor_sec", ttl=0, sec=True)))
    for name, fn in checks:
        try:
            fn()
            print("  ok   %s" % name)
        except Exception as exc:
            print("  FAIL %s: %s" % (name, exc))


def build_parser():
    ap = argparse.ArgumentParser(prog="python3 -m scanner", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", metavar="DIR", help="answer every request from fixture files in DIR")
    ap.add_argument("--config", help="path to config.json")
    sub = ap.add_subparsers(dest="cmd")

    def scan_opts(p):
        p.add_argument("--tickers", help="comma list instead of the full universe")
        p.add_argument("--no-news", action="store_true")
        p.add_argument("--no-fundamentals", action="store_true")
        p.add_argument("--no-inplay", action="store_true")
        p.add_argument("--no-log", action="store_true", help="do not log A/B signals to out/signals.csv")
        p.add_argument("--top", type=int, default=15)
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("scan", help="swing scan (daily layer)")
    scan_opts(p)
    p.set_defaults(fn=cmd_scan)
    p = sub.add_parser("premarket", help="morning routine: scan + in-play + intraday levels")
    scan_opts(p)
    p.set_defaults(fn=cmd_premarket)
    p = sub.add_parser("intraday", help="intraday triggers on the watchlist")
    p.add_argument("--tickers")
    p.add_argument("--loop", type=int, default=0, metavar="SECONDS", help="re-check every N seconds (min 30)")
    p.add_argument("--bell", action="store_true", help="terminal bell on new triggers")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_intraday)
    p = sub.add_parser("inplay", help="stocks in play from news, screeners and 8-Ks")
    p.add_argument("--top", type=int, default=25)
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_inplay)
    p = sub.add_parser("ticker", help="all layers for one symbol")
    p.add_argument("symbol")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_ticker)
    p = sub.add_parser("regime", help="market regime + sector ranks")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_regime)
    p = sub.add_parser("backtest", help="backtest the daily setups")
    p.add_argument("--tickers")
    p.add_argument("--universe", choices=["nasdaq100", "sp500", "etfs", "futures"], default="nasdaq100")
    p.add_argument("--years", type=int, default=5)
    p.add_argument("--setups", help="comma list, e.g. breakout,pullback")
    p.add_argument("--target-r", type=float, default=2.0)
    p.add_argument("--max-hold", type=int, default=10)
    p.add_argument("--fill-window", type=int, default=3)
    p.add_argument("--slippage", type=float, default=5.0, help="bps per side")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_backtest)
    p = sub.add_parser("journal", help="signals track record and your trade log")
    p.add_argument("action", choices=["review", "stats", "add", "close"])
    for k in ("symbol", "side", "setup", "grade", "score", "notes", "followed"):
        p.add_argument("--" + k)
    for k in ("entry", "stop", "target", "size", "exit"):
        p.add_argument("--" + k, type=float)
    p.add_argument("--id")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_journal)
    p = sub.add_parser("orders", help="export plans to trader/orders.json for trader-risk")
    p.add_argument("--symbols", help="comma list of symbols from the last scan (default: A grades)")
    p.add_argument("--max", type=int, default=3)
    p.set_defaults(fn=cmd_orders)
    p = sub.add_parser("dashboard", help="rebuild the HTML dashboard")
    p.set_defaults(fn=cmd_dashboard)
    p = sub.add_parser("doctor", help="check settings and data sources")
    p.set_defaults(fn=cmd_doctor)
    return ap


def main(argv=None):
    ap = build_parser()
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        ap.print_help()
        return 1
    cfg = config.load(a.config)
    a.fn(a, cfg)
    return 0
