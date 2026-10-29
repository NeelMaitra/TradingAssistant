"""Builds the offline fixture set in tests/fixtures/ (deterministic).

Synthetic daily and 5-minute bars in Yahoo chart JSON format, engineered so the
scan has something to find, plus real SEC / Yahoo RSS samples copied from the
baseline trader-skill test fixtures (Apple's XBRL facts, 8-K feed, headlines).
Run: python3 tests/make_fixtures.py   (pinned "now": 2026-10-14 10:35 ET)
"""

import datetime
import json
import math
import os
import random
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from scanner.data import NY  # noqa: E402
from scanner.net import safe_key  # noqa: E402

FIX = os.path.join(ROOT, "tests", "fixtures")
BASE = os.path.join(ROOT, "tests", "baseline_samples")
LAST_DAILY = datetime.date(2026, 10, 13)
TODAY = datetime.date(2026, 10, 14)
N = 520


def bdays_back(end, n):
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= datetime.timedelta(days=1)
    return out[::-1]


DAYS = bdays_back(LAST_DAILY, N)


def write(key, obj):
    path = os.path.join(FIX, safe_key(key))
    with open(path, "w", encoding="utf-8") as fh:
        if isinstance(obj, (dict, list)):
            json.dump(obj, fh)
        else:
            fh.write(obj)


def chart(sym, times, o, h, l, c, v, gran):
    return {"chart": {"result": [{"meta": {"symbol": sym, "dataGranularity": gran, "currency": "USD",
                                           "exchangeTimezoneName": "America/New_York",
                                           "regularMarketPrice": c[-1]},
                                  "timestamp": times,
                                  "indicators": {"quote": [{"open": o, "high": h, "low": l, "close": c,
                                                            "volume": v}]}}], "error": None}}


def ohlc_from_closes(closes, rng, vol_pct, vols=None, ranges=None):
    o, h, l, v = [], [], [], []
    for i, c in enumerate(closes):
        prev = closes[i - 1] if i else c
        op = prev * (1 + rng.gauss(0, vol_pct * 0.25))
        r = (ranges[i] if ranges else vol_pct) * c
        hi = max(op, c) + abs(rng.gauss(0, r * 0.45))
        lo = min(op, c) - abs(rng.gauss(0, r * 0.45))
        o.append(round(op, 4))
        h.append(round(hi, 4))
        l.append(round(lo, 4))
        v.append(int((vols[i] if vols else 1.0) * 5_000_000 * (0.8 + 0.4 * rng.random())))
    return o, h, l, [round(x, 4) for x in closes], v


def walk(rng, start, drifts, vol):
    c, out = start, []
    for d in drifts:
        c *= math.exp(d + rng.gauss(0, vol))
        out.append(c)
    return out


