# TradingBrain — operator + CI entrypoints. Default is always safe (paper/read-only).
PY ?= python3
export TB_MODE ?= paper

.PHONY: install test safety schema scorecards paper-dry-run backtest-smoke audit invariants redteam health status

install:
	$(PY) -m pip install -r requirements-dev.txt -c constraints.txt

test:
	$(PY) -m pytest -q

safety:
	$(PY) -m pytest -q tests/test_safety.py tests/test_safety_invariants.py \
	  tests/test_red_team_safety.py tests/test_no_unsafe_wrappers.py \
	  tests/test_no_hardcoded_paths.py tests/test_scorecard_sources.py

invariants:
	$(PY) -m pytest -q tests/test_safety_invariants.py

redteam:
	$(PY) -m pytest -q tests/test_red_team_safety.py

schema:
	$(PY) -m database.schema && $(PY) -m database.contracts

scorecards:
	$(PY) -m safety.risk_policy

paper-dry-run:
	$(PY) -m scripts.order_dry_run && $(PY) -m scripts.paper_trade --limit 3

backtest-smoke:
	$(PY) -m backtest.stress_test

audit:
	$(PY) -m safety.config_guard && $(PY) -m safety.risk_policy && $(PY) -m journal.event_store

health:
	$(PY) -m monitoring.health

status:
	$(PY) -m scripts.operator_status
