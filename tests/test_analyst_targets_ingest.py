from __future__ import annotations

import duckdb


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []

    def get(self, url, params, timeout):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return _FakeResponse(self.payloads[params["symbol"]])


def test_fetch_finnhub_price_targets_marks_rows_as_provider_aggregate():
    from scripts.ingest.analyst_targets import fetch_finnhub_price_targets

    session = _FakeSession({
        "MU": {
            "symbol": "MU",
            "targetHigh": 140,
            "targetLow": 90,
            "targetMean": 120,
            "targetMedian": 118,
            "lastUpdated": "2026-05-31",
        }
    })

    rows, errors = fetch_finnhub_price_targets(["MU"], key="test-key", session=session, throttle_seconds=0)

    assert errors == []
    assert len(rows) == 4
    assert {r["analyst"] for r in rows} == {"aggregate_median", "aggregate_mean", "aggregate_high", "aggregate_low"}
    assert {r["provenance_level"] for r in rows} == {"provider_aggregate"}
    assert {r["provider"] for r in rows} == {"finnhub"}
    assert all("token" in call["params"] for call in session.calls)


def test_fetch_finnhub_price_targets_missing_key_fails_closed(monkeypatch):
    from scripts.ingest.analyst_targets import fetch_finnhub_price_targets

    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    monkeypatch.delenv("FINNHUB", raising=False)
    monkeypatch.delenv("finnhub", raising=False)
    monkeypatch.delenv("finnhub_api_key", raising=False)

    rows, errors = fetch_finnhub_price_targets(["MU"], key=None, throttle_seconds=0)

    assert rows == []
    assert errors == [{"ticker": None, "error": "FINNHUB_API_KEY not set"}]


def test_merge_targets_is_idempotent_and_repairs_incomplete_schema(tmp_path):
    from scripts.ingest.analyst_targets import merge_targets

    db = tmp_path / "knowledge.duckdb"
    con = duckdb.connect(str(db))
    con.execute("CREATE TABLE analyst_targets(ticker VARCHAR, broker VARCHAR, target DOUBLE)")
    con.close()

    row = {
        "target_id": "row-1",
        "ticker": "MU",
        "broker": "Finnhub consensus aggregate",
        "analyst": "aggregate_median",
        "rating": "consensus",
        "action": "provider aggregate median target",
        "target": 118.0,
        "date": "2026-05-31",
        "source_url": "https://finnhub.io/api/v1/stock/price-target?symbol=MU",
        "notes": "Provider aggregate price-target metric; not broker/analyst-level provenance.",
        "provider": "finnhub",
        "provenance_level": "provider_aggregate",
        "source_json": "{}",
        "ingested_at": "2026-06-01T00:00:00+00:00",
    }

    first = merge_targets([row], db_path=db, write_raw=False)
    second = merge_targets([{**row, "target": 119.0}], db_path=db, write_raw=False)

    assert first["added"] == 1
    assert second["updated"] == 1
    con = duckdb.connect(str(db))
    try:
        rows = con.execute(
            "SELECT target, provider, provenance_level FROM analyst_targets WHERE target_id = 'row-1'"
        ).fetchall()
    finally:
        con.close()
    assert rows == [(119.0, "finnhub", "provider_aggregate")]
    assert second["db_total"] == 1
    assert second["provider_aggregate_total"] == 1


def test_hermes_ingest_tool_uses_new_module_without_network(monkeypatch):
    from scripts.agent import hermes_tools
    from scripts.ingest import analyst_targets

    monkeypatch.setattr(
        analyst_targets,
        "fetch_finnhub_price_targets",
        lambda tickers: ([{
            "target_id": "row-1",
            "ticker": "MU",
            "broker": "Finnhub consensus aggregate",
            "analyst": "aggregate_median",
            "rating": "consensus",
            "action": "provider aggregate median target",
            "target": 118.0,
            "date": "2026-05-31",
            "source_url": "https://finnhub.io/api/v1/stock/price-target?symbol=MU",
            "notes": "",
            "provider": "finnhub",
            "provenance_level": "provider_aggregate",
            "source_json": "{}",
            "ingested_at": "2026-06-01T00:00:00+00:00",
        }], []),
    )
    monkeypatch.setattr(analyst_targets, "merge_targets", lambda rows: {"added": len(rows), "total": len(rows), "db_total": len(rows)})

    out = hermes_tools.ingest_analyst_target_provenance(["MU"])

    assert out["available"] is True
    assert out["valid_rows"] == 1
    assert "aggregate" in out["caution"].lower()