def daily_series(sym, seed, kind):
    rng = random.Random(seed)
    vol = 0.012
    ranges, vols = None, [1.0] * N
    if kind == "trend_up":
        closes = walk(rng, 100, [0.0012] * N, vol)
    elif kind == "strong_up":
        closes = walk(rng, 80, [0.0018] * N, vol)
    elif kind == "weak":
        closes = walk(rng, 100, [-0.0002] * N, vol)
    elif kind == "down":
        closes = walk(rng, 120, [0.0004] * 300 + [-0.0022] * (N - 300), vol)
    elif kind == "vix":
        closes = [max(10.5, 15 + 3 * math.sin(i / 23.0) + rng.gauss(0, 0.6)) for i in range(N)]
        closes[-6:] = [16.5, 16.0, 15.6, 15.1, 14.8, 14.2]
    elif kind == "breakout":
        closes = walk(rng, 60, [0.0016] * (N - 25), vol)
        top = closes[-1]
        base = []
        for k in range(24):
            base.append(top * (0.965 + 0.02 * rng.random()))
        closes += base
        closes.append(top * 0.995)
        ranges = [vol] * (N - 25) + [vol * 0.45] * 24 + [vol * 0.6]
        vols = [1.0] * (N - 1) + [1.9]
        closes = closes[:N]
    elif kind == "pullback":
        closes = walk(rng, 50, [0.0025] * (N - 6), vol * 0.45)
        top = closes[-1]
        closes += [top * 1.012, top * 1.004, top * 0.994, top * 0.986, top * 0.981, top * 1.007]
        closes = closes[:N]
        ranges = [vol] * N
    elif kind == "gap":
        closes = walk(rng, 200, [0.0008] * (N - 1), vol * 1.4)
        closes.append(closes[-1] * 1.105)
        vols = [1.0] * (N - 1) + [4.2]
    elif kind == "breakdown":
        closes = walk(rng, 90, [0.0003] * 280 + [-0.0018] * (N - 280 - 22), vol)
        bot = closes[-1]
        closes += [bot * (1.008 + 0.02 * rng.random()) for _ in range(21)]
        closes.append(bot * 1.004)
        ranges = [vol] * (N - 22) + [vol * 0.45] * 21 + [vol * 0.6]
        vols = [1.0] * (N - 1) + [1.6]
        closes = closes[:N]
    elif kind == "oversold":
        closes = walk(rng, 55, [0.0009] * (N - 3), vol * 0.7)
        closes += [closes[-1] * 0.975, closes[-1] * 0.975 * 0.972, closes[-1] * 0.975 * 0.972 * 0.97]
    else:
        raise ValueError(kind)
    o, h, l, c, v = ohlc_from_closes(closes, rng, vol, vols, ranges)
    if kind == "gap":  # make the gap bar open high and close near its high
        o[-1] = round(c[-2] * 1.09, 4)
        l[-1] = round(o[-1] * 0.995, 4)
        h[-1] = round(c[-1] * 1.004, 4)
    if kind == "breakout":
        h[-1] = max(h[-1], c[-1] * 1.002)
    if kind == "pullback":   # last bar dips to the 20 EMA zone intraday and closes green
        o[-1] = round(c[-2] * 0.998, 4)
        l[-1] = round(min(l[-1], c[-1] * 0.976), 4)
        h[-1] = round(max(h[-1], c[-1] * 1.003), 4)
    times = [int(datetime.datetime(d.year, d.month, d.day, 9, 30, tzinfo=NY).timestamp()) for d in DAYS]
    return chart(sym, times, o, h, l, c, v, "1d")


def intraday_series(sym, seed, last_close, behaviour):
    """5-minute bars: 9 full sessions + today's premarket and first hour."""
    rng = random.Random(seed + 999)
    days = bdays_back(TODAY, 10)
    t, o, h, l, c, v = [], [], [], [], [], []
    px = last_close / 1.002
    for d in days:
        is_today = d == TODAY
        start = datetime.datetime(d.year, d.month, d.day, 4, 0, tzinfo=NY)
        end_min = 10 * 60 + 35 if is_today else 20 * 60
        m = 4 * 60
        or_hi = None
        while m < end_min:
            ts = start + datetime.timedelta(minutes=m - 240)
            regular = 570 <= m < 960
            drift = 0.0
            if is_today and regular:
                k = (m - 570) // 5
                if behaviour == "up":
                    drift = -0.0008 if k < 3 else 0.0011
                elif behaviour == "down":
                    drift = 0.0008 if k < 3 else -0.0011
            sd = 0.0012 if regular else 0.0004
            op = px
            px = px * math.exp(drift + rng.gauss(0, sd))
            hi = max(op, px) * (1 + abs(rng.gauss(0, sd * 0.4)))
            lo = min(op, px) * (1 - abs(rng.gauss(0, sd * 0.4)))
            vol = (60_000 if regular else 4_000) * (1.6 if is_today and behaviour != "flat" else 1.0)
            if regular and (m < 600 or m > 930):
                vol *= 2.2
            t.append(int(ts.timestamp()))
            o.append(round(op, 4))
            h.append(round(hi, 4))
            l.append(round(lo, 4))
            c.append(round(px, 4))
            v.append(int(vol * (0.7 + 0.6 * rng.random())))
            m += 5
            _ = or_hi
    return chart(sym, t, o, h, l, c, v, "5m")


