"""Output: terminal text, Markdown and a self-contained HTML dashboard."""

import html
import os

from . import config

COMPONENTS = ["regime", "trend", "setup", "participation", "catalyst", "fundamentals"]
COLORS = {"regime": "#6366f1", "trend": "#0ea5e9", "setup": "#10b981", "participation": "#f59e0b",
          "catalyst": "#ec4899", "fundamentals": "#8b5cf6"}


def _f(x, n=2):
    if x is None:
        return "-"
    if isinstance(x, (int, float)):
        return ("%." + str(n) + "f") % x
    return str(x)


def _px(x):
    if x is None:
        return "-"
    return "%.2f" % x if abs(x) >= 1 else "%.4f" % x


def _size(sz):
    if not sz:
        return "-"
    if "contracts" in sz:
        return "%d ct ($%.0f risk)" % (sz["contracts"], sz.get("risk_total") or 0)
    return "%d sh ($%.0f risk)" % (sz.get("shares", 0), sz.get("risk_total") or 0)


# ------------------------------------------------------------------ terminal

def text(scan, intraday=None, top=15):
    out = []
    r = scan["regime"]
    out.append("CONFLUENCE SCAN  %s  (bars through %s, market %s)"
               % (scan["generated_at"], scan.get("bars_through"), scan["phase"]))
    out.append("")
    out.append("REGIME: %s (%+.2f)" % (r["label"], r["score"]))
    for x in r["reasons"]:
        out.append("  - " + x)
    if scan["sectors"]:
        lead = [s["etf"] for s in scan["sectors"] if s["status"] == "leading"]
        lag = [s["etf"] for s in scan["sectors"] if s["status"] == "lagging"]
        out.append("  leading: %s | lagging: %s" % (", ".join(lead), ", ".join(lag)))
    out.append("")
    out.append("TOP SETUPS")
    out.append("  %-2s %-6s %-15s %-5s %5s  %9s %9s %9s  %-18s %s" %
               ("Gr", "Sym", "Setup", "Dir", "Score", "Entry", "Stop", "2R", "Size", "Flags"))
    for c in scan["candidates"][:top]:
        p = c["plan"]
        out.append("  %-2s %-6s %-15s %-5s %5.0f  %9s %9s %9s  %-18s %s" %
                   (c["grade"], c["display"], p["setup"], p["direction"], c["score"], _px(p["entry"]),
                    _px(p["stop"]), _px(p["targets"][1]), _size(c.get("sizing")), "; ".join(c["flags"])[:60]))
    if scan.get("inplay"):
        out.append("")
        out.append("STOCKS IN PLAY")
        for x in scan["inplay"][:12]:
            head = (x.get("headlines") or [{}])[0].get("title", "")
            out.append("  %-6s score %.2f %-7s chg %s  rvol %s  %s  %s" %
                       (x["ticker"], x["score"], x.get("bias", ""), _f(x.get("chg_pct"), 1),
                        _f(x.get("daily_rvol") or x.get("rvol"), 1), ",".join(x.get("catalysts", [])[:3]),
                        head[:70]))
    if intraday:
        out.append("")
        out.append(intraday_text(intraday))
    if scan.get("error_count"):
        out.append("")
        out.append("(%d data notes, see out/scan.json 'errors')" % scan["error_count"])
    return "\n".join(out)


def intraday_text(res):
    out = ["INTRADAY  %s  (%s)" % (res["generated_at"], res["phase"])]
    spy = res.get("spy") or {}
    if spy:
        out.append("  SPY %s (%s%%) %s VWAP %s" % (_px(spy.get("last")), _f(spy.get("change_pct")),
                                                  "above" if spy.get("above_vwap") else "below",
                                                  _px(spy.get("vwap"))))
    for r in res["rows"]:
        lv = r["levels"]
        head = "  %-6s %s  last %s  chg %s%%  RS %s  rvol %s  VWAP %s" % (
            r["display"], ("[%s %s]" % (r["daily"].get("grade") or "-", r["daily"].get("direction") or "")).ljust(10),
            _px(r["last"]), _f(r.get("change_pct")), _f(r.get("rs_vs_spy")), _f(r.get("rvol")), _px(r.get("vwap")))
        out.append(head)
        out.append("         levels: " + "  ".join("%s %s" % (k.upper(), _px(v)) for k, v in lv.items()))
        for t in r["triggers"]:
            out.append("         %s %s %s entry %s stop %s 2R %s  q %s  %s" % (
                "**ALIGNED**" if t.get("aligned") else "trigger", t["trigger"], t["direction"], _px(t["entry"]),
                _px(t["stop"]), _px(t["targets"][1]), _f(t.get("intraday_quality")), _size(t.get("sizing"))))
        for t in r["plans"]:
            out.append("         plan %s: %s (stop %s)" % (t["trigger"], t["reasons"][0], _px(t["stop"])))
    return "\n".join(out)


