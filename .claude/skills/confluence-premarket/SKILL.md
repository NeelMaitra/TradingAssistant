---
name: confluence-premarket
description: >-
  Neel's morning trading prep. Runs the confluence scanner's premarket routine
  (stocks in play from news, screeners and live 8-Ks; full swing scan of S&P 500,
  Nasdaq-100, sector ETFs and micro futures; market regime and sector ranks;
  intraday levels for the watchlist), verifies the catalysts behind the best
  setups, and briefs the A/B plans with entries, stops, targets and size. Use when
  the user says "premarket", "morning scan", "what's in play", "prep my day",
  "what should I watch today", "run the scanner", or "any A setups".
argument-hint: "[--tickers A,B,C]"
---

# confluence-premarket

## Steps

1. Run it (from the repo root):

   ```bash
   python3 -m scanner premarket --json > out/premarket.json 2> out/premarket.log; tail -3 out/premarket.log
   ```

   If the user passed tickers, add `--tickers A,B,C`. If the run errors, run
   `python3 -m scanner doctor` and report what failed.

2. Read `out/scan.json` (regime, sectors, candidates, inplay, watchlist) and
   `out/intraday.json` (levels and pending plans).

3. Verify catalysts for every A/B candidate and the top 5 in-play names: open the
   linked headline or 8-K (WebFetch) and confirm what actually happened. If a story is
   paywalled, say so. If the headline was misread by the word list, say the score is wrong.

4. Brief Neel in this order, short:
   - **Tide:** regime label + score, the 2-3 reasons that matter, leading and lagging sectors.
   - **A/B setups** (max 6): symbol, setup, direction, grade/score, entry, stop, 2R/3R, size,
     flags first, then the one-line why. Mention which components carried the score.
   - **In play:** top names with the verified catalyst and whether a setup exists.
   - **Intraday plan:** for each watchlist name, the premarket high/low and prior-day levels,
     and the pending long/short triggers. Index futures (MES/MNQ) bias from the regime.
   - **Risk notes:** earnings today, names flagged against the tide, data notes count.

5. Point him to `out/dashboard.html` for the full table.

## Rules

- Plans only. Never place orders. If he wants to act, use `python3 -m scanner orders --symbols X`
  then `/trader-risk` and `/trader-broker`, which require his yes per ticket.
- Never predict price. Grades rank confluence; they are not probabilities.
- Free data is delayed; tell him to confirm levels on his broker chart.
- No em dashes.
