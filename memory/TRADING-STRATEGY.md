# Trading Strategy — Hard Rules

> Source: Opus 4.7 Trading Bot Setup Guide (Nate Herk), adopted 2026-05-29.
> Every workflow reads this file first. Rules are non-negotiable.

## Hard rules

- **No options.** Stocks only, ever.
- **Max 5–6 open positions** at any time.
- **Max 20% of equity per position** (~$2,000 on a $10,000 account).
- **Max 3 new trades per week.**
- **Target 75–85% capital deployed.**
- **10% trailing stop** on every new position, placed as a **real GTC order** on Alpaca. Never mental.
- **Cut losers at –7%** from entry. Manual sell. No hoping, no averaging down.
- Tighten the trailing stop to **7% when up +15%**, to **5% when up +20%**.
- Never tighten a stop to within **3% of current price**. **Never move a stop down.**
- **Exit an entire sector** after 2 consecutive failed trades in that sector.
- Follow sector momentum. Don't force a thesis if the whole sector is rolling over.
- **Patience beats activity.** A week with zero trades can be the right answer.

## Buy-side gate (every check must pass before any buy)

1. Total positions after this fill ≤ 6.
2. Total trades placed this week (including this one) ≤ 3.
3. Position cost ≤ 20% of account equity.
4. Position cost ≤ available cash.
5. Pattern-day-trader day-trade count leaves room (<3 on a sub-$25k account).
6. A specific catalyst is documented in today's RESEARCH-LOG entry.
7. The instrument is a stock (not an option, not anything else).

## Sell-side rules (midday + opportunistic)

- Unrealized loss ≤ –7% → close immediately.
- Thesis broken (catalyst invalidated, sector rolling over, news event) → close even if not yet at –7%.
- Up ≥ +20% → tighten trailing stop to 5%.
- Up ≥ +15% → tighten trailing stop to 7%.
- Two consecutive failed trades in a sector → exit all positions in that sector.

## Entry checklist (document all before placing)

- Specific catalyst today?
- Sector in momentum?
- Stop level (7–10% below entry)?
- Target (minimum 2:1 risk/reward)?
