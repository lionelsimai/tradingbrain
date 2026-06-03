"""Market data.  [HOOK 1] swap simulate_prices() for real stock data."""
import random

random.seed(42)  # reproducible runs


def simulate_prices(days: int = 200, start: float = 100.0):
    """A fake but realistic-looking daily price series (random walk + drift)."""
    prices = [start]
    for _ in range(days - 1):
        drift, shock = 0.0004, random.gauss(0, 0.015)
        prices.append(round(prices[-1] * (1 + drift + shock), 2))
    return prices


# [HOOK 1] To use real data, install yfinance and replace simulate_prices():
# import yfinance as yf
# def real_prices(ticker="AAPL", period="1y"):
#     return yf.download(ticker, period=period)["Close"].tolist()
