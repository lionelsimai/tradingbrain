"""Rule-based signals that watch the market."""


def sma(values, n):
    return sum(values[-n:]) / n if len(values) >= n else None


def rsi(values, n: int = 14):
    if len(values) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(-n, 0):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    if losses == 0:
        return 100.0
    rs = (gains / n) / (losses / n)
    return round(100 - 100 / (1 + rs), 1)


def signal_trend(history):
    """+1 when the short average is above the long average (uptrend), else -1."""
    fast, slow = sma(history, 10), sma(history, 30)
    if fast is None or slow is None:
        return 0
    return 1 if fast > slow else -1


def signal_momentum(history):
    """RSI: oversold (<35) leans buy, overbought (>65) leans sell."""
    r = rsi(history)
    if r is None:
        return 0
    if r < 35:
        return 1
    if r > 65:
        return -1
    return 0
