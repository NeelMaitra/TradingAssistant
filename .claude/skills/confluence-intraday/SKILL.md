---
name: confluence-intraday
description: >-
  Intraday trigger check for Neel's watchlist using the confluence scanner's
  5-minute layer: opening range breaks, VWAP reclaim/loss, prior-day and premarket
  high/low breaks, relative volume and relative strength vs SPY, and whether each
  trigger lines up with the daily A/B setup ("aligned"). Use when the user says
  "any triggers", "check the watchlist", "what's breaking out", "is NVDA above
  VWAP", "watch these for me", "intraday scan", or during market hours.
argument-hint: "[--tickers A,B] [--loop 60]"
---

# confluence-intraday

## Steps

1. If `out/watchlist.json` is missing or from a previous day, run the premarket skill first
   (or pass `--tickers`).
2. One check:

   ```bash
   python3 -m scanner intraday --json > out/intraday_check.json
   ```

   To keep watching, run `python3 -m scanner intraday --loop 60 --bell` in the background and
   report each `>>> NEW` line as it appears (stop when the market closes).
3. Read the rows. Lead with **aligned** triggers (daily A/B + intraday trigger, same direction),
   then other triggers ranked by `intraday_quality`.
4. For each trigger give: symbol, trigger, direction, entry, stop, 1R/2R, size, VWAP side,
   RS vs SPY, RVOL, and the daily context (grade, setup). Note when price is already well past
   the entry (chasing) by comparing `last` to `entry` in R.
5. Mention SPY's position vs its VWAP as the intraday tide.

## Rules

- Bars are ~15 minutes delayed on free data. Say so and tell him to confirm on his chart.
- Plans only; execution goes through `/trader-risk` -> `/trader-broker` with his yes.
- No predictions, no em dashes.
