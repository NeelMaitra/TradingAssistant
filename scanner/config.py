"""Settings: defaults merged with config.json (gitignored) and environment variables."""

import copy
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    # SEC asks every script to identify itself: "Your Name you@example.com".
    "sec_user_agent": "",

    # Account and risk (used only to size the plans; nothing is ever placed).
    "account_size": 10000,
    "risk_per_trade_pct": 0.5,        # % of account risked between entry and stop
    "max_position_pct": 25,           # cap on any one stock position
    "min_reward_risk": 2.0,           # plans below this R:R are flagged
    "max_contracts": 2,               # hard cap per micro futures plan

    # Universe
    "universe": {
        "sp500": True,
        "nasdaq100": True,
        "sector_etfs": True,
        "index_etfs": True,
        "futures": True,              # micro futures (MES, MNQ, M2K, MYM, MGC, MCL)
        "watchlist": [],              # your own tickers, always scanned
        "min_price": 5.0,
        "min_avg_dollar_volume": 20_000_000,   # 20-day average, stocks only
    },

    # Scoring weights (each component is scored 0..1, then weighted to 100)
    "weights": {
        "regime": 20,
        "trend": 20,
        "setup": 20,
        "participation": 10,
        "catalyst": 15,
        "fundamentals": 15,
    },
    "grades": {"A": 75, "B": 60, "C": 45},

    # Setup parameters
    "setups": {
        "breakout_lookback": 20,
        "contraction_ratio": 0.85,     # ATR(10)/ATR(50) below this = tight
        "pullback_atr_band": 0.6,      # low within this many ATRs of the 20 EMA
        "gap_pct": 3.0,
        "episodic_gap_pct": 8.0,
        "rvol_high": 1.5,
        "earnings_buffer_days": 3,     # swing trades into earnings get penalised
    },

    # Intraday layer
    "intraday": {
        "interval": "5m",
        "opening_range_minutes": 15,
        "watchlist_size": 15,
        "rvol_days": 10,
    },

    # In-play discovery
    "inplay": {
        "rss_feeds": [
            "https://finance.yahoo.com/news/rssindex",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            "https://feeds.content.dowjones.io/public/rss/mw_topstories",
            "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
        ],
        "use_yahoo_screeners": True,
        "use_sec_current_8k": True,
        "max_items": 400,
        "hours": 18,
    },

    # Fundamentals are fetched only for the shortlist (they are slow and change quarterly)
    "fundamentals_shortlist": 40,

    # Network
    "threads": 8,
    "cache_minutes": {"daily": 240, "intraday": 1, "news": 10, "earnings": 360,
                      "fundamentals": 10080, "universe": 10080},

    "paper": True,
}

FUTURES = {
    # Yahoo symbol: (name, dollars per point, tick size)
    "MES=F": ("Micro E-mini S&P 500", 5.0, 0.25),
    "MNQ=F": ("Micro E-mini Nasdaq-100", 2.0, 0.25),
    "M2K=F": ("Micro E-mini Russell 2000", 5.0, 0.1),
    "MYM=F": ("Micro E-mini Dow", 0.5, 1.0),
    "MGC=F": ("Micro Gold", 10.0, 0.1),
    "MCL=F": ("Micro WTI Crude", 100.0, 0.01),
}

SECTOR_ETFS = {
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy", "XLV": "Health Care",
    "XLI": "Industrials", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
    "XLU": "Utilities", "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication Services",
    "SMH": "Semiconductors", "XBI": "Biotech", "KRE": "Regional Banks", "ITB": "Homebuilders",
}

# GICS sector name (S&P 500 constituents file) -> sector ETF
GICS_TO_ETF = {
    "Information Technology": "XLK", "Financials": "XLF", "Energy": "XLE",
    "Health Care": "XLV", "Industrials": "XLI", "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP", "Utilities": "XLU", "Materials": "XLB",
    "Real Estate": "XLRE", "Communication Services": "XLC",
}

INDEX_ETFS = ["SPY", "QQQ", "IWM", "DIA", "TLT", "GLD", "USO", "HYG"]


def _merge(base, extra):
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def load(path=None):
    """DEFAULTS <- config.json <- env. Missing file is fine."""
    cfg = copy.deepcopy(DEFAULTS)
    path = path or os.environ.get("CONFLUENCE_CONFIG") or os.path.join(ROOT, "config.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            _merge(cfg, json.load(fh))
    ua = os.environ.get("SEC_USER_AGENT")
    if ua:
        cfg["sec_user_agent"] = ua
    if not cfg["sec_user_agent"]:
        # fall back to the baseline skills' config, if the user set it there
        tcfg = os.path.join(ROOT, "trader", "config.json")
        if os.path.isfile(tcfg):
            try:
                with open(tcfg, encoding="utf-8") as fh:
                    cfg["sec_user_agent"] = json.load(fh).get("sec_user_agent", "") or ""
            except (OSError, ValueError):
                pass
    if "you@example.com" in (cfg["sec_user_agent"] or ""):
        cfg["sec_user_agent"] = ""
    return cfg


def out_dir(cfg=None):
    d = os.environ.get("CONFLUENCE_OUT") or os.path.join(ROOT, "out")
    os.makedirs(d, exist_ok=True)
    return d


def data_dir():
    d = os.environ.get("CONFLUENCE_DATA") or os.path.join(ROOT, "data")
    os.makedirs(d, exist_ok=True)
    return d
