# TradingBrain — paper-only 24/7 host image.
# Builds the real system (now portable) and runs it in PAPER mode.
# It never enables live trading and never pushes code anywhere.
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Core deps (mirrors the README quick-start; unpinned for build portability).
RUN pip install --no-cache-dir \
    duckdb pandas numpy pyarrow pyyaml yfinance hmmlearn scikit-learn requests

COPY . /app

# Portability + safety defaults. Live stays fail-closed.
ENV TRADINGBRAIN_ROOT=/app \
    HERMES_TRADING_MODE=paper \
    TB_ALLOW_LIVE=0 \
    TICK_SECONDS=3600 \
    REVIEW_EVERY_TICKS=24

CMD ["python3", "ops/serve.py"]
