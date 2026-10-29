"""Headline scoring: which way a headline leans, what kind of catalyst it is,
and which tickers it names. A transparent word list, not a black box: every
score comes with the phrases that produced it.

Headlines are leads, not facts. Open the story or the filing before acting.
"""

import re

# (regex, weight, catalyst tag). Weight > 0 bullish, < 0 bearish.
LEXICON = [
    (r"\bbeats?\b|\btops?\b (?:estimates|expectations|forecasts)|\bbetter[- ]than[- ]expected\b|\bblowout\b", 0.6, "earnings"),
    (r"\bmiss(?:es|ed)?\b|\bfalls? short\b|\bworse[- ]than[- ]expected\b|\bdisappoint", -0.6, "earnings"),
    (r"\braises? (?:its |full[- ]year |annual )?(?:guidance|outlook|forecast)|\bboosts? (?:guidance|outlook)|\bguidance (?:above|tops)", 0.8, "guidance"),
    (r"\b(?:cuts?|lowers?|slashes|withdraws?) (?:its |full[- ]year |annual )?(?:guidance|outlook|forecast)|\bguidance (?:below|misses)|\bweak (?:guidance|outlook)", -0.8, "guidance"),
    (r"\brecord (?:revenue|sales|profit|quarter|deliveries)", 0.4, "earnings"),
    (r"\bupgrade[sd]?\b|\braised? to (?:buy|outperform|overweight)|\binitiat\w* (?:at|with) (?:buy|outperform|overweight)", 0.5, "analyst"),
    (r"\bdowngrade[sd]?\b|\bcut to (?:sell|underperform|underweight|neutral|hold)", -0.5, "analyst"),
    (r"\b(?:raises|lifts|boosts) (?:its )?price target\b|\bprice target (?:raised|hiked|lifted)", 0.3, "analyst"),
    (r"\b(?:cuts|lowers|trims) (?:its )?price target\b|\bprice target (?:cut|lowered|slashed)", -0.3, "analyst"),
    (r"\bto (?:be )?acquired?\b|\bagrees? to be (?:bought|acquired)|\btakeover (?:bid|offer)|\bbuyout offer|\bgo[- ]private", 0.9, "deal"),
    (r"\bacqui(?:re|res|sition of)\b|\bmerger\b|\bto buy\b", 0.15, "deal"),
    (r"\bbuyback\b|\brepurchase\b|\bdividend (?:hike|increase|raised)|\braises (?:its )?dividend", 0.4, "capital"),
    (r"\b(?:secondary|stock|share|equity) offering\b|\bdilut|\bat[- ]the[- ]market offering|\bconvertible notes? offering", -0.5, "capital"),
    (r"\bdividend (?:cut|suspend)|\bsuspends? (?:its )?dividend", -0.6, "capital"),
    (r"\bFDA (?:approv|clear|grants)|\bapproval for\b|\bmeets? (?:primary )?endpoint|\bpositive (?:trial|data|results)", 0.8, "fda"),
    (r"\bFDA (?:reject|declin|warning)|\bcomplete response letter|\bfails? (?:trial|endpoint)|\bclinical hold|\bnegative (?:trial|data)", -0.9, "fda"),
    (r"\bwins? (?:a |an )?(?:contract|deal|order)|\bawarded\b|\bpartnership with\b|\bteams? up with\b|\bstrategic (?:deal|agreement)", 0.4, "contract"),
    (r"\bstock split\b", 0.3, "capital"),
    (r"\bsurg(?:e|es|ed|ing)\b|\bsoar(?:s|ed|ing)?\b|\bjump(?:s|ed)?\b|\brall(?:y|ies|ied)\b|\bskyrocket", 0.35, "move"),
    (r"\ball[- ]time high\b|\brecord high\b|\b52-week high\b", 0.3, "move"),
    (r"\b52-week low\b|\bmulti-year low\b", -0.3, "move"),
    (r"\bplung(?:e|es|ed)\b|\bsink(?:s|ing)?\b|\btumbl(?:e|es|ed)\b|\bslump(?:s|ed)?\b|\bcrater|\bsell[- ]?off\b|\bdives?\b", -0.35, "move"),
    (r"\bprobe\b|\binvestigat|\bsubpoena|\bSEC charges\b|\bDOJ\b|\bantitrust\b|\blawsuit\b|\bsued\b|\bclass action\b", -0.4, "legal"),
    (r"\brecall\b|\boutage\b|\bbreach\b|\bhack(?:ed)?\b|\bcyberattack", -0.4, "risk"),
    (r"\bbankrupt|\bchapter 11\b|\bdefault(?:s|ed)?\b|\bgoing concern\b|\bdelist", -1.0, "risk"),
    (r"\b(?:CEO|CFO) (?:resigns|steps down|departs|exits|ousted|fired)|\bsteps down as (?:CEO|CFO)", -0.4, "people"),
    (r"\blayoffs?\b|\bjob cuts\b|\brestructuring\b", -0.1, "people"),
    (r"\bshort seller\b|\bshort report\b|\bfraud\b|\baccounting (?:issue|irregular)", -0.7, "risk"),
    (r"\bS&P 500 (?:index )?(?:addition|inclusion)|\bto join (?:the )?S&P 500|\badded to (?:the )?S&P", 0.6, "index"),
    (r"\bactivist\b|\bstake in\b", 0.3, "activist"),
    (r"\bAI (?:deal|partnership|contract|chip)|\bdata cent(?:er|re) (?:deal|contract)", 0.25, "theme"),
]
_LEX = [(re.compile(rx, re.I), w, tag) for rx, w, tag in LEXICON]

