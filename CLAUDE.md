# Confluence Scanner

A trading confluence tool for Neel. It scans for setups where market regime, trend,
pattern quality, volume, catalysts and fundamentals line up, on two layers:

- **Daily / swing layer** (`python3 -m scanner scan`): the whole universe (S&P 500, Nasdaq-100,
  sector + index ETFs, micro futures, watchlist, plus today's stocks in play), graded A-D.
- **Intraday layer** (`python3 -m scanner intraday`): 5-minute levels and triggers (ORB, VWAP
  reclaim/loss, prior-day and premarket high/low breaks) for the watchlist the daily scan builds.
  A trigger is **aligned** when it fires in the same direction as a daily A/B setup.

Built on top of the baseline trader-skill pack (MIT, Jake Schincariol), whose 11 skills live in
`.claude/skills/trader-*` and still work on their own. The scanner reuses their parsers through
`scanner/baseline.py` (news and 8-K feeds, SEC XBRL facts, NYSE calendar) and hands orders to
their `trader-risk` -> `trader-broker` flow.

## Commands

```bash
python3 -m scanner doctor                 # check config + which data sources answer
python3 -m scanner premarket              # morning: in-play + scan + intraday levels + dashboard
python3 -m scanner scan [--tickers A,B]   # swing scan only
python3 -m scanner intraday --loop 60     # watch the watchlist, alert on new triggers
python3 -m scanner inplay                 # stocks in play from news, screeners, live 8-Ks
python3 -m scanner ticker NVDA            # one symbol, every layer
python3 -m scanner regime                 # market regime + sector ranks
python3 -m scanner backtest --universe nasdaq100 --years 5
python3 -m scanner journal review|stats|add|close
python3 -m scanner orders [--symbols A,B] # -> trader/orders.json for /trader-risk
python3 -m unittest discover -s tests -v  # offline tests (fixtures, pinned clock)
```

Outputs land in `out/`: `scan.json`, `intraday.json`, `watchlist.json`, `dashboard.html`,
`premarket.md`, `signals.csv` (auto-logged A/B signals), `trades.csv` (your trades), `backtest.json`.
Read the JSON when answering questions; open `dashboard.html` for the visual.

## Code map

| file | job |
|---|---|
| `scanner/config.py` | defaults, `config.json` merge, futures specs, sector ETF maps |
| `scanner/net.py` | HTTP with disk cache, throttling, `--offline` fixture mode |
| `scanner/data.py` | Yahoo chart bars (daily + 5m, stocks/ETFs/futures), Stooq fallback, sessions, market phase |
| `scanner/indicators.py` | pure-list indicators, no look-ahead; `Pack` = all daily indicators |
| `scanner/regime.py` | market score (SPY/QQQ/IWM structure, VIX, HYG, breadth), sector RS ranks |
| `scanner/setups.py` | daily setups (breakout, pullback, gap_go, episodic_pivot, oversold_bounce + short mirrors), trend + participation scores |
| `scanner/headlines.py` | headline lexicon scoring, ticker extraction |
| `scanner/catalysts.py` | earnings calendar (Nasdaq), per-ticker news + 8-Ks, live 8-K feed, catalyst score |
| `scanner/inplay.py` | stocks-in-play discovery |
| `scanner/fundamentals.py` | SEC XBRL growth/margins via baseline trader-analyst |
| `scanner/scoring.py` | 6-component confluence score, grades, sizing, flags |
| `scanner/intraday.py`, `live.py` | 5-minute levels/triggers, cross-layer alignment |
| `scanner/pipeline.py` | the scan end to end |
| `scanner/backtest.py`, `journal.py` | R-multiple backtest, forward-test signal log, trade log |
| `scanner/report.py`, `cli.py` | terminal/Markdown/HTML output, commands |

Standard-library Python 3.9+ only. Keep it that way unless Neel agrees to a dependency.

## Rules when working in this repo

- **Plans, not orders.** Never place or route a trade outside `/trader-risk` -> `/trader-broker`,
  and never without Neel's explicit yes for that exact ticket. Paper trading stays the default.
- **Headlines are leads.** Before telling Neel a catalyst is real, open the story or the 8-K.
- **No predictions.** Describe what the data shows and the plan's levels. Never say what price will do.
- **Show the why.** When presenting a setup give the grade, the component breakdown, entry/stop/targets,
  size and every flag. Flags (earnings inside the hold, against the tide, wide stop) come first.
- **Free data is delayed** (~15 min intraday). Tell him to confirm levels on his broker chart.
- **Changing the scoring or setups?** Run `python3 -m scanner backtest` before and after and
  compare out-of-sample stats by setup and by score bucket. Do not tune on in-sample results alone.
  Keep tests green; regenerate fixtures with `python3 tests/make_fixtures.py` if you change their shape.
- **Secrets** (SEC user agent email, broker keys) live in `config.json` / env vars, which are gitignored.
- Neel prefers concise, direct answers without em dashes.

## Ideas queued (not built yet)

Options/volatility layer (IV rank, expected move into earnings), Alpaca or IBKR real-time data
adapter, intraday backtest on 60 days of 5-minute bars, relative-volume alerts pushed to phone.
