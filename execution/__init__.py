"""Execution layer — the single, audited path from approved intent to broker.

Only execution.order_manager.OrderManager.submit() may place orders, and it does
so ONLY through a BrokerAdapter that accepts an OrderIntent (never raw fields).
"""
