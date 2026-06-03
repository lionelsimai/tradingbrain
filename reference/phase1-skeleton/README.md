# Paper-Trading Agent (Phase 1)

A safe, extendable skeleton for a stock trading agent. It risks **no real money**
and runs anywhere with Python 3.10+ — your laptop, a server, or directly on your
Zo Computer (which gives you a full Linux filesystem).

## What's inside (the five pieces you asked for)

| Piece | File | What it does |
|-------|------|--------------|
| Signals | `agent/signals.py` | Rules that watch the market |
| Patterns / brain | `agent/brain.py` | Turns signals into a confidence + action |
| Verifiability | `agent/backtest.py` | Tests the logic on history |
| Observability | `agent/observability.py` | Logs every decision and *why* |
| Broker + risk | `agent/broker.py` | Paper trades, stop-loss, kill switch |

`config.py` holds your guardrails. `run.py` ties it all together.

## Run it

```bash
python run.py
```

Prints a scorecard and writes `decision_log.csv` — every BUY/SELL/HOLD with its reason.

## Optional: tests

```bash
pip install pytest
pytest
```

## The four hooks (this is where you build upon it)

1. **Real data** — `agent/data.py`. Swap `simulate_prices()` for a real source like `yfinance`.
2. **Real ML** — `agent/brain.py` → `ml_score()`. Train a model, return its probability.
3. **LLM advisor** — `agent/brain.py` → `llm_reasoning()`. Wire in the Anthropic API
   (key via `.env`). It explains decisions; it never places trades.
4. **Real broker** — `agent/broker.py`. Use a broker's **paper** account first.

## Build order (safe first)

1. Paper sandbox + logging ✅ (this)
2. Real signals & patterns
3. Backtest on real history
4. Add the LLM advisor
5. Go live **last** — hard risk limits + kill switch, real money only after months of clean paper results.

## On Zo Computer

Upload this folder (or `git clone` it), then run `python run.py`. Later, Zo can host the
live dashboard and keep the agent running as an always-on process. Because a Zo is always
on and can connect to your email and other tools, keep all keys in `.env` (never in code),
and stay on paper trading until you trust the results.

## A note worth keeping

In the demo run, the bot made about 5% while simply buying and holding made about 47%.
Beating the market is hard. The backtest exists so you discover that on fake money, not
real money. Keep verifying.