SYMBOLS = {
    # symbol: (seed, daily kind, intraday behaviour)
    "SPY": (1, "trend_up", "up"), "QQQ": (2, "trend_up", "up"), "IWM": (3, "trend_up", "flat"),
    "^VIX": (4, "vix", None), "HYG": (5, "trend_up", None), "TLT": (6, "weak", None),
    "GLD": (7, "trend_up", None), "USO": (8, "weak", None), "DIA": (9, "trend_up", None),
    "XLK": (10, "strong_up", None), "XLF": (11, "trend_up", None), "XLE": (12, "weak", None),
    "XLV": (13, "weak", None), "XLI": (14, "trend_up", None), "XLY": (15, "trend_up", None),
    "XLP": (16, "weak", None), "XLU": (17, "weak", None), "XLB": (18, "weak", None),
    "XLRE": (19, "down", None), "XLC": (20, "strong_up", None), "SMH": (21, "strong_up", None),
    "XBI": (22, "weak", None), "KRE": (23, "down", None), "ITB": (24, "trend_up", None),
    "AAPL": (31, "breakout", "up"), "NVDA": (32, "pullback", "up"), "TSLA": (33, "gap", "up"),
    "INTC": (34, "breakdown", "down"), "KO": (35, "oversold", "flat"), "MSFT": (36, "trend_up", "flat"),
    "JPM": (37, "trend_up", "flat"), "XOM": (38, "weak", "flat"),
    "MES=F": (41, "trend_up", "up"), "MNQ=F": (42, "strong_up", "up"),
    "M2K=F": (43, "trend_up", None), "MYM=F": (44, "trend_up", None),
    "MGC=F": (45, "trend_up", None), "MCL=F": (46, "weak", None),
}


