import json
from pathlib import Path

from loops import forward_paper_runner


def test_forward_paper_runner_is_idempotent_for_same_signal(tmp_path: Path):
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

    first = forward_paper_runner.run_once(tmp_path, limit=1)
    second = forward_paper_runner.run_once(tmp_path, limit=1)

    assert first["processed"] == 1
    assert second["processed"] == 0
    signal_rows = (tmp_path / "forward-paper" / "paper_signals.jsonl").read_text().splitlines()
    assert len(signal_rows) == 1
