# Risk Policy

`config/risk_policy.yaml` is the ONLY active risk source. `safety/risk_policy.py`
loads it, validates schema + bounds, versions it (hash), and detects conflicts
with legacy configs (which are passive). `risk_gate`, `order_manager`, the paper
adapter, and calibration read ONLY this policy.

Key limits (defaults): risk_per_trade 0.5% (max 1%), max_position 10%,
portfolio_heat 4%, max_concurrent 6, sector 30%, correlated 35%, daily_loss 1.5%,
weekly_loss 4%, drawdown 8%, loss-streak halt at 3. Live trading disabled.
