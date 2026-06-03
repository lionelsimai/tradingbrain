import json
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd
from loops import forward_paper_runner


def test_forward_paper_scorecard_is_paper_only(tmp_path: Path):
    card = forward_paper_runner.scorecard(tmp_path)

    assert card["evidence_source"] == "paper"
    assert card["resolved"] == 0
    assert "Replay/backtest" in card["methodology_caveat"]
    assert (tmp_path / "scorecard-paper.json").exists()


def test_forward_paper_once_records_signal_order_fill(tmp_path: Path):
    (tmp_path / "desk-signals.json").write_text(json.dumps({
        "regime": "bull",
        "buys": [{
            "ticker": "NVDA",
            "setup": "TREND_LEADER",
            "entry": 100.0,
            "stop": 95.0,
            "target": 112.0,
            "confidence": 0.7,
        }],
    }))

    out = forward_paper_runner.run_once(tmp_path, limit=1)
    card = out["scorecard"]

    assert out["processed"] == 1
    assert card["total_signals"] == 1
    assert card["accepted_signals"] + card["rejected_signals"] == 1
    signals = (tmp_path / "forward-paper" / "paper_signals.jsonl").read_text()
    assert '"signal_source": "desk-signals.json"' in signals
    assert '"source": "synthetic_paper_quote"' in signals


