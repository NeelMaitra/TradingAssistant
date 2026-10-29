"""Stocks in play: names the market is paying attention to today.

Sources (each optional, failures are noted, not fatal):
  1. Market-wide news RSS feeds: tickers pulled out of headlines and scored
  2. Yahoo's predefined screeners: day gainers, day losers, most active
  3. SEC's live 8-K feed: earnings, officer changes, deals, impairments...
  4. (added by the pipeline) the universe scan itself: gaps and relative volume
"""

import datetime
import re

from . import baseline, data
from .catalysts import current_8k
from .headlines import score as score_text
from .net import NetError

SCREENER = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds=%s&count=50"
TAG_RX = re.compile(r"<[^>]+>")


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def feed_items(fetcher, url, k):
    news = baseline.load("trader-news", "news")
    raw = fetcher.get(url, "rss_feed_%d" % k, ttl=fetcher.cfg["cache_minutes"]["news"])
    items = news.parse_rss(raw, None)
    host = url.split("/")[2].replace("www.", "").replace("feeds.", "")
    for it in items:
        it["source"] = host
        it["summary"] = TAG_RX.sub(" ", it.get("summary") or "")[:500]
    return items


def parse_screener(data, scr):
    try:
        quotes = data["finance"]["result"][0]["quotes"]
    except (KeyError, IndexError, TypeError):
        return []
    out = []
    for q in quotes:
        sym = q.get("symbol")
        if not sym or "." in sym and not sym.endswith((".A", ".B")):
            continue
        avg = q.get("averageDailyVolume3Month") or q.get("averageDailyVolume10Day") or 0
        out.append({"ticker": sym.upper(), "screen": scr, "name": q.get("shortName") or q.get("longName"),
                    "price": q.get("regularMarketPrice"), "chg_pct": q.get("regularMarketChangePercent"),
                    "volume": q.get("regularMarketVolume"),
                    "rvol": round(q["regularMarketVolume"] / avg, 2) if avg and q.get("regularMarketVolume") else None,
                    "market_cap": q.get("marketCap")})
    return out


def screeners(fetcher):
    rows = []
    for scr in ("day_gainers", "day_losers", "most_actives"):
        try:
            data = fetcher.json(SCREENER % scr, "yahoo_screener_%s" % scr, ttl=fetcher.cfg["cache_minutes"]["news"])
            rows += parse_screener(data, scr)
        except NetError as exc:
            fetcher.note("Yahoo screener %s: %s" % (scr, exc))
    return rows


def discover(fetcher, matcher, c2t=None, now=None, min_price=None):
    """ticker -> in-play record {score, bias, mentions, headlines, sources, ...}."""
    cfg = fetcher.cfg["inplay"]
    now = now or data.now_ny().astimezone(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(hours=cfg["hours"])
    book = {}

    def rec(t):
        return book.setdefault(t, {"ticker": t, "mentions": 0, "sentiment_sum": 0.0, "headlines": [],
                                   "catalysts": set(), "sources": set(), "screens": [], "filings": []})

    # 1. news feeds
    seen = set()
    for k, url in enumerate(cfg["rss_feeds"]):
        try:
            items = feed_items(fetcher, url, k)
        except Exception as exc:
            fetcher.note("news feed %s: %s" % (url.split("/")[2], exc))
            continue
        for it in items[:cfg["max_items"]]:
            if it.get("time") and it["time"] < cutoff:
                continue
            key = re.sub(r"\W+", " ", it["title"].lower()).strip()
            if key in seen:
                continue
            seen.add(key)
            text = "%s. %s" % (it["title"], it.get("summary") or "")
            tickers = matcher.find(it["title"]) or matcher.find(text, strict=True)
            if not tickers or len(tickers) > 3:     # market wrap-ups name everything; skip them
                continue
            s, tags, hits = score_text(text)
            for t in tickers:
                r = rec(t)
                r["mentions"] += 1
                r["sentiment_sum"] += s
                r["catalysts"].update(tags)
                r["sources"].add("news")
                r["headlines"].append({"title": it["title"], "link": it.get("link"), "source": it.get("source"),
                                       "time": it["time"].isoformat() if it.get("time") else None,
                                       "sentiment": s, "phrases": hits})

    # 2. screeners
    if cfg.get("use_yahoo_screeners", True):
        for q in screeners(fetcher):
            if min_price and (q.get("price") or 0) < min_price:
                continue
            r = rec(q["ticker"])
            r["sources"].add("screener")
            r["screens"].append(q["screen"])
            r["chg_pct"] = q.get("chg_pct")
            r["rvol"] = q.get("rvol")
            r.setdefault("name", q.get("name"))

    # 3. live 8-Ks
    if cfg.get("use_sec_current_8k", True) and c2t and fetcher.sec_ua:
        try:
            for f in current_8k(fetcher, c2t):
                if not f["ticker"] or not f["important"]:
                    continue
                if f.get("time") and f["time"] < cutoff:
                    continue
                r = rec(f["ticker"])
                r["sources"].add("8-K")
                r["filings"].append({"labels": f["labels"], "items": f["items"], "link": f["link"],
                                     "time": f["time"].isoformat() if f.get("time") else None})
                if "2.02" in f["items"]:
                    r["catalysts"].add("earnings")
        except NetError as exc:
            fetcher.note("SEC live 8-K feed: %s" % exc)

    out = {}
    for t, r in book.items():
        sent = r["sentiment_sum"] / r["mentions"] if r["mentions"] else 0.0
        chg = r.get("chg_pct") or 0.0
        sc = (0.25 * _clip(r["mentions"] / 3) + 0.30 * _clip(abs(sent) / 0.6)
              + 0.25 * _clip(abs(chg) / 8) + 0.20 * (1.0 if r["filings"] else 0.0))
        sc += 0.1 * (len(r["sources"]) - 1)
        lean = sent * 0.6 + _clip(chg / 8, -1, 1) * 0.4
        r["headlines"].sort(key=lambda h: abs(h["sentiment"]), reverse=True)
        out[t] = {"ticker": t, "score": round(_clip(sc), 3),
                  "bias": "long" if lean > 0.1 else "short" if lean < -0.1 else "neutral",
                  "lean": round(lean, 3), "sentiment": round(sent, 3), "mentions": r["mentions"],
                  "chg_pct": round(chg, 2) if r.get("chg_pct") is not None else None, "rvol": r.get("rvol"),
                  "catalysts": sorted(r["catalysts"]), "sources": sorted(r["sources"]),
                  "screens": r["screens"], "filings": r["filings"][:3], "headlines": r["headlines"][:5],
                  "name": r.get("name")}
    return out
