---
name: confluence-ticker
description: >-
  Full confluence read on one symbol (stock, ETF or micro future like MES=F):
  daily setups and grade with the six-component breakdown, key levels, trend
  checks, regime and sector alignment, earnings date, verified headlines and
  8-Ks, SEC fundamentals, and today's intraday levels and triggers. Use when the
  user says "check NVDA", "what do you think of TSLA here", "is AAPL a setup",
  "levels on MES", "should I look at X", or names a ticker for analysis.
argument-hint: "SYMBOL"
---

# confluence-ticker

1. Run `python3 -m scanner ticker SYMBOL --json > out/ticker.json` (futures use Yahoo symbols:
   MES=F, MNQ=F, M2K=F, MYM=F, MGC=F, MCL=F).
2. Open the top 2-3 headlines or 8-Ks and confirm what they say.
3. Answer in this shape:
   - **Verdict line:** best setup and grade, or "no setup today" plus the nearest level that
     would create one (e.g. a close above the 20-day high).
   - **Plan** (if any): entry, stop, 2R/3R, size, flags.
   - **Why:** regime/sector, trend checks, setup reasons, catalyst (verified), fundamentals.
   - **Levels:** prior high/low, 20-day and 52-week extremes, 20 EMA / 50 / 200 SMA, and
     intraday PDH/PDL/PMH/PML/VWAP if the market is open.
   - **Risk:** earnings date, opposing signals.
4. Never predict the move; describe the setup and what would invalidate it. No em dashes.
