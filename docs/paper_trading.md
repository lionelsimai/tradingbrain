# Paper Trading

Paper is the default and only enabled trading mode.

- Every paper order flows through `execution/order_manager.OrderManager.submit`.
- The `PaperAdapter` simulates spread, slippage, partial fills, rejects (stale
  quote / cash short), stop/target brackets, and gap-through-stop.
- State lives in `paper_*` tables (`database/schema.py`).
- Run a dry-run: route a `Proposal` through `OrderManager` (see
  `tests/test_order_manager.py`).
- Operator: `python3 -m safety.operator status|kill|pause|close_all|health`.

Before any live consideration: accumulate ≥ paper_min_trades real paper fills,
clean reconciliation, and execution-quality review (see strategy_governance.md).
