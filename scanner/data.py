"""Price bars: Yahoo Finance chart JSON (daily + intraday, stocks, ETFs, futures,
indexes), with Stooq as a daily fallback. Free and delayed (~15 min for most
US quotes). Check anything that matters against your broker.
"""

import datetime
import io
import csv
from concurrent.futures import ThreadPoolExecutor

try:
    from zoneinfo import ZoneInfo
    NY = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover - Python < 3.9
    NY = datetime.timezone(datetime.timedelta(hours=-5))

from .net import NetError

YAHOO_CHART = ("https://query1.finance.yahoo.com/v8/finance/chart/%s"
               "?range=%s&interval=%s&includePrePost=%s&events=div%%2Csplits")
STOOQ_DAILY = "https://stooq.com/q/d/l/?s=%s&i=d"


class Bars(object):
    """Parallel lists. t is a timezone-aware New York datetime (date-only data at 00:00)."""

    __slots__ = ("symbol", "t", "o", "h", "l", "c", "v", "meta", "source")

    def __init__(self, symbol, rows=None, meta=None, source=""):
        self.symbol = symbol
        self.meta = meta or {}
        self.source = source
        self.t, self.o, self.h, self.l, self.c, self.v = [], [], [], [], [], []
        for r in rows or []:
            self.append(*r)

    def append(self, t, o, h, l, c, v):
        self.t.append(t)
        self.o.append(float(o))
        self.h.append(float(h))
        self.l.append(float(l))
        self.c.append(float(c))
        self.v.append(float(v or 0))

    def __len__(self):
        return len(self.c)

    def slice(self, start=0, end=None):
        b = Bars(self.symbol, meta=self.meta, source=self.source)
        for name in ("t", "o", "h", "l", "c", "v"):
            setattr(b, name, getattr(self, name)[start:end])
        return b

    def last_date(self):
        return self.t[-1].date() if self.t else None


def yahoo_symbol(sym):
    s = sym.strip().upper()
    if s.startswith("^") or s.endswith("=F") or s.endswith("=X"):
        return s
    return s.replace(".", "-")


def parse_yahoo(data, symbol):
    try:
        res = data["chart"]["result"][0]
    except (KeyError, IndexError, TypeError):
        err = (data.get("chart") or {}).get("error") if isinstance(data, dict) else None
        raise NetError("Yahoo has no chart for %s%s" % (symbol, (": %s" % err.get("description")) if err else ""))
    meta = res.get("meta") or {}
    ts = res.get("timestamp") or []
    q = ((res.get("indicators") or {}).get("quote") or [{}])[0]
    o, h, l, c, v = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))
    gran = meta.get("dataGranularity", "1d")
    daily = gran.endswith("d") or gran.endswith("wk") or gran.endswith("mo")
    b = Bars(symbol, meta=meta, source="yahoo")
    for i, t in enumerate(ts):
        try:
            if None in (o[i], h[i], l[i], c[i]):
                continue
        except IndexError:
            break
        dt = datetime.datetime.fromtimestamp(t, NY)
        if daily:
            dt = datetime.datetime(dt.year, dt.month, dt.day, tzinfo=NY)
        b.append(dt, o[i], h[i], l[i], c[i], (v[i] if i < len(v) else 0) or 0)
    # Yahoo sometimes repeats the live daily bar; keep the last of each date
    if daily and len(b) > 1:
        keep = [i for i in range(len(b)) if i == len(b) - 1 or b.t[i].date() != b.t[i + 1].date()]
        if len(keep) != len(b):
            nb = Bars(symbol, meta=meta, source="yahoo")
            for i in keep:
                nb.append(b.t[i], b.o[i], b.h[i], b.l[i], b.c[i], b.v[i])
            b = nb
    return b


