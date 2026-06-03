# data package — market-data validation + calendar.
# NOTE: kept intentionally EMPTY (no submodule imports) so that
# `from data import quote_validator` / `market_calendar` work WITHOUT pulling in
# pandas (used only by data.data_contract). Reconstructed from the test contracts
# (tests/test_quote_validator.py, test_market_calendar.py, test_data_contract.py)
# and caller usage (execution/order_manager.py, safety/risk_gate.py).
