"""Offline tests. Run: python3 -m unittest discover -s tests -v

Every network request is answered from tests/fixtures (see make_fixtures.py),
with the clock pinned to 2026-10-14 10:35 ET.
"""

import datetime
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIX = os.path.join(ROOT, "tests", "fixtures")
CFG = os.path.join(ROOT, "tests", "fixture_config.json")
os.environ["CONFLUENCE_NOW"] = "2026-10-14T10:35:00-04:00"
os.environ["CONFLUENCE_OFFLINE"] = FIX

if not os.path.isfile(os.path.join(FIX, "sec_current_8k.atom")):   # generated, not committed
    sys.path.insert(0, os.path.join(ROOT, "tests"))
    import make_fixtures
    make_fixtures.main()

from scanner import (backtest, baseline, catalysts, config, data, headlines, indicators, intraday,  # noqa: E402
                     journal, live, pipeline, regime, scoring, setups)
from scanner.net import Fetcher  # noqa: E402


def fetcher():
    return Fetcher(config.load(CFG), offline=FIX)


class TempOut(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["CONFLUENCE_OUT"] = self.tmp

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("CONFLUENCE_OUT", None)


class TestIndicators(unittest.TestCase):
    def test_sma_ema(self):
        xs = [1, 2, 3, 4, 5, 6]
        self.assertEqual(indicators.sma(xs, 3), [None, None, 2.0, 3.0, 4.0, 5.0])
        e = indicators.ema(xs, 3)
        self.assertIsNone(e[1])
        self.assertAlmostEqual(e[2], 2.0)
        self.assertAlmostEqual(e[3], 3.0)

    def test_rsi_bounds(self):
        up = list(range(1, 40))
        self.assertEqual(indicators.rsi(up, 14)[-1], 100.0)
        down = list(range(40, 1, -1))
        self.assertLess(indicators.rsi(down, 14)[-1], 1.0)

    def test_rvol_excludes_today(self):
        v = [100] * 20 + [300]
        self.assertAlmostEqual(indicators.rvol(v, 20)[-1], 3.0)

    def test_no_lookahead(self):
        f = fetcher()
        b = data.daily(f, "AAPL")
        full = indicators.Pack(b)
        cut = indicators.Pack(b.slice(0, 400))
        for name in ("ema20", "sma50", "atr14", "rsi14", "adx14", "rvol20"):
            self.assertAlmostEqual(getattr(full, name)[399], getattr(cut, name)[399], places=8, msg=name)


class TestSetups(unittest.TestCase):
    def setUp(self):
        self.f = fetcher()
        self.cfg = self.f.cfg

    def found(self, sym):
        p = indicators.Pack(data.daily(self.f, sym))
        return {d["setup"]: d for d in setups.detect(p, len(p.bars) - 1, self.cfg)}

    def test_engineered_setups(self):
        self.assertIn("breakout", self.found("AAPL"))
        self.assertIn("pullback", self.found("NVDA"))
        self.assertIn("episodic_pivot", self.found("TSLA"))
        self.assertIn("breakdown", self.found("INTC"))
        self.assertIn("oversold_bounce", self.found("KO"))

    def test_plan_geometry(self):
        for sym in ("AAPL", "NVDA", "TSLA", "INTC"):
            for d in self.found(sym).values():
                sign = 1 if d["direction"] == "long" else -1
                self.assertGreater((d["entry"] - d["stop"]) * sign, 0, sym)
                self.assertAlmostEqual(d["targets"][1], d["entry"] + sign * 2 * d["risk_per_share"], places=3)
                self.assertTrue(0 <= d["quality"] <= 1)
                self.assertLessEqual(d["risk_atr"], 2.51)


class TestHeadlines(unittest.TestCase):
    def test_score_direction(self):
        self.assertGreater(headlines.score("Acme beats estimates and raises full-year guidance")[0], 0.5)
        self.assertLess(headlines.score("Acme misses, cuts guidance; shares plunge")[0], -0.5)
        self.assertLess(headlines.score("FDA rejects Acme drug in complete response letter")[0], -0.4)
        self.assertEqual(headlines.score("Acme to host investor day")[0], 0.0)

    def test_matcher(self):
        m = headlines.TickerMatcher({"NVDA": "Nvidia", "AAPL": "Apple Inc.", "TGT": "Target Corporation",
                                     "META": "Meta Platforms"})
        self.assertEqual(m.find("Nvidia wins a deal"), ["NVDA"])
        self.assertEqual(m.find("Shares of $AAPL rise"), ["AAPL"])
        self.assertEqual(m.find("Acme (NASDAQ: ACME) jumps"), ["ACME"])
        self.assertEqual(m.find("Analysts raise target on Meta"), ["META"])   # 'Target' is ambiguous
        self.assertEqual(m.find("Target hit for the index"), [])


class TestCatalysts(unittest.TestCase):
    def test_earnings_calendar(self):
        f = fetcher()
        cal = catalysts.earnings_calendar(f, datetime.date(2026, 10, 14))
        ko = catalysts.earnings_context("KO", cal, datetime.date(2026, 10, 14))
        self.assertEqual(ko["days"], 2)
        ts = catalysts.earnings_context("TSLA", cal, datetime.date(2026, 10, 14))
        self.assertEqual(ts["days"], -1)

    def test_earnings_penalty_for_swing(self):
        earn = {"days": 2, "date": "2026-10-16", "time": "before open"}
        s_swing, why = catalysts.catalyst_score("long", [], earn, swing=True)
        s_day, _ = catalysts.catalyst_score("long", [], earn, swing=False)
        self.assertLess(s_swing, s_day)
        self.assertTrue(any("binary risk" in w for w in why))

    def test_current_8k_feed(self):
        f = fetcher()
        _t2c, c2t = catalysts.cik_map(f)
        items = catalysts.current_8k(f, c2t)
        self.assertEqual(items[0]["ticker"], "AAPL")
        self.assertIn("2.02", items[0]["items"])
        self.assertTrue(items[0]["important"])


class TestScoring(unittest.TestCase):
    def test_reweights_missing_components(self):
        cfg = config.load(CFG)
        parts = {"regime": 1, "trend": 1, "setup": 1, "participation": 1, "catalyst": None, "fundamentals": None}
        sc, gr, bd = scoring.combine(parts, cfg, "stock")
        self.assertAlmostEqual(sc, 100.0)
        self.assertEqual(gr, "A")
        sc2, _, bd2 = scoring.combine(dict(parts, catalyst=1, fundamentals=1), cfg, "future")
        self.assertNotIn("fundamentals", bd2)
        self.assertNotIn("catalyst", bd2)

    def test_sizing(self):
        cfg = config.load(CFG)
        plan = {"entry": 100.0, "stop": 98.0, "risk_per_share": 2.0}
        s = scoring.size(plan, cfg, "AAPL")
        self.assertEqual(s["shares"], 62)              # $125 risk / $2
        f = scoring.size({"entry": 5000, "stop": 4999, "risk_per_share": 1.0}, cfg, "MES=F")
        self.assertEqual(f["contracts"], cfg["max_contracts"])
        z = scoring.size({"entry": 70, "stop": 60, "risk_per_share": 10.0}, cfg, "MCL=F")
        self.assertEqual(z["contracts"], 0)


class TestBacktest(unittest.TestCase):
    def bars(self, rows):
        b = data.Bars("T")
        d0 = datetime.datetime(2026, 1, 5, tzinfo=data.NY)
        for k, (o, h, l, c) in enumerate(rows):
            b.append(d0 + datetime.timedelta(days=k), o, h, l, c, 1000)
        return b

    def plan(self, **kw):
        p = {"direction": "long", "entry": 101.0, "stop": 99.0, "targets": [103, 105, 107],
             "setup": "breakout", "entry_type": "stop"}
        p.update(kw)
        return p

    def test_target(self):
        b = self.bars([(100, 100.5, 99.5, 100), (100.5, 102, 100.2, 101.8), (102, 106, 101.5, 105.5)])
        r = backtest.simulate(b, 0, self.plan(), slippage_bps=0)
        self.assertEqual(r["exit_reason"], "target")
        self.assertAlmostEqual(r["r"], 2.0)

    def test_stop_wins_ties(self):
        b = self.bars([(100, 100.5, 99.5, 100), (100.5, 106, 98, 101)])
        r = backtest.simulate(b, 0, self.plan(), slippage_bps=0)
        self.assertEqual(r["exit_reason"], "stop")
        self.assertAlmostEqual(r["r"], -1.0)

    def test_gap_through_fill_at_open(self):
        b = self.bars([(100, 100.5, 99.5, 100), (102, 103, 101.5, 102.5), (102.5, 103, 102, 102.8)])
        r = backtest.simulate(b, 0, self.plan(), slippage_bps=0, max_hold=2)
        self.assertEqual(r["entry"], 102)

    def test_unfilled(self):
        b = self.bars([(100, 100.5, 99.5, 100)] * 5)
        self.assertIsNone(backtest.simulate(b, 0, self.plan(), fill_window=3))

    def test_run_on_fixtures(self):
        f = fetcher()
        res = backtest.run(f.cfg, f, ["AAPL", "NVDA", "SPY"], years=2, log=lambda *a: None)
        self.assertGreater(res["overall"]["n"], 10)
        self.assertIn("75+", res["by_score"])
        for t in res["trades"][:50]:
            self.assertLess(t["signal_date"], t["entry_date"] + "z")


class TestIntraday(unittest.TestCase):
    def test_regular_session_triggers(self):
        f = fetcher()
        b = data.intraday(f, "INTC")
        a = intraday.analyze(b, f.cfg, spy_change=1.0)
        self.assertEqual(a["phase"], "regular")
        names = {t["trigger"] for t in a["triggers"]}
        self.assertIn("orb_short", names)
        for t in a["triggers"]:
            self.assertGreater(t["stop"], t["entry"]) if t["direction"] == "short" else None
        for k in ("pdh", "pdl", "pmh", "pml", "orh", "orl"):
            self.assertIn(k, a["levels"])

    def test_premarket_plans(self):
        f = fetcher()
        b = data.intraday(f, "AAPL")
        cut = [k for k, t in enumerate(b.t) if t.date() == datetime.date(2026, 10, 14) and t.hour * 60 + t.minute >= 570]
        pre = b.slice(0, cut[0])
        a = intraday.analyze(pre, f.cfg)
        self.assertEqual(a["phase"], "premarket")
        self.assertFalse(a["triggers"])
        self.assertEqual({p["direction"] for p in a["plans"]}, {"long", "short"})


class TestPipeline(TempOut):
    def test_premarket_end_to_end(self):
        f = fetcher()
        res = pipeline.scan(f.cfg, f, log=lambda *a: None)
        self.assertEqual(res["bars_through"], "2026-10-13")
        top = {c["symbol"]: c for c in res["candidates"]}
        self.assertIn("TSLA", top)
        self.assertEqual(res["candidates"][0]["symbol"], "TSLA")
        tsla = top["TSLA"]
        self.assertTrue(tsla["checked"])
        self.assertIn("catalyst", tsla["breakdown"])
        self.assertTrue(any("earnings" in w for w in tsla["why"]["catalyst"]))
        ko = [c for c in res["candidates"] if c["symbol"] == "KO"][0]
        self.assertIn("earnings inside the hold", ko["flags"])
        aapl = top["AAPL"]
        self.assertIn("fundamentals", aapl["breakdown"])
        self.assertIn("TSLA", [r["ticker"] for r in res["inplay"]])
        self.assertIn("MES=F", [w["symbol"] for w in res["watchlist"]])
        self.assertEqual(journal.log_signals(res), len([c for c in res["candidates"] if c["grade"] in "AB"]))
        self.assertEqual(journal.log_signals(res), 0)          # no duplicates
        intr = live.run(f.cfg, f, res["watchlist"])
        aligned = [t for r in intr["rows"] for t in r["triggers"] if t["aligned"]]
        self.assertTrue(aligned)
        from scanner import report
        path = report.dashboard(res, intr)
        self.assertTrue(os.path.getsize(path) > 5000)

    def test_exported_orders_pass_baseline_format_checks(self):
        f = fetcher()
        res = pipeline.scan(f.cfg, f, log=lambda *a: None)
        pipeline.save(res)
        from scanner import cli
        trader_dir = os.path.join(config.ROOT, "trader")
        existed = os.path.isfile(os.path.join(trader_dir, "orders.json"))
        backup = None
        if existed:
            with open(os.path.join(trader_dir, "orders.json")) as fh:
                backup = fh.read()
        try:
            cli.main(["--config", CFG, "orders"])
            with open(os.path.join(trader_dir, "orders.json")) as fh:
                doc = json.load(fh)
            risk = baseline.load("trader-risk", "check")
            prices = {o["symbol"]: float(o["stop_price"]) for o in doc["orders"]}
            out = risk.check(doc["orders"], {"budget": 25000, "paper": True}, prices=prices)
            for r in out["results"]:
                fmt = [x for x in r.get("reasons", []) if x.startswith("format")]
                self.assertFalse(fmt, fmt)
        finally:
            if backup is not None:
                with open(os.path.join(trader_dir, "orders.json"), "w") as fh:
                    fh.write(backup)
            elif os.path.isfile(os.path.join(trader_dir, "orders.json")):
                os.remove(os.path.join(trader_dir, "orders.json"))


class TestJournal(TempOut):
    def test_trade_log(self):
        tid = journal.add_trade("AAPL", "long", 100, 98, 104, 50, "breakout", "A", 80)
        r = journal.close_trade(tid, 104, "yes")
        self.assertAlmostEqual(float(r["r"]), 2.0)
        st = journal.trade_stats()
        self.assertEqual(st["all"]["n"], 1)
        self.assertEqual(st["followed_plan_avg_r"], 2.0)


class TestRegime(unittest.TestCase):
    def test_market_and_sectors(self):
        f = fetcher()
        bars = data.many(f, sorted(set(regime.MARKET) | set(config.SECTOR_ETFS)), data.daily)
        m = regime.market(bars, breadth=0.6)
        self.assertIn(m["label"], ("Risk-on", "Neutral", "Risk-off"))
        self.assertTrue(-1 <= m["score"] <= 1)
        secs = regime.sectors(bars)
        self.assertEqual(len(secs), len(config.SECTOR_ETFS))
        self.assertEqual(secs[0]["status"], "leading")
        self.assertGreaterEqual(secs[0]["rs"], secs[-1]["rs"])


if __name__ == "__main__":
    unittest.main()