def test_forward_paper_once_uses_fresh_moomoo_quote(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("data.market_calendar.session", lambda now=None: "regular")
    snap = tmp_path / "intraday_snap.parquet"
    pd.DataFrame([{
        "ticker": "NVDA",
        "last_price": 100.01,
        "bid": 100.0,
        "ask": 100.02,
        "fetched_at_utc": datetime.now(timezone.utc),
        "ts_utc": datetime.now(timezone.utc),
        "source": "moomoo:market_snapshot",
        "sec_status": "NORMAL",
    }]).to_parquet(snap, index=False)
    monkeypatch.setattr(forward_paper_runner, "INTRADAY_SNAPSHOT", snap)
    (tmp_path / "desk-signals.json").write_text(json.dumps({
        "regime": "bull",
        "buys": [{
            "ticker": "NVDA",
            "setup": "TREND_LEADER",
            "entry": 100.0,
            "stop": 95.0,
            "target": 112.0,
            "confidence": 0.7,
        }],
    }))

    out = forward_paper_runner.run_once(tmp_path, limit=1, require_live_data=True)
    card = out["scorecard"]
    signal = json.loads((tmp_path / "forward-paper" / "paper_signals.jsonl").read_text().splitlines()[0])

    assert out["processed"] == 1
    assert signal["data_freshness"]["source"] == "moomoo:market_snapshot"
    assert signal["data_freshness"]["live_like_quote"] is True
    assert signal["quote_at_decision"]["bid"] == 100.0
    assert card["quote_source_breakdown"]["moomoo:market_snapshot"] == 1
    assert card["live_like_signal_count"] == 1
    assert card["synthetic_quote_signal_count"] == 0


def test_forward_paper_require_live_data_rejects_without_moomoo_quote(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(forward_paper_runner, "INTRADAY_SNAPSHOT", tmp_path / "missing.parquet")
    (tmp_path / "desk-signals.json").write_text(json.dumps({
        "regime": "bull",
        "buys": [{
            "ticker": "NVDA",
            "setup": "TREND_LEADER",
            "entry": 100.0,
            "stop": 95.0,
            "target": 112.0,
            "confidence": 0.7,
        }],
    }))

    out = forward_paper_runner.run_once(tmp_path, limit=1, require_live_data=True)
    signal = json.loads((tmp_path / "forward-paper" / "paper_signals.jsonl").read_text().splitlines()[0])

    assert out["processed"] == 1
    assert signal["status"] == "rejected"
    assert "data:" in signal["rejection_reason"]
    assert out["scorecard"]["accepted_signals"] == 0


def test_forward_paper_premarket_writes_gate_status(tmp_path: Path):
    out = forward_paper_runner.premarket(tmp_path)

    assert out["stage"] == "premarket"
    assert "paper_safe_to_trade" in out
    assert (tmp_path / "forward-paper-premarket.json").exists()


def test_forward_paper_scorecard_counts_live_like_resolved(tmp_path: Path):
    fwd = tmp_path / "forward-paper"
    fwd.mkdir()
    (fwd / "paper_signals.jsonl").write_text(json.dumps({
        "signal_id": "sig_live",
        "ticker": "NVDA",
        "strategy": "TREND_LEADER",
        "regime": "bull",
        "status": "accepted",
        "data_freshness": {"source": "moomoo:market_snapshot", "live_like_quote": True},
    }) + "\n" + json.dumps({
        "signal_id": "sig_synth",
        "ticker": "MU",
        "strategy": "TREND_LEADER",
        "regime": "bull",
        "status": "accepted",
        "data_freshness": {"source": "synthetic_paper_quote", "synthetic": True, "live_like_quote": False},
    }) + "\n")
    (fwd / "paper_exits.jsonl").write_text(json.dumps({
        "signal_id": "sig_live",
        "r_multiple": 1.0,
    }) + "\n" + json.dumps({
        "signal_id": "sig_synth",
        "r_multiple": 1.0,
    }) + "\n")

    card = forward_paper_runner.scorecard(tmp_path)

    assert card["resolved"] == 2
    assert card["live_like_resolved_trades"] == 1
    assert card["synthetic_quote_signal_count"] == 1


def test_forward_paper_scorecard_scores_strategy_regime_confidence_and_slippage(tmp_path: Path):
    fwd = tmp_path / "forward-paper"
    fwd.mkdir()
    (fwd / "paper_signals.jsonl").write_text(
        json.dumps({
            "signal_id": "sig_1",
            "ticker": "NVDA",
            "strategy": "TREND_LEADER",
            "regime": "bull",
            "status": "accepted",
            "confidence": 0.65,
            "data_freshness": {"source": "moomoo:market_snapshot", "live_like_quote": True},
        }) + "\n" + json.dumps({
            "signal_id": "sig_2",
            "ticker": "NVDA",
            "strategy": "TREND_LEADER",
            "regime": "bull",
            "status": "accepted",
            "confidence": 0.75,
            "data_freshness": {"source": "moomoo:market_snapshot", "live_like_quote": True},
        }) + "\n" + json.dumps({
            "signal_id": "sig_3",
            "ticker": "MU",
            "strategy": "MEAN_REVERSION",
            "regime": "bear",
            "status": "rejected",
            "confidence": 0.55,
            "data_freshness": {"source": "synthetic_paper_quote", "synthetic": True},
        }) + "\n"
    )
    (fwd / "paper_orders.jsonl").write_text(
        json.dumps({"signal_id": "sig_1", "status": "filled"}) + "\n"
        + json.dumps({"signal_id": "sig_2", "status": "filled"}) + "\n"
        + json.dumps({"signal_id": "sig_missing_fill", "status": "accepted"}) + "\n"
    )
    (fwd / "paper_fills.jsonl").write_text(
        json.dumps({"signal_id": "sig_1", "slippage_bps": 5.0, "partial_fill_status": "full"}) + "\n"
        + json.dumps({"signal_id": "sig_2", "slippage_bps": 60.0, "partial_fill_status": "partial"}) + "\n"
    )
    (fwd / "paper_exits.jsonl").write_text(
        json.dumps({"signal_id": "sig_1", "ticker": "NVDA", "strategy": "TREND_LEADER", "r_multiple": 1.5}) + "\n"
        + json.dumps({"signal_id": "sig_2", "ticker": "NVDA", "strategy": "TREND_LEADER", "r_multiple": -1.0}) + "\n"
    )

    card = forward_paper_runner.scorecard(tmp_path)

    strat = card["performance_by_strategy"]["TREND_LEADER"]
    assert strat["resolved"] == 2
    assert strat["win_rate"] == 50.0
    assert strat["expectancy_R"] == 0.25
    assert card["performance_by_regime"]["bull"]["resolved"] == 2
    assert card["performance_by_ticker"]["NVDA"]["average_R"] == 0.25
    assert card["confidence_band_breakdown"]["0.60-0.69"]["expectancy_R"] == 1.5
    assert card["confidence_band_breakdown"]["0.70-0.79"]["expectancy_R"] == -1.0
    assert card["confidence_band_breakdown"]["<0.60"]["rejected"] == 1
    assert card["slippage_summary"]["p95_bps"] == 60.0
    assert card["slippage_summary"]["over_50bps"] == 1
    assert card["fill_quality"]["fill_rate_pct"] == 66.67
    assert card["fill_quality"]["partial_fill_rate_pct"] == 50.0
