---
name: tradingbrain-validate
description: >
  Validate the TradingBrain system and present its final state in one command.
  Use whenever someone wants to (a) check that TradingBrain's validation
  machinery and safety invariants still hold after a change, or (b) get a single
  honest summary of whether the strategy is cleared to trade. Runs the test
  suite, the safety-invariant checks, the Monte Carlo risk-of-ruin, and the
  institutional gauntlet, then writes FINAL-REPORT.md.
---

# TradingBrain — Validate & Present

## What this skill does
One command runs every validation layer and writes a single honest report:

```
python3 -m scripts.validate_all              # full (includes the test suite, ~50s)
python3 -m scripts.validate_all --skip-tests # faster (~12s)
```

Output:
- A console summary: each check ✅/❌, the gauntlet verdict, the go-live verdict.
- `FINAL-REPORT.md`: presents the product, the verdict, what's verified vs not,
  and the honest limitations.

## What it checks (and what "pass" means)
It confirms the validation MACHINERY works and the SAFETY INVARIANTS hold:
- go-live computes a verdict and live trading is fail-closed (blocked unless cleared),
- the recommendation engine never shows a "strong" pick while conviction is capped,
- the app export bridge matches the schema (no null price levels),
- memory recall never misreports the track record (independent recompute),
- the data-quality gate and the no-look-ahead proofs pass,
- Monte Carlo and the gauntlet run and produce verdicts.

**Important:** "all checks pass" means the safety/honesty scaffolding is healthy.
It does **not** mean the strategy is approved to trade. That verdict is reported
separately and is currently REJECTED / BLOCKED by design — the blocker is the
absence of a real forward paper record and a survivorship-free universe, not a bug.

## When to run it
- After any change to the engine, gates, memory, or data.
- Before trusting any recommendation or considering (eventually) real capital.
- As the standing definition of "is the system still honest and safe?"

## How to read the result
- **Infrastructure HEALTHY + verdict BLOCKED** → expected and correct today.
- **Infrastructure PROBLEMS** → a safety invariant broke; fix before anything else.
- **Verdict moves toward CLEARED** → only happens once real paper trades accumulate
  and the gates legitimately turn green. Do not force it.
