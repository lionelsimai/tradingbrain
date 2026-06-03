from agent.signals import sma, rsi, signal_trend


def test_sma_basic():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1], 5) is None


def test_rsi_all_gains():
    assert rsi(list(range(1, 20))) == 100.0


def test_trend_detects_uptrend():
    assert signal_trend(list(range(1, 41))) == 1