def parse_stooq(text, symbol):
    rows = list(csv.DictReader(io.StringIO(text)))
    b = Bars(symbol, source="stooq")
    for r in rows:
        try:
            d = datetime.datetime.strptime(r["Date"], "%Y-%m-%d")
            b.append(datetime.datetime(d.year, d.month, d.day, tzinfo=NY),
                     r["Open"], r["High"], r["Low"], r["Close"], r.get("Volume") or 0)
        except (KeyError, ValueError):
            continue
    if not len(b):
        raise NetError("Stooq has no data for %s" % symbol)
    return b


def daily(fetcher, symbol, range_="2y"):
    ys = yahoo_symbol(symbol)
    ttl = fetcher.cfg["cache_minutes"]["daily"]
    try:
        data = fetcher.json(YAHOO_CHART % (ys, range_, "1d", "false"),
                            "yahoo_%s_%s_1d" % (ys, range_), ttl=ttl)
        b = parse_yahoo(data, symbol)
        if len(b) >= 30:
            return b
    except NetError as exc:
        first = exc
    else:
        first = NetError("Yahoo returned too few bars for %s" % symbol)
    if ys.startswith("^") or ys.endswith("=F"):
        raise first
    try:
        raw = fetcher.get(STOOQ_DAILY % (ys.lower().replace("-", ".") + ".us"),
                          "stooq_%s_1d" % ys, ttl=ttl)
        return parse_stooq(raw.decode("utf-8", "replace"), symbol)
    except NetError:
        raise first


def intraday(fetcher, symbol, interval="5m", range_="1mo", prepost=True):
    ys = yahoo_symbol(symbol)
    data = fetcher.json(YAHOO_CHART % (ys, range_, interval, "true" if prepost else "false"),
                        "yahoo_%s_%s_%s" % (ys, range_, interval),
                        ttl=fetcher.cfg["cache_minutes"]["intraday"])
    return parse_yahoo(data, symbol)


def many(fetcher, symbols, fn=daily, threads=None, **kw):
    """symbol -> Bars for every symbol that loaded; failures go to fetcher.errors."""
    out = {}

    def one(s):
        try:
            return s, fn(fetcher, s, **kw)
        except NetError as exc:
            fetcher.note(str(exc))
            return s, None

    with ThreadPoolExecutor(max_workers=threads or fetcher.cfg.get("threads", 8)) as ex:
        for s, b in ex.map(one, symbols):
            if b is not None and len(b):
                out[s] = b
    return out


# ------------------------------------------------------------- sessions

def session_parts(bars, day=None):
    """Split intraday bars for one New York date into premarket / regular / after.
    Regular session is 9:30-16:00 ET (used for futures too, the RTH convention)."""
    day = day or (bars.t[-1].date() if len(bars) else None)
    pre, reg, post = [], [], []
    for i, t in enumerate(bars.t):
        if t.date() != day:
            continue
        hm = t.hour * 60 + t.minute
        if hm < 570:
            pre.append(i)
        elif hm < 960:
            reg.append(i)
        else:
            post.append(i)
    return pre, reg, post


def trading_days(bars):
    seen = []
    for t in bars.t:
        d = t.date()
        if not seen or seen[-1] != d:
            seen.append(d)
    return seen


def now_ny():
    """Current New York time. CONFLUENCE_NOW (ISO 8601) pins it, for tests and replays."""
    import os
    pinned = os.environ.get("CONFLUENCE_NOW")
    if pinned:
        d = datetime.datetime.fromisoformat(pinned)
        return (d if d.tzinfo else d.replace(tzinfo=NY)).astimezone(NY)
    return datetime.datetime.now(NY)


def market_phase(now=None):
    """'premarket' | 'open' | 'after' | 'closed' (weekends; holidays via the baseline calendar)."""
    now = now or now_ny()
    if now.weekday() >= 5:
        return "closed"
    try:
        from . import baseline
        alerts = baseline.load("trader-alerts", "alerts")
        if not alerts.trading_day(now.date())[0]:
            return "closed"
    except Exception:
        pass
    hm = now.hour * 60 + now.minute
    if 240 <= hm < 570:
        return "premarket"
    if 570 <= hm < 960:
        return "open"
    if 960 <= hm < 1200:
        return "after"
    return "closed"
