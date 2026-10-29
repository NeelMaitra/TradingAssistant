---
name: confluence-backtest
description: >-
  Backtests the confluence scanner's daily setups in R multiples (win rate,
  expectancy, profit factor, drawdown) by setup, by technical confluence score
  bucket and by market regime, with an in-sample / out-of-sample split; also
  used before and after any change to scoring or setup rules. Use when the user
  says "backtest", "does the breakout setup work", "which setups are worth
  trading", "test this change", "is a higher score better", or "tune the scanner".
argument-hint: "[--universe nasdaq100|sp500|etfs|futures] [--setups a,b] [--years N]"
---

# confluence-backtest

1. Run:

   ```bash
   python3 -m scanner backtest --universe nasdaq100 --years 5
   ```

   Options: `--setups breakout,pullback`, `--target-r 3`, `--max-hold 15`, `--slippage 10`,
   `--tickers A,B`. S&P 500 over 10 years takes a few minutes on first download (then cached).

2. Report, plainly:
   - Overall and **out-of-sample** expectancy (avg R) and profit factor. OOS is what counts.
   - Setups that are positive OOS with n >= 30 (keep), negative OOS (cut or rework), and
     anything with n < 30 (not enough data, say so).
   - Whether the score buckets are monotonic (75+ better than 60-75 better than 45-60). If not,
     the weights are not adding information; suggest which component to test.
   - Regime split: are longs in Risk-off dragging results?

3. When changing rules or weights: record the baseline numbers first, make one change,
   rerun, compare OOS only, and keep the change only if OOS improves without shrinking n badly.
   Run `python3 -m unittest discover -s tests` after any code change.

## Caveats to state

Daily bars only, simple fills (stop entries within 3 bars, stop assumed first when a bar
touches both), no point-in-time news or fundamentals (catalyst and fundamentals components are
excluded from backtest scores), survivorship bias in today's index lists. Past results do not
promise future ones. No em dashes.