# ------------------------------------------------------------------ html

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1c1c1e;--muted:#6b6b70;--line:#e6e6e3;--long:#0f9d58;--short:#d93025;
--a:#0f9d58;--b:#3b82f6;--c:#b7791f;--d:#9ca3af;--chip:#f0f0ed}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#0f1012;--card:#17181b;--ink:#ececec;
--muted:#9a9aa1;--line:#2a2b30;--chip:#22242a}}
:root[data-theme="dark"]{--bg:#0f1012;--card:#17181b;--ink:#ececec;--muted:#9a9aa1;--line:#2a2b30;--chip:#22242a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
main{max-width:1240px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:20px;margin:0 0 2px}h2{font-size:15px;margin:0 0 10px;letter-spacing:.02em}
.sub{color:var(--muted);font-size:12.5px}.grid{display:grid;gap:14px;grid-template-columns:1fr}
@media(min-width:900px){.grid.two{grid-template-columns:1.2fr 1fr}}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin-top:14px;overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13px}th{color:var(--muted);font-weight:600;text-align:left;
font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;border-bottom:1px solid var(--line);padding:6px 8px;white-space:nowrap}
td{border-bottom:1px solid var(--line);padding:7px 8px;vertical-align:top}tr:last-child td{border-bottom:0}
.num{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.g{display:inline-block;min-width:22px;text-align:center;border-radius:6px;font-weight:700;color:#fff;padding:1px 6px}
.gA{background:var(--a)}.gB{background:var(--b)}.gC{background:var(--c)}.gD,.g-{background:var(--d)}
.long{color:var(--long);font-weight:600}.short{color:var(--short);font-weight:600}
.chip{display:inline-block;background:var(--chip);border-radius:999px;padding:1px 8px;margin:1px 2px 1px 0;font-size:11.5px;white-space:nowrap}
.flag{background:rgba(217,48,37,.12);color:var(--short)}.ok{background:rgba(15,157,88,.12);color:var(--long)}
.bar{display:flex;height:8px;width:120px;border-radius:4px;overflow:hidden;background:var(--chip)}
.bar span{display:block;height:100%}details summary{cursor:pointer;color:var(--muted);font-size:12px}
.why{font-size:12.5px;color:var(--muted);margin:6px 0 2px}.why b{color:var(--ink);font-weight:600}
.regime{display:flex;align-items:center;gap:14px;flex-wrap:wrap}.big{font-size:26px;font-weight:700}
.meter{position:relative;height:10px;flex:1;min-width:160px;border-radius:5px;
background:linear-gradient(90deg,var(--short),#e5c158,var(--long))}
.meter i{position:absolute;top:-4px;width:4px;height:18px;background:var(--ink);border-radius:2px}
a{color:inherit}.legend span{margin-right:10px;font-size:11.5px;color:var(--muted)}
.legend i{display:inline-block;width:9px;height:9px;border-radius:2px;margin-right:4px;vertical-align:-1px}
.foot{color:var(--muted);font-size:12px;margin-top:18px}
"""


def _e(x):
    return html.escape(str(x if x is not None else ""))


def _bar(bd):
    spans = []
    for k in COMPONENTS:
        if k in bd:
            spans.append('<span title="%s %s/%s" style="width:%.1f%%;background:%s"></span>'
                         % (k, bd[k]["points"], bd[k]["max"], bd[k]["points"], COLORS[k]))
    return '<div class="bar">%s</div>' % "".join(spans)


def _why(c):
    rows = []
    for k in COMPONENTS:
        v = c["why"].get(k)
        b = c["breakdown"].get(k)
        if v is None or b is None:
            continue
        rows.append('<div class="why"><b>%s %s/%s</b> &middot; %s</div>'
                    % (k.title(), _e(b["points"]), _e(b["max"]), _e("; ".join(v))))
    for h in (c.get("headlines") or [])[:3]:
        rows.append('<div class="why">&rarr; <a href="%s" target="_blank" rel="noopener">%s</a></div>'
                    % (_e(h.get("link")), _e(h["title"])))
    return "".join(rows)


def dashboard(scan, intraday=None, path=None):
    r = scan["regime"]
    pos = (r["score"] + 1) / 2 * 100
    secs = "".join('<tr><td class="num">%d</td><td><b>%s</b> %s</td><td class="num">%+.1f</td>'
                   '<td class="num">%+.1f%%</td><td><span class="chip %s">%s</span></td></tr>'
                   % (s["rank"], _e(s["etf"]), _e(s["sector"]), s["rs"], s["roc20"],
                      "ok" if s["status"] == "leading" else "flag" if s["status"] == "lagging" else "",
                      s["status"]) for s in scan["sectors"])
    rows = []
    for c in scan["candidates"][:40]:
        p = c["plan"]
        flags = "".join('<span class="chip flag">%s</span>' % _e(f) for f in c["flags"])
        earn = c.get("earnings")
        if earn:
            flags += '<span class="chip">earnings %s</span>' % _e(earn["date"])
        rows.append(
            '<tr><td><span class="g g%s">%s</span></td><td><b>%s</b><div class="sub">%s</div></td>'
            '<td>%s<div class="sub">%s</div></td><td class="%s">%s</td><td class="num">%.0f %s</td>'
            '<td class="num">%s</td><td class="num">%s</td><td class="num">%s<div class="sub">%s</div></td>'
            '<td class="num">%s</td><td>%s<details><summary>why</summary>%s</details></td></tr>'
            % (c["grade"], c["grade"], _e(c["display"]), _e((c.get("name") or "")[:26]), _e(p["setup"]),
               _e(p["hold"]), p["direction"], p["direction"], c["score"], _bar(c["breakdown"]),
               _px(p["entry"]), _px(p["stop"]), _px(p["targets"][1]), "3R " + _px(p["targets"][2]),
               _e(_size(c.get("sizing"))), flags, _why(c)))
    ip = []
    for x in scan.get("inplay", [])[:25]:
        h = (x.get("headlines") or [{}])[0]
        head = ('<a href="%s" target="_blank" rel="noopener">%s</a>' % (_e(h.get("link")), _e(h.get("title")))
                if h.get("title") else "")
        if x.get("filings"):
            head += ' <span class="chip">8-K: %s</span>' % _e(", ".join(x["filings"][0]["labels"]))
        ip.append('<tr><td><b>%s</b></td><td class="num">%.2f</td><td class="%s">%s</td><td class="num">%s</td>'
                  '<td class="num">%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'
                  % (_e(x["ticker"]), x["score"], x.get("bias", ""), _e(x.get("bias")), _f(x.get("chg_pct"), 1),
                     _f(x.get("daily_rvol") or x.get("rvol"), 1),
                     "".join('<span class="chip">%s</span>' % _e(k) for k in (x.get("catalysts") or [])[:4]),
                     _e(", ".join(x.get("setups") or [])), head))
    intr = ""
    if intraday and intraday.get("rows"):
        trs = []
        for rr in intraday["rows"]:
            trig = "".join('<div>%s<b class="%s">%s</b> %s &middot; entry %s stop %s 2R %s &middot; %s</div>'
                           % ('<span class="chip ok">aligned</span>' if t.get("aligned") else "",
                              t["direction"], _e(t["trigger"]), _e(t["reasons"][0]), _px(t["entry"]), _px(t["stop"]),
                              _px(t["targets"][1]), _e(_size(t.get("sizing")))) for t in rr["triggers"])
            trig += "".join('<div class="sub">plan: %s (stop %s)</div>' % (_e(t["reasons"][0]), _px(t["stop"]))
                            for t in rr["plans"])
            lv = " ".join('<span class="chip">%s %s</span>' % (_e(k.upper()), _px(v)) for k, v in rr["levels"].items())
            d = rr["daily"]
            trs.append('<tr><td><b>%s</b><div class="sub">%s %s</div></td><td class="num">%s<div class="sub">%s%%</div></td>'
                       '<td class="num">%s</td><td class="num">%s</td><td class="num">%s</td><td>%s<div>%s</div></td></tr>'
                       % (_e(rr["display"]), _e(d.get("grade") or ""), _e(d.get("direction") or ""), _px(rr["last"]),
                          _f(rr.get("change_pct")), _px(rr.get("vwap")), _f(rr.get("rs_vs_spy")), _f(rr.get("rvol")),
                          trig or '<span class="sub">no trigger</span>', lv))
        intr = ('<div class="card"><h2>Intraday triggers <span class="sub">%s &middot; %s</span></h2><table>'
                '<tr><th>Sym</th><th class="num">Last</th><th class="num">VWAP</th><th class="num">RS vs SPY</th>'
                '<th class="num">RVOL</th><th>Triggers / levels</th></tr>%s</table></div>'
                % (_e(intraday["generated_at"]), _e(intraday["phase"]), "".join(trs)))
    legend = "".join('<span><i style="background:%s"></i>%s</span>' % (COLORS[k], k) for k in COMPONENTS)
    errs = "".join("<li>%s</li>" % _e(x) for x in scan.get("errors", [])[:40])
    doc = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Confluence Scanner</title>
<style>%s</style></head><body><main>
<h1>Confluence Scanner</h1>
<div class="sub">Generated %s &middot; daily bars through %s &middot; market %s &middot; %d symbols loaded &middot;
sizing at %s%% risk of $%s</div>
<div class="grid two">
<div class="card"><h2>Market regime</h2><div class="regime"><div class="big">%s</div>
<div class="meter"><i style="left:calc(%.1f%% - 2px)"></i></div><div class="sub">%+.2f</div></div>
<ul class="sub">%s</ul></div>
<div class="card"><h2>Sectors by relative strength</h2><table><tr><th class="num">#</th><th>Sector</th>
<th class="num">RS</th><th class="num">20d</th><th>Status</th></tr>%s</table></div></div>
%s
<div class="card"><h2>Setups ranked by confluence</h2><div class="legend">%s</div><table>
<tr><th>Gr</th><th>Symbol</th><th>Setup</th><th>Dir</th><th class="num">Score</th><th class="num">Entry</th>
<th class="num">Stop</th><th class="num">Target 2R</th><th class="num">Size</th><th>Flags / why</th></tr>%s</table></div>
<div class="card"><h2>Stocks in play</h2><table><tr><th>Sym</th><th class="num">Score</th><th>Bias</th>
<th class="num">Chg %%</th><th class="num">RVOL</th><th>Catalysts</th><th>Setups</th><th>Top headline</th></tr>%s</table></div>
<div class="card"><details><summary>%d data notes</summary><ul class="sub">%s</ul></details></div>
<p class="foot">Plans, not orders. Free data is delayed; headlines are leads, not facts: open the story or the
8-K before acting. Scores rank confluence, they do not predict. Nothing here places a trade: orders go through
trader-risk and trader-broker, which need your explicit yes. Not financial advice.</p>
</main></body></html>""" % (
        CSS, _e(scan["generated_at"]), _e(scan.get("bars_through")), _e(scan["phase"]), scan["loaded"],
        _e(scan["settings"]["risk_per_trade_pct"]), _e(scan["settings"]["account_size"]),
        _e(r["label"]), pos, r["score"], "".join("<li>%s</li>" % _e(x) for x in r["reasons"]), secs,
        intr, legend, "".join(rows) or '<tr><td colspan="10" class="sub">No setups today.</td></tr>',
        "".join(ip) or '<tr><td colspan="8" class="sub">Nothing flagged.</td></tr>',
        scan.get("error_count", 0), errs)
    path = path or os.path.join(config.out_dir(), "dashboard.html")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(doc)
    return path


def markdown(scan, top=10):
    r = scan["regime"]
    out = ["# Confluence scan %s" % scan["generated_at"][:16].replace("T", " "), "",
           "**Regime:** %s (%+.2f). %s" % (r["label"], r["score"], "; ".join(r["reasons"])), ""]
    lead = [s["etf"] for s in scan["sectors"] if s["status"] == "leading"]
    if lead:
        out.append("**Leading sectors:** " + ", ".join(lead))
        out.append("")
    out.append("| Gr | Sym | Setup | Dir | Score | Entry | Stop | 2R | Size |")
    out.append("|---|---|---|---|---|---|---|---|---|")
    for c in scan["candidates"][:top]:
        p = c["plan"]
        out.append("| %s | %s | %s | %s | %.0f | %s | %s | %s | %s |" % (
            c["grade"], c["display"], p["setup"], p["direction"], c["score"], _px(p["entry"]),
            _px(p["stop"]), _px(p["targets"][1]), _size(c.get("sizing"))))
    return "\n".join(out) + "\n"
