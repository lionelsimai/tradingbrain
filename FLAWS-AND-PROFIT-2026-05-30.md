# TradingBrain — Flaws, Vulnerabilities & How It Can Actually Make Money

*An honest, evidence-based teardown. Every number here came from running the
system's own engines over its own 30-year data this session. Where I assert a
weakness, I show the test that proves it.*

---

## Bottom line up front

After the consistency fixes, the engines now agree and the loop is sound. But
**consistency is not profit.** When I ran the *portfolio-level* backtest (real
next-day-open fills, risk rails, position caps) the verdict is blunt:

> **TradingBrain is a defensive, drawdown-control trend-follower — not an alpha
> machine. It loses to simple buy-and-hold in bull markets and earns its keep
> only in bears/crises. Its one robust, repeatable edge is the regime filter
> ("don't be long when SPY < 200-day"). Almost everything else is noise around
> beta.**

If you trade it expecting to beat holding QQQ on these names, the evidence says
you will underperform. If you trade it to *survive* drawdowns and stay solvent
through a crash, it works.

---

## The evidence (portfolio backtest, top-5 momentum, monthly rebalance)

| Period | Strategy | SPY | Alpha | MaxDD | Sharpe |
|---|---|---|---|---|---|
| Dot-com 2000–02 | **−11%** | −37% | **+26%** | 18% | −0.42 |
| Recovery 2003–07 | +81% | +75% | +6% | 15% | 1.08 |
| GFC 2008–09 | **+23%** | −19% | **+42%** | 7% | 1.34 |
| 2010s 2010–19 | +93% | **+247%** | **−154%** | 14% | 0.65 |
| 2022 bear | −12% | −19% | +7% | 12% | −1.60 |
| AI bull 2023–25 | +16% | **+86%** | **−71%** | 20% | 0.46 |
| Full 1999–2026 | +404% | **+889%** | **−486%** | 21% | 0.62 |

**Read it carefully:**
- **Bull markets → it badly trails buy-and-hold.** 2010s: +93% vs +247%. AI
  bull: +16% vs +86%. Full history: it captured less than half of SPY. Trading
  in and out, getting stopped, and sitting in cash during pullbacks leaves
  enormous money on the table in a trending market.
- **Bears/crises → it protects capital.** Dot-com +26% alpha, GFC +42% alpha,
  2022 +7% alpha. That is the entire value proposition.
- **The regime filter is the edge.** With it OFF, GFC goes −24.5% and 2022 goes
  −21% (and it halts). With it ON, drawdowns stay ~20% and crises become
  positive-alpha. The "flat when SPY < 200-day" rule is doing the real work; the
  six-setup zoo is decoration.

---

## Flaws & vulnerabilities found this session

### 1. Survivorship bias inflates every headline stat (structural)
The universe is **77 names that exist and matter *today*** — the AI winners.
`config/session.yaml` admits `survivorship_bias_free: false`. The ~62% win rate
and +0.12R/trade are optimistic: the names that went to zero (2000-era roadkill)
aren't in the data. *Mitigant:* the system uses stops, so a loser is cut at ~−1R
regardless — far less survivorship-sensitive than buy-and-hold. *But* the
portfolio test **already loses to buy-and-hold even with the bias in its favor**,
so de-biasing only widens the gap.

### 2. The per-trade "edge" doesn't survive contact with a portfolio
Per-trade R-stats look fine (+0.12R up-tape, +0.09R down-tape, positive in most
years). But those 47,000 "trades" are **massively overlapping** across 77
correlated names sampled every 3 bars — the effective independent sample is a
tiny fraction. The honest portfolio curve (above) is the truth; the per-trade
significance is overstated.

### 3. Concentration: "6 positions" ≈ 2.3 independent bets
Average pairwise daily-return correlation across the universe is **0.32** (2023+).
Six "diversified" AI longs behave like ~2.3 independent bets — and in a crash
correlations converge toward 1.0, which is exactly why MaxDD sits at ~20% even
with five names. You are making one leveraged AI-beta bet wearing a diversified
costume.

### 4. The portfolio engine silently ignored 4 of 8 configured risk rules
`config/sources.yaml` defines `max_sector_pct`, `min_confidence`,
`cash_only_if_regime_off`, `no_new_positions_if_vix_above`. `backtest/engine.py`
referenced **only** `max_position_pct`, `stop_loss_pct`, `take_profit_pct`,
`max_drawdown_halt_pct`. The operator believed a sector cap was on. It was not.
→ **Fixed this pass** (sector cap now enforced; see below).

### 5. Calibration could size *up* into weakness
The learned `regime_multiplier` had `BREAKOUT bear = 1.44` — i.e. lean harder
into breakouts during a bear market. That is a survivorship artifact (the few
breakouts that worked in weakness), and dangerous live. → **Fixed** (clamped to
≤1.0 in any risk-off regime).

