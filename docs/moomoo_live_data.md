# moomoo OpenAPI Live Data Setup

This integration is for real-time US equity market data only. It does not enable
live trading.

## Safety Flags

Keep these in `.env`:

```bash
TB_MODE=paper
TB_ALLOW_LIVE=0
MOOMOO_OPEND_HOST=127.0.0.1
MOOMOO_OPEND_PORT=11111
```

## OpenD

1. Install and start moomoo OpenD.
2. Log in to the moomoo account that has US market data access.
3. Confirm OpenD is listening on `127.0.0.1:11111`.

## One-Shot Snapshot

```bash
cd "/Users/lionel/Documents/New project/TradingBrain"
set -a
source .env
set +a

./.venv-tb/bin/python -m scripts.ingest.moomoo --tickers NVDA,MU,AMD
```

Outputs:

- `data/intraday_snap.parquet`
- `reports/moomoo-live-quotes.json`
- `reports/live-data-health.json`

## Health Check

```bash
./.venv-tb/bin/python -m monitoring.live_data_health --write-report
```

This fails closed when OpenD is offline, the moomoo package is missing, the
snapshot is stale, or live execution flags are enabled.

## Live-Like Forward Paper

After the snapshot and health check pass, collect paper observations with fresh
moomoo decision quotes:

```bash
./.venv-tb/bin/python -m loops.forward_paper_runner --once --require-live-data
./.venv-tb/bin/python -m loops.forward_paper_runner --scorecard
```

The paper scorecard reports `live_like_resolved_trades` separately from total
paper rows. Go-live gate 5 uses the live-like count when it is available.

## Full Universe

```bash
./.venv-tb/bin/python -m scripts.ingest.moomoo --full-universe
```

If the command says OpenD is unreachable, start OpenD first. If the command says
subscription or market-data rights are missing, enable the relevant US equity
quote permissions in moomoo.
