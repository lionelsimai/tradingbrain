# Validation & Go-Live — what was added

This implements the capstone of the Master Build & Validation spec: a single,
honest authority that decides whether TradingBrain is allowed to risk real money.
It does NOT rebuild the engine (that already existed) — it adds the two missing
pieces that tie everything together.

## 1. The go-live authority (Section 14)
One command reads every validation artifact and renders one verdict:
```
python3 -m lab.go_live
```
It checks seven gates and **defaults to BLOCKED** — it stays blocked until every
one is green, and it tells you exactly what's failing. Right now it says:

- ✅ Walk-forward out-of-sample — passes (beats the market in all test windows)
- 🟡 Monte Carlo drawdown — survivable, but on practice data only (see below)
- 🟡 Stress scenarios — needs your eyes (it loses in crashes, as trend systems do)
- ✅ Overfitting proofs — passes (no look-ahead, live matches backtest, repeatable)
- ❌ Paper matches live — **the main blocker: zero real trades have happened yet**
- ✅ Risk controls, kill switch, data health — all present and valid
- ❌ Human approval — not yet given

Verdict: **BLOCKED**, which is correct. The full report is written to
`reports/go-live.md`.

## 2. Monte Carlo drawdown engine (Section 5.2 — "the million runs, done right")
```
python3 -m backtest.monte_carlo --paths 20000
```
Instead of hunting for lucky settings, this holds the strategy fixed and
reshuffles the real trade history thousands of times to learn the *range* of
outcomes — especially how bad the worst drawdowns get. On practice data it shows
a median drawdown around 6% and a 99th-percentile around 11%, inside the 20%
ceiling. It never invents a trade; it only reshuffles ones that were recorded,
and it labels everything as practice/indicative.

## The honest bottom line (unchanged)
Two gates can't be satisfied yet because the system has **made zero real trades**.
No amount of backtesting clears them. The one thing that does is running it in
paper mode to build a real track record — which is exactly what the hosting setup
is for. The authority will flip those gates to green on real evidence, not before.

## To approve (only after a real paper record exists)
Edit `config/go_live_signoff.yaml` and set `approved: true` with your name and the
date — after you've reviewed `reports/go-live.md` and everything it cites.