def main():
    if os.path.isdir(FIX):
        shutil.rmtree(FIX)
    os.makedirs(FIX)
    for sym, (seed, kind, intr) in SYMBOLS.items():
        d = daily_series(sym, seed, kind)
        for rng_ in ("2y", "5y", "10y"):
            write("yahoo_%s_%s_1d" % (sym, rng_), d)
        last = d["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1]
        if intr:
            write("yahoo_%s_1mo_5m" % sym, intraday_series(sym, seed, last, intr))
    # 6 months for journal review
    for sym in SYMBOLS:
        src = os.path.join(FIX, safe_key("yahoo_%s_2y_1d" % sym))
        shutil.copy(src, os.path.join(FIX, safe_key("yahoo_%s_6mo_1d" % sym)))

    # ---- real samples from the baseline repo's tests
    tickers = json.load(open(os.path.join(BASE, "company_tickers.json")))
    extra = {"NVDA": 1045810, "TSLA": 1318605, "INTC": 50863, "MSFT": 789019, "JPM": 19617, "XOM": 34088}
    k = 900
    for t, cik in extra.items():
        tickers[str(k)] = {"cik_str": cik, "ticker": t, "title": t}
        k += 1
    write("sec_company_tickers.json", tickers)
    shutil.copy(os.path.join(BASE, "companyfacts-CIK0000320193.json"), os.path.join(FIX, "sec_facts_0000320193"))
    shutil.copy(os.path.join(BASE, "companyfacts-CIK0000021344.json"), os.path.join(FIX, "sec_facts_0000021344"))
    shutil.copy(os.path.join(BASE, "yahoo-AAPL.xml"), os.path.join(FIX, "yahoo_rss_AAPL"))
    shutil.copy(os.path.join(BASE, "yahoo-KO.xml"), os.path.join(FIX, "yahoo_rss_KO"))
    shutil.copy(os.path.join(BASE, "sec-8-K-0000320193.xml"), os.path.join(FIX, "sec_8k_0000320193"))
    shutil.copy(os.path.join(BASE, "sec-8-K-0000021344.xml"), os.path.join(FIX, "sec_8k_0000021344"))

    # ---- synthetic market-wide news feed (headlines are made up for the test)
    items = [
        ("Tesla soars after record deliveries as it raises full-year guidance (NASDAQ: TSLA)", "Tue, 13 Oct 2026 21:05:00 +0000"),
        ("Intel downgraded to underperform at a major broker, price target cut", "Wed, 14 Oct 2026 11:10:00 +0000"),
        ("Nvidia wins data center contract with a hyperscaler", "Wed, 14 Oct 2026 12:00:00 +0000"),
        ("Stocks set to open higher; Apple, Microsoft, JPMorgan, Exxon and Nvidia in focus", "Wed, 14 Oct 2026 12:30:00 +0000"),
        ("Coca-Cola shares slump ahead of earnings", "Wed, 14 Oct 2026 10:00:00 +0000"),
    ]
    rss = ['<?xml version="1.0"?><rss version="2.0"><channel><title>Test markets feed</title>']
    for k, (title, when) in enumerate(items):
        rss.append("<item><title>%s</title><link>https://example.com/story/%d</link><guid>test-%d</guid>"
                   "<pubDate>%s</pubDate><description>%s</description></item>" % (title, k, k, when, title))
    rss.append("</channel></rss>")
    write("rss_feed_0", "".join(rss))
    for t in ("NVDA", "TSLA", "INTC", "MSFT", "JPM", "XOM"):
        write("yahoo_rss_%s" % t, '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>')
    empty_atom = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    for cik in extra.values():
        write("sec_8k_%010d" % cik, empty_atom)

    # Yahoo screener (day gainers)
    write("yahoo_screener_day_gainers", {"finance": {"result": [{"quotes": [
        {"symbol": "TSLA", "shortName": "Tesla", "regularMarketPrice": 300.0, "regularMarketChangePercent": 10.5,
         "regularMarketVolume": 21000000, "averageDailyVolume3Month": 5000000, "marketCap": 9.5e11}]}]}})
    write("yahoo_screener_day_losers", {"finance": {"result": [{"quotes": []}]}})
    write("yahoo_screener_most_actives", {"finance": {"result": [{"quotes": []}]}})

    # SEC live 8-K feed: Apple results (item 2.02)
    write("sec_current_8k.atom", """<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Latest Filings</title>
<entry><title>8-K - Apple Inc. (0000320193) (Filer)</title>
<link rel="alternate" type="text/html" href="https://www.sec.gov/Archives/edgar/data/320193/x-index.htm"/>
<summary type="html"> &lt;b&gt;Filed:&lt;/b&gt; 2026-10-14 &lt;b&gt;AccNo:&lt;/b&gt; 0000320193-26-000099 &lt;br&gt;Item 2.02: Results of Operations and Financial Condition&lt;br&gt;Item 9.01: Financial Statements and Exhibits</summary>
<updated>2026-10-14T08:05:00-04:00</updated><category scheme="https://www.sec.gov/" label="form type" term="8-K"/>
<id>urn:tag:sec.gov,2008:accession-number=0000320193-26-000099</id></entry>
</feed>""")

    # Nasdaq earnings calendar: KO in 2 days (risk for a swing hold), TSLA reported last night
    for d in bdays_back(datetime.date(2026, 10, 23), 10):
        rows = []
        if d == datetime.date(2026, 10, 16):
            rows.append({"symbol": "KO", "name": "Coca-Cola", "time": "time-pre-market", "epsForecast": "$0.74"})
        if d == datetime.date(2026, 10, 13):
            rows.append({"symbol": "TSLA", "name": "Tesla", "time": "time-after-hours", "epsForecast": "$0.60"})
        write("nasdaq_earnings_%s" % d.isoformat(), {"data": {"rows": rows or None}})
    print("fixtures written to %s (%d files)" % (FIX, len(os.listdir(FIX))))


if __name__ == "__main__":
    main()
