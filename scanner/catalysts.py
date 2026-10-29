"""Catalysts: the earnings calendar, headlines and SEC 8-K filings.

Reuses the baseline trader-news parsers for Yahoo RSS and EDGAR Atom feeds and
the baseline 8-K item table. Adds a market-wide current-8-K feed and a
Nasdaq earnings calendar.
"""

import datetime
import json
import re
import xml.etree.ElementTree as ET

from . import baseline, data
from .headlines import score as score_text, short_name
from .net import NetError

NASDAQ_EARNINGS = "https://api.nasdaq.com/api/calendar/earnings?date=%s"
NASDAQ_HEADERS = {"Accept": "application/json, text/plain, */*", "Origin": "https://www.nasdaq.com",
                  "Referer": "https://www.nasdaq.com/"}
SEC_CURRENT = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&company=&dateb="
               "&owner=include&start=0&count=100&output=atom")
YAHOO_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=%s&region=US&lang=en-US"
SEC_FEED = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=%s&type=8-K"
            "&dateb=&owner=include&count=10&output=atom")
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def _news():
    return baseline.load("trader-news", "news")


# ------------------------------------------------------------ earnings

def business_days(start, n, back=0):
    days, d = [], start - datetime.timedelta(days=1)
    k = 0
    while k < back:
        if d.weekday() < 5:
            days.insert(0, d)
            k += 1
        d -= datetime.timedelta(days=1)
    d = start
    while len(days) < back + n:
        if d.weekday() < 5:
            days.append(d)
        d += datetime.timedelta(days=1)
    return days


def parse_earnings(data, day):
    rows = (((data or {}).get("data") or {}).get("rows")) or []
    out = {}
    for r in rows:
        sym = (r.get("symbol") or "").strip().upper()
        if not sym:
            continue
        when = r.get("time") or ""
        out[sym] = {"date": day.isoformat(),
                    "time": "before open" if "pre" in when else "after close" if "after" in when else "unspecified",
                    "eps_forecast": r.get("epsForecast"), "name": r.get("name")}
    return out


def earnings_calendar(fetcher, today=None, ahead=8, back=2):
    """ticker -> next (or most recent within `back` days) earnings date info."""
    today = today or data.now_ny().date()
    cal = {}
    for d in business_days(today, ahead, back):
        try:
            data = fetcher.json(NASDAQ_EARNINGS % d.isoformat(), "nasdaq_earnings_%s" % d.isoformat(),
                                ttl=fetcher.cfg["cache_minutes"]["earnings"], headers=NASDAQ_HEADERS)
        except NetError as exc:
            fetcher.note("earnings calendar %s: %s" % (d, exc))
            continue
        for sym, info in parse_earnings(data, d).items():
            prev = cal.get(sym)
            # prefer the next upcoming date; keep a recent past one only if nothing upcoming
            if prev is None or (prev["date"] < today.isoformat() <= info["date"]):
                cal[sym] = info
    return cal


def earnings_context(sym, cal, today=None):
    """{'days': trading-ish days until (neg = since), 'date', 'time'} or None."""
    info = cal.get(sym.replace("-", ".")) or cal.get(sym)
    if not info:
        return None
    today = today or data.now_ny().date()
    d = datetime.date.fromisoformat(info["date"])
    bd = 0
    step = 1 if d >= today else -1
    x = today
    while x != d:
        x += datetime.timedelta(days=step)
        if x.weekday() < 5:
            bd += step
    return dict(info, days=bd)


# ------------------------------------------------------------ SEC

def cik_map(fetcher):
    """ticker -> 10-digit CIK, and CIK -> ticker."""
    try:
        data = fetcher.json(TICKERS_URL, "sec_company_tickers.json", sec=True,
                            ttl=fetcher.cfg["cache_minutes"]["universe"])
    except NetError as exc:
        fetcher.note("SEC ticker map: %s" % exc)
        return {}, {}
    t2c, c2t = {}, {}
    for v in data.values():
        t = v["ticker"].upper()
        c = str(v["cik_str"]).zfill(10)
        t2c.setdefault(t, c)
        c2t.setdefault(c, t)
    return t2c, c2t


def parse_current_8k(raw, c2t):
    """SEC 'latest filings' Atom -> items with ticker, 8-K item numbers and labels."""
    news = _news()
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise NetError("SEC current feed is not XML: %s" % exc)
    out = []
    for entry in root.iter():
        if news._local(entry.tag) != "entry":
            continue
        title = news._text(entry, "title")
        summary = news._text(entry, "summary")
        m = re.search(r"\((\d{10})\)", title)
        if not m or not title.startswith("8-K"):
            continue
        cik = m.group(1)
        items = sorted(set(re.findall(r"Item (\d\.\d\d)", summary)))
        link = ""
        for c in entry.iter():
            if news._local(c.tag) == "link":
                link = c.get("href", "")
        company = re.sub(r"^8-K(?:/A)?\s*-\s*", "", title).split(" (")[0]
        out.append({"ticker": c2t.get(cik), "cik": cik, "company": company, "items": items,
                    "labels": [news.ITEMS_8K.get(i, "item " + i) for i in items if i != "9.01"],
                    "important": bool(set(items) & news.IMPORTANT_ITEMS), "link": link,
                    "time": news.parse_time(news._text(entry, "updated")), "source": "SEC EDGAR"})
    return out


