---
name: confluence-journal
description: >-
  Keeps Neel's trading consistent: grades the scanner's auto-logged A/B signals
  against what price actually did (forward-test track record), logs the trades he
  takes and closes, and reviews results by grade, setup and plan discipline. Use
  when the user says "log a trade", "I bought X at", "I closed X", "how are the
  signals doing", "weekly review", "journal", "am I following my plan", or
  "trading stats".
argument-hint: "review | stats | add | close"
---

# confluence-journal

## Log a trade he took

```bash
python3 -m scanner journal add --symbol NVDA --side long --entry 191.2 --stop 185.3 --target 203 \
  --size 21 --setup pullback --grade B --score 64 --notes "aligned ORB at 9:50"
python3 -m scanner journal close --id 3 --exit 199.8 --followed yes --notes "trimmed at 2R"
```

Pull setup/grade/score from `out/scan.json` when he names a ticker from today's scan. Ask only
for what is missing (entry, stop, size). `--followed` is whether he stuck to the plan.

## Review

```bash
python3 -m scanner journal review   # grades pending/open signals with the backtest rules
python3 -m scanner journal stats    # signals by grade/setup + his trades
```

Report: signal track record (n, win %, avg R) for A vs B and by setup; his trades' avg R vs the
signals'; avg R when he followed the plan vs when he did not. Point out the one habit that would
help most, backed by the numbers. Small samples (n < 20) are noise: say so. No em dashes.
