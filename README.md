# Confluence Scanner

A trading tool that highlights opportunities where several independent signals line up, so you
can trade the same process every day and use the grade as one piece of confluence.

Two layers:

- **Swing (daily):** scans the S&P 500, Nasdaq-100, sector and index ETFs, micro futures
  (MES, MNQ, M2K, MYM, MGC, MCL), your watchlist and today's stocks in play. Each setup gets a
  0-100 confluence score and an A-D grade with a plan: entry, stop, 1R/2R/3R targets, size.
- **Intraday (5-minute):** for the watchlist the daily scan builds: prior-day and premarket
  levels, opening range, VWAP, relative volume and relative strength vs SPY, and triggers
  (ORB, VWAP reclaim/loss, level breaks). A trigger in the same direction as a daily A/B setup is
  marked **aligned**: that is the highest-confluence signal the tool produces.

Built on [trader-skill](https://github.com/Jakeschincariol/trader-skill) (MIT). Its 11 Claude
skills ship in `.claude/skills/trader-*` and the scanner reuses their SEC, news and calendar code.
Standard-library Python 3.9+, no API keys, no pip installs.

## The score

| component | weight | what it measures |
|---|---|---|
| regime | 20 | SPY/QQQ/IWM trend structure, VIX level and direction, credit (HYG), breadth; plus the stock's sector rank |
| trend | 20 | MA stack (20 EMA / 50 / 200 SMA), 50-day slope, 3-month return, 52-week position, ADX |
| setup | 20 | pattern quality: base tightness, close location, volume on the trigger bar |
| participation | 10 | relative volume, dollar volume, gap size |
| catalyst | 15 | headline sentiment and type, important 8-Ks, earnings reactions; **penalty** for earnings inside a swing hold |
| fundamentals | 15 | SEC XBRL revenue and EPS growth, operating margin and its trend |

Components that do not apply (fundamentals for ETFs and futures, catalysts for futures) are dropped
and the rest re-weighted. Grades: A >= 75, B >= 60, C >= 45. Every score ships with its reasons and
flags (earnings in the hold, against the tide, wide stop, size 0). Weights live in `config.json`.

Setups: `breakout`, `pullback`, `gap_go`, `episodic_pivot`, `oversold_bounce` and the short mirrors
`breakdown`, `failed_rally`, `gap_down`, `overbought_fade`.

Stocks in play come from market news feeds (tickers pulled out of headlines and scored), Yahoo's
gainers/losers/most-active screeners, SEC's live 8-K feed, and the universe's own gaps and volume.

## Setup

```bash
git clone <this repo> && cd confluence-scanner
cp config.example.json config.json      # set sec_user_agent, account_size, risk_per_trade_pct
python3 -m scanner doctor               # checks every data source
python3 -m unittest discover -s tests   # offline tests
```

SEC requires a User-Agent with your name and email for 8-Ks and fundamentals. Without it those
parts are skipped and the rest still runs.

## Daily routine

```bash
python3 -m scanner premarket            # ~8:30 ET: in play + full scan + intraday levels
open out/dashboard.html
python3 -m scanner intraday --loop 60 --bell   # after the open: alerts on new triggers
python3 -m scanner ticker NVDA          # deep dive any name
python3 -m scanner journal add ...      # log what you take; journal close ... when out
python3 -m scanner journal review       # weekly: how did the logged signals actually do
```

Or in Claude Code just say "premarket", "any triggers", "check NVDA", "log a trade",
"backtest the setups". The project skills (`.claude/skills/confluence-*`) drive the CLI, verify
the headlines behind each catalyst and brief you.

## Make it something you can trust

1. **Backtest first:** `python3 -m scanner backtest --universe nasdaq100 --years 5`. Look at
   out-of-sample expectancy by setup and whether higher score buckets really do better. Only trade
   setups that hold up out of sample with a decent sample size.
2. **Forward test:** every scan logs its A/B signals to `out/signals.csv`; `journal review`
   grades them against real prices. Paper trade until the live record matches the backtest.
3. **Journal:** log your real trades with `--followed yes/no` to see what discipline is worth.

## Execution (optional)

The scanner never places orders. `python3 -m scanner orders --symbols NVDA` writes long stock/ETF
plans as stop-entry proposals to `trader/orders.json`; then `/trader-risk` checks them and
`/trader-broker` shows each ticket and needs your explicit yes (Alpaca paper by default). Attach
your protective stop right after any fill.

## Limits

Free data: Yahoo quotes are delayed (~15 min intraday) and the endpoints are unofficial; confirm
levels on your broker. The headline scorer is a transparent word list, so read the story. 13F,
Congress and backtest data all have their own lags and biases. This is software that reads public
data and does arithmetic. It is not financial advice and cannot see the future.