def current_8k(fetcher, c2t):
    raw = fetcher.get(SEC_CURRENT, "sec_current_8k.atom", sec=True, ttl=fetcher.cfg["cache_minutes"]["news"])
    return parse_current_8k(raw, c2t)


# ------------------------------------------------------------ per-ticker news

def relevant(it, sym, name=None):
    """Yahoo's per-ticker feed mixes in stories about other companies. Keep a headline
    only if it names the ticker or the company; SEC filings are always the company's own."""
    if it.get("kind") == "filing":
        return True
    hay = "%s %s" % (it.get("title") or "", it.get("summary") or "")
    t = re.escape(sym.upper().replace("-", "."))
    if len(sym) >= 2 and re.search(r"(?<![A-Za-z0-9])%s(?![A-Za-z0-9])" % t, hay):
        return True
    if re.search(r"\$%s\b|\(%s\)|(?:NYSE|NASDAQ|Nasdaq)\s*:\s*%s\b" % (t, t, t), hay):
        return True
    sn = short_name(name or "")
    if sn and sn != sym.upper():          # name equal to the bare ticker is a placeholder
        if len(sn) >= 3 and re.search(r"\b%s" % re.escape(sn), hay, re.I):
            return True
        first = sn.split()[0]
        if len(first) >= 5 and re.search(r"\b%s\b" % re.escape(first), hay, re.I):
            return True
    return False


def ticker_news(fetcher, sym, t2c=None, hours=72, now=None, sec=True, name=None):
    """Headlines (Yahoo RSS) + 8-Ks (EDGAR) for one ticker, scored, newest first.
    Headlines that do not mention the ticker or company name are dropped."""
    news = _news()
    now = now or data.now_ny().astimezone(datetime.timezone.utc)
    items = []
    ys = sym.replace(".", "-")
    try:
        raw = fetcher.get(YAHOO_RSS % ys, "yahoo_rss_%s" % ys, ttl=fetcher.cfg["cache_minutes"]["news"])
        items += news.parse_rss(raw, sym)
    except (NetError, Exception) as exc:  # parse errors come back as NewsError
        fetcher.note("headlines %s: %s" % (sym, exc))
    cik = (t2c or {}).get(sym.replace("-", ".").upper()) or (t2c or {}).get(sym.upper())
    if sec and cik and fetcher.sec_ua:
        try:
            raw = fetcher.get(SEC_FEED % cik, "sec_8k_%s" % cik, sec=True,
                              ttl=fetcher.cfg["cache_minutes"]["news"])
            items += news.parse_sec_atom(raw, sym)
        except (NetError, Exception) as exc:
            fetcher.note("8-K feed %s: %s" % (sym, exc))
    cutoff = now - datetime.timedelta(hours=hours)
    keep = []
    for it in news.dedupe(news.tag(items, {sym: None})):
        if it.get("time") and it["time"] < cutoff:
            continue
        if not relevant(it, sym, name):
            continue
        s, tags, hits = score_text("%s. %s" % (it["title"], it.get("summary") or "")[:600])
        it["sentiment"], it["catalysts"], it["phrases"] = s, tags, hits
        keep.append(it)
    keep.sort(key=lambda x: x.get("time") or now, reverse=True)
    return keep


def catalyst_score(direction, items, earn=None, filings=None, swing=True, buffer_days=3):
    """0..1 plus reasons. Fresh aligned news, important 8-Ks and earnings reactions
    help; an earnings report inside the holding window is a risk, so it is penalised
    for swing trades (not for day trades taken after the report)."""
    reasons, s = [], 0.35            # no news is neutral, not bad
    sign = 1 if direction == "long" else -1
    if items:
        top = items[:8]
        avg = sum(it.get("sentiment", 0) for it in top) / len(top)
        strongest = max(top, key=lambda it: abs(it.get("sentiment", 0)))
        aligned = avg * sign
        s += 0.45 * max(-1.0, min(1.0, aligned * 1.5))
        if abs(strongest.get("sentiment", 0)) >= 0.3:
            reasons.append("%s headline: \"%s\"" % ("supportive" if strongest["sentiment"] * sign > 0 else "opposing",
                                                    strongest["title"][:110]))
        else:
            reasons.append("%d headline(s) in the window, none strongly directional" % len(items))
        cats = sorted({c for it in top for c in it.get("catalysts", [])})
        if cats:
            reasons.append("catalysts: " + ", ".join(cats))
    for f in filings or []:
        if f.get("important"):
            s += 0.1
            reasons.append("8-K: " + ", ".join(f.get("labels") or f.get("items") or []))
            break
    if earn:
        d = earn["days"]
        if d < 0 and d >= -2:
            s += 0.1
            reasons.append("reported earnings %d day(s) ago (%s): post-earnings move in play" % (-d, earn["time"]))
        elif d == 0:
            if swing:
                s -= 0.25
            reasons.append("earnings TODAY %s" % earn["time"])
        elif 0 < d <= buffer_days and swing:
            s -= 0.3
            reasons.append("earnings in %d trading day(s) (%s %s): binary risk inside a swing hold"
                           % (d, earn["date"], earn["time"]))
        elif 0 < d <= 10:
            reasons.append("earnings %s (%s)" % (earn["date"], earn["time"]))
    return round(max(0.0, min(1.0, s)), 3), reasons


def items_json(items):
    out = []
    for it in items:
        d = {k: v for k, v in it.items() if k not in ("time",)}
        d["time"] = it["time"].isoformat() if it.get("time") else None
        out.append(d)
    return json.loads(json.dumps(out, default=str))
