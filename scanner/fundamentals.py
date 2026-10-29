"""Fundamentals from SEC XBRL company facts, via the baseline trader-analyst parser.

Fetched only for the shortlist (company facts files are large and change once a
quarter) and cached for a week. Scores growth and margin direction 0..1 for the
trade direction: longs want growth and expanding margins, shorts the opposite.
"""

from . import baseline
from .net import NetError

FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json"


def _clip(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def metrics(fetcher, sym, t2c):
    """-> metrics dict or None. Needs the SEC User-Agent."""
    facts = baseline.load("trader-analyst", "facts")
    cik = t2c.get(sym.replace("-", ".").upper()) or t2c.get(sym.upper())
    if not cik or not fetcher.sec_ua:
        return None
    try:
        cf = fetcher.json(FACTS_URL % cik, "sec_facts_%s" % cik, sec=True,
                          ttl=fetcher.cfg["cache_minutes"]["fundamentals"])
        res = facts.analyse(cf, quarters=6)
    except (NetError, Exception) as exc:
        fetcher.note("fundamentals %s: %s" % (sym, exc))
        return None
    row = facts.metrics_row(sym, res)
    rows = res["rows"]
    # margin trend: latest quarter vs the same quarter a year earlier (rows are newest first)
    om_now = rows[0].get("operating_margin") if rows else None
    om_then = rows[4].get("operating_margin") if len(rows) > 4 else None
    row["operating_margin_change"] = round(om_now - om_then, 2) if None not in (om_now, om_then) else None
    row["quarters"] = [{k: r.get(k) for k in ("end", "fiscal", "revenue", "revenue_yoy", "eps_diluted",
                                               "eps_yoy", "operating_margin")} for r in rows[:4]]
    return row


def score(direction, m):
    """0..1 plus reasons. Missing data scores neutral (0.5)."""
    if not m:
        return 0.5, ["no SEC fundamentals (ETF, future, foreign filer, or no SEC User-Agent)"]
    rg, eg = m.get("revenue_growth_yoy"), m.get("eps_growth_yoy")
    om, omc, nm = m.get("operating_margin"), m.get("operating_margin_change"), m.get("net_margin")
    parts, reasons = [], []
    if rg is not None:
        parts.append(_clip((rg + 5) / 30))          # -5% -> 0, +25% -> 1
        reasons.append("revenue %+.0f%% y/y" % rg)
    if eg is not None:
        parts.append(_clip((eg + 10) / 50))
        reasons.append("EPS %+.0f%% y/y" % eg)
    if om is not None:
        parts.append(_clip((om + 5) / 35))
        reasons.append("operating margin %.0f%%" % om)
    if omc is not None:
        parts.append(_clip(0.5 + omc / 10))
        reasons.append("margin %s %.1f pts y/y" % ("up" if omc >= 0 else "down", abs(omc)))
    if nm is not None and nm < 0:
        parts.append(0.2)
        reasons.append("unprofitable")
    if not parts:
        return 0.5, ["fundamentals incomplete"]
    s = sum(parts) / len(parts)
    if direction == "short":
        s = 1 - s
    return round(s, 3), reasons
