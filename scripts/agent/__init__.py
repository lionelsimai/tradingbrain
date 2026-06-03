"""TradingBrain ↔ Hermes agent adapter.

Exposes TradingBrain's safe, read-and-propose operations as Hermes-format tools
so a Nous Hermes agent can drive the system. No tool here can place an order,
touch a broker, size a position, or override the kill switch — consistent with
agents/permissions.py. The system proposes and explains; a human executes.
"""
