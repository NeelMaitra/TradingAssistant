"""What gets scanned: S&P 500 (+ GICS sector), Nasdaq-100, sector and index ETFs,
micro futures, your watchlist, plus anything the in-play finder adds that day.
"""

import csv
import io
import os

from . import config
from .net import NetError

SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
SP500_FILE = os.path.join(config.ROOT, "data", "sp500.csv")

# Nasdaq-100 snapshot. Names that no longer trade simply fail to load and are skipped.
NASDAQ100 = """AAPL MSFT NVDA AMZN GOOGL GOOG META AVGO TSLA COST NFLX ASML AMD PEP TMUS CSCO
ADBE LIN QCOM TXN INTU AMGN ISRG BKNG CMCSA HON AMAT PDD ARM GILD VRTX ADP PANW SBUX ADI MU
LRCX MELI KLAC REGN INTC MDLZ CRWD CTAS SNPS CDNS PYPL MAR ORLY CEG ABNB FTNT MRVL DASH WDAY
ADSK ROP CSX PCAR NXPI CHTR APP AEP MNST CPRT TTD PAYX ROST FAST KDP ODFL BKR EXC VRSK FANG XEL
EA CTSH DDOG GEHC KHC TEAM AZN LULU CCEP IDXX MCHP CSGP TTWO ZS ON DXCM BIIB WBD CDW GFS MDB
PLTR MSTR AXON SHOP""".split()


def _read_sp500(text):
    out = {}
    for r in csv.DictReader(io.StringIO(text)):
        sym = (r.get("Symbol") or "").strip().upper()
        if not sym:
            continue
        out[sym] = {"name": r.get("Security", ""), "sector": r.get("GICS Sector", ""),
                    "industry": r.get("GICS Sub-Industry", ""), "cik": r.get("CIK", "")}
    return out


def sp500(fetcher=None, refresh=False):
    """ticker -> {name, sector, industry, cik}. Bundled snapshot, refreshed weekly if online."""
    text = None
    if fetcher is not None and (refresh or not os.path.isfile(SP500_FILE)) and not fetcher.offline:
        try:
            text = fetcher.get(SP500_URL, "sp500_constituents.csv",
                               ttl=fetcher.cfg["cache_minutes"]["universe"]).decode("utf-8")
            with open(SP500_FILE, "w", encoding="utf-8") as fh:
                fh.write(text)
        except NetError as exc:
            fetcher.note("S&P 500 list not refreshed (%s); using the bundled snapshot" % exc)
    if text is None and os.path.isfile(SP500_FILE):
        with open(SP500_FILE, encoding="utf-8") as fh:
            text = fh.read()
    return _read_sp500(text or "")


def build(cfg, fetcher=None, extra=None):
    """symbol -> info dict {kind, name, sector, sector_etf}."""
    u = cfg["universe"]
    out = {}
    if u.get("index_etfs", True):
        for s in config.INDEX_ETFS:
            out[s] = {"kind": "etf", "name": s, "sector": "Index", "sector_etf": None}
    if u.get("sector_etfs", True):
        for s, name in config.SECTOR_ETFS.items():
            out[s] = {"kind": "etf", "name": name + " ETF", "sector": name, "sector_etf": s}
    if u.get("sp500", True):
        for s, r in sp500(fetcher).items():
            out[s] = {"kind": "stock", "name": r["name"], "sector": r["sector"],
                      "industry": r["industry"], "sector_etf": config.GICS_TO_ETF.get(r["sector"])}
    if u.get("nasdaq100", True):
        for s in NASDAQ100:
            out.setdefault(s, {"kind": "stock", "name": s, "sector": "", "sector_etf": None})
    if u.get("futures", True):
        for s, (name, _pv, _tick) in config.FUTURES.items():
            out[s] = {"kind": "future", "name": name, "sector": "Futures", "sector_etf": None}
    for s in list(u.get("watchlist") or []) + list(extra or []):
        s = s.strip().upper()
        if s and s not in out:
            out[s] = {"kind": "future" if s.endswith("=F") else "stock", "name": s,
                      "sector": "", "sector_etf": None, "added": "watchlist" if s in (u.get("watchlist") or []) else "in-play"}
    return out


def is_future(sym):
    return sym.upper().endswith("=F")


def display(sym):
    """MES=F -> MES, BRK-B stays readable."""
    return sym[:-2] if sym.endswith("=F") else sym
