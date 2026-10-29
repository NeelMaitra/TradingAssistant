"""The confluence score: six components, each 0..1, weighted to 100.

  regime        market tide + sector strength in the trade's direction
  trend         moving-average structure, ADX, 52-week position
  setup         quality of the specific pattern (tightness, close, volume)
  participation relative volume, liquidity, gap
  catalyst      headline sentiment, 8-Ks, earnings timing
  fundamentals  growth and margin direction (stocks only)

Components that do not apply (fundamentals for an ETF or future, catalysts
for a future) are dropped and the rest re-weighted, so scores stay comparable.
The grade is a label, not a promise: check every A against the chart and news.
"""

import math

from . import config


def combine(parts, cfg, kind="stock"):
    """parts: name -> 0..1 or None. Returns (score 0..100, grade, breakdown)."""
    w = dict(cfg["weights"])
    if kind != "stock":
        w.pop("fundamentals", None)
    if kind == "future":
        w.pop("catalyst", None)
    total_w = sum(v for k, v in w.items() if parts.get(k) is not None)
    if not total_w:
        return 0.0, "-", {}
    score, breakdown = 0.0, {}
    for k, wt in w.items():
        v = parts.get(k)
        if v is None:
            continue
        pts = 100.0 * wt / total_w * v
        breakdown[k] = {"value": round(v, 3), "points": round(pts, 1), "max": round(100.0 * wt / total_w, 1)}
        score += pts
    return round(score, 1), grade(score, cfg), breakdown


def grade(score, cfg):
    g = cfg["grades"]
    if score >= g["A"]:
        return "A"
    if score >= g["B"]:
        return "B"
    if score >= g["C"]:
        return "C"
    return "D"


def size(plan, cfg, symbol):
    """Shares (stocks/ETFs) or contracts (micro futures) for the configured risk.
    Plans only: nothing here places an order."""
    acct = float(cfg["account_size"])
    risk_dollars = acct * float(cfg["risk_per_trade_pct"]) / 100.0
    rps = plan["risk_per_share"]
    out = {"risk_budget": round(risk_dollars, 2)}
    if symbol.endswith("=F") and symbol in config.FUTURES:
        _name, pv, _tick = config.FUTURES[symbol]
        per = rps * pv
        n = int(math.floor(risk_dollars / per)) if per > 0 else 0
        cap = int(cfg.get("max_contracts", 2))
        if n > cap:
            n = cap
            out["note"] = "capped at %d contracts (max_contracts)" % cap
        out.update({"contracts": n, "risk_per_contract": round(per, 2), "point_value": pv})
        if n == 0:
            out["note"] = "1 contract risks $%.0f, over your $%.0f budget: skip or tighten" % (per, risk_dollars)
        out["risk_total"] = round(max(n, 0) * per, 2)
        return out
    shares = int(math.floor(risk_dollars / rps)) if rps > 0 else 0
    cap = int(math.floor(acct * float(cfg["max_position_pct"]) / 100.0 / plan["entry"])) if plan["entry"] > 0 else 0
    note = None
    if shares > cap:
        shares, note = cap, "capped at %s%% of the account" % cfg["max_position_pct"]
    out.update({"shares": shares, "position_value": round(shares * plan["entry"], 2),
                "risk_total": round(shares * rps, 2)})
    if note:
        out["note"] = note
    return out


def flags(plan, cfg, regime_value, cat_reasons):
    f = []
    rr = None
    if plan.get("targets") and plan["risk_per_share"]:
        rr = abs(plan["targets"][-1] - plan["entry"]) / plan["risk_per_share"]
    if plan["setup"] in ("oversold_bounce", "overbought_fade"):
        pass  # mean reversion targets the 8 EMA, R:R is naturally lower
    elif rr is not None and rr < cfg["min_reward_risk"]:
        f.append("reward:risk under %.1f" % cfg["min_reward_risk"])
    if regime_value is not None and regime_value < 0.35:
        f.append("against the market/sector tide")
    if any("binary risk" in r or "TODAY" in r for r in cat_reasons):
        f.append("earnings inside the hold")
    if plan["risk_atr"] > 1.8:
        f.append("wide stop (%.1f ATR)" % plan["risk_atr"])
    return f