# company names that are also everyday words and cause false matches
AMBIGUOUS = {"Target", "Gap", "Ball", "Match", "Block", "Visa", "Apple Hospitality", "Fox", "News",
             "Global", "Republic", "Progressive", "Principal", "Essex", "Equity", "Public", "General",
             "Dollar", "Discover", "Ross", "Best", "Southern", "Franklin", "Constellation", "Eaton",
             "Expedia", "Paramount", "Live", "Copart", "Williams", "Regions", "Citizens", "Truist"}

SUFFIX = re.compile(r"[,.]?\s+(?:Inc\.?|Corp(?:oration)?\.?|Co\.?|Company|Ltd\.?|plc|PLC|N\.V\.|S\.A\.|"
                    r"Holdings?|Group|Incorporated|Limited|Class [A-C]|\(Class [A-C]\)|& Co\.?|"
                    r"Technologies|Platforms|Brands|Industries|International|Systems)\b.*$")


def score(text):
    """-> (score -1..1, tags, matched phrases)."""
    total, tags, hits = 0.0, [], []
    for rx, w, tag in _LEX:
        m = rx.search(text)
        if m:
            total += w
            hits.append(m.group(0))
            if tag not in tags:
                tags.append(tag)
    # squash: two strong positives ~0.9, one ~0.5
    s = total / (1 + abs(total) * 0.6)
    return round(max(-1.0, min(1.0, s)), 3), tags, hits


def short_name(security):
    n = SUFFIX.sub("", security or "").strip()
    n = re.sub(r"\s*\(.*?\)\s*", " ", n).strip()
    return n


class TickerMatcher(object):
    """Finds tickers in free text: $NVDA, (NASDAQ: NVDA), (NVDA), and company names."""

    def __init__(self, names):
        """names: ticker -> company name (e.g. from the S&P 500 list)."""
        self.tickers = set(names)
        self.by_name = {}
        for t, name in names.items():
            sn = short_name(name)
            if len(sn) >= 4 and sn not in AMBIGUOUS and sn.split()[0] not in AMBIGUOUS:
                self.by_name.setdefault(sn, t)
        parts = sorted(self.by_name, key=len, reverse=True)
        self.name_rx = re.compile(r"\b(" + "|".join(re.escape(p) for p in parts) + r")(?:'s)?\b") if parts else None
        self.cash_rx = re.compile(r"\$([A-Z]{1,5}(?:\.[A-Z])?)\b")
        self.exch_rx = re.compile(r"\((?:NYSE|NASDAQ|Nasdaq|NYSE American|AMEX|Cboe)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\)")
        self.paren_rx = re.compile(r"\(([A-Z]{2,5})\)")

    def find(self, text, strict=False):
        found = []
        for rx in (self.cash_rx, self.exch_rx):
            for m in rx.finditer(text):
                t = m.group(1).replace(".", "-")
                if t not in found:
                    found.append(t)
        for m in self.paren_rx.finditer(text):
            t = m.group(1)
            if t in self.tickers and t not in found:
                found.append(t)
        if not strict and self.name_rx is not None:
            for m in self.name_rx.finditer(text):
                t = self.by_name[m.group(1)]
                if t not in found:
                    found.append(t)
        return found