### 6. Benchmark is SPY, but the right yardstick is QQQ / the basket
Comparing an AI-momentum strategy to SPY flatters it. Against QQQ or an
equal-weight basket of the very names it trades, the underperformance in
bull regimes (Flaw #2) is even starker. The honest opportunity cost is "what if
I just held these names?" — and the answer is "you'd have more money."

### 7. A 5th, unrelated simulator still lives in `engine.py`
The portfolio engine uses Clenow momentum + fixed 10%/25% stops — *not* the
unified `trade_sim` plan the rest of the system now shares. It's a different
strategy than the live desk emits. Fine as a regime/överlay study, but know that
the portfolio curve above tests *momentum + regime*, not the six desk setups.

### 8. Live-data fragility (operational)
Live signals depend on yfinance + an intraday snapshot parquet. No sanity guard
against a stale/bad print feeding a bogus signal. A single bad tick → a real
order. Worth a price-sanity gate before any live deployment.

---

## How it can actually make money — the honest plan

**Stop asking it to beat the market. Ask it to do the two things it provably
does well, and convert the one real signal into regime-independent alpha.**

### A. Use it as a drawdown-control sleeve (works today)
Capture ~50–70% of the upside with ~25% of the drawdown. If you cannot
psychologically hold an 80% NVDA drawdown, a system that caps DD near 20% and
still compounds has genuine value — measured in *Sharpe and solvency*, not raw
return. Size it as a satellite, with the **200-day regime gate as the master
switch**. Expected: ~5–7% CAGR, Sharpe ~0.6 on this universe.

### B. Deploy it when buy-and-hold is *worst* (timing the relative value)
The system's relative value is highest in bear/sideways tapes (dot-com, GFC,
2022). The play: hold beta in clean uptrends; **switch to the system when the
regime breaks** (SPY loses the 200-day, breadth deteriorates). You're using it
as crash insurance you can actually trade, not as an everyday alpha source.

### C. Market-neutral long-short — I tested it; it does NOT work *in this universe*
My first instinct was that the relative-strength signal should be expressed
**market-neutral** (long strongest-RS AI names, short weakest), to strip out the
AI-beta and isolate cross-sectional momentum. It's the textbook move. **So I
backtested it** (long top-8 / short bottom-8, dollar-neutral, monthly, costs in):

| Period | Long/Short return | Sharpe | MaxDD |
|---|---|---|---|
| Dot-com 2000–02 | −6% | 0.19 | 59% |
| GFC 2008–09 | **−44%** | −0.76 | 55% |
| 2022 bear | −9% | 0.02 | 38% |
| AI bull 2023–25 | +9% | 0.30 | 50% |
| Full 2002–26 | +100% | **0.28** | **79%** |

**It fails.** A 79% drawdown and a −44% GFC are disqualifying. The reason is
Flaw #3: this universe is **one hyper-correlated sector**. There isn't enough
*dispersion* between the strongest and weakest AI names to harvest — shorting
"the weakest AI stock" still gets run over in squeezes, and in a crisis the
weakest don't reliably fall the most. Cross-sectional momentum is real, but only
across a **broad, cross-sector, survivorship-free** universe (hundreds of names,
many industries). Inside a 77-name AI basket, market-neutral is a trap.

**Implication:** there is no clean intra-sector alpha to extract here. That
*reinforces* the real conclusion — the only robust, repeatable edge in this
system is the **regime/drawdown overlay (A + B)**, not stock selection. If you
want genuine market-neutral alpha, the prerequisite is a much broader universe;
this infra would need a different, survivorship-free dataset first.

### D. Refinements that raise realistic edge (in priority order)
1. **Simplify the setup zoo.** Momentum + the regime gate is ~90% of the value.
   Fewer, more robust signals = less overfitting, lower costs.
2. **Cap total AI-beta exposure**, not just per-name. Sector cap (now enforced)
   is a start; add a basket-beta cap so you can't end up 100% one factor.
3. **Benchmark against QQQ / equal-weight basket** so opportunity cost is always
   in your face.
4. **Trade only the most liquid names** (NVDA, MSFT, AMZN, AVGO, …) for
   capacity and slippage; drop the thin tickers.
5. **Add a price-sanity gate** on live data before any order.
6. **A broader, survivorship-free universe** is the only way to trust the
   momentum numbers — and to find the dispersion a long-short book needs.

### What NOT to do
- Don't add more setups hoping to find edge — the portfolio test shows the
  setups aren't the edge.
- Don't run it un-hedged and expect to beat QQQ. You won't.
- Don't trust the +0.12R/trade or the 6–35x research multiples as profit
  forecasts. They're hypothesis-test outputs on biased, overlapping data.

---

## Fixes applied this pass (tested)

| File | Change |
|---|---|
| `scripts/calibration.py` | `regime_multiplier` clamped to ≤1.0 in any risk-off regime — never size up into weakness. |
| `backtest/engine.py` | Loads the universe category map and **enforces `max_sector_pct`** on new entries (was silently ignored). |

Both verified: `BREAKOUT bear` multiplier now 1.0 (was 1.44); engine runs with
the sector cap active; `analyze`, calibration, and all 11 tests still pass.

---

*Honest summary: the machine is well-built and now internally consistent, but
its current shape is a defensive beta vehicle that trails buy-and-hold in the
regimes that dominate history. Its one robust, repeatable edge is the regime /
drawdown overlay — so the realistic money is in (A) drawdown control and (B)
trading it as crash insurance, sized as a satellite with the 200-day gate as the
master switch. I tested the obvious alpha upgrade (market-neutral long-short) and
it failed inside this hyper-correlated basket; genuine stock-selection alpha
would require a broad, cross-sector, survivorship-free universe this system does
not yet have. Don't expect it to beat QQQ on these names — use it to survive the
tape that QQQ can't.*
