from loops import harden_live_readiness, improvement_backlog


def _stress():
    return {
        "verdict": "LIVE_BLOCKED",
        "final_decision": "RESEARCH_ONLY",
        "blockers": [
            {
                "id": "paper_evidence_thin",
                "severity": "critical",
                "required_action": "Collect at least 50 resolved forward paper trades.",
            },
            {
                "id": "live_data_health_failed",
                "severity": "high",
                "required_action": "Start OpenD and refresh quotes.",
            },
            {
                "id": "stress:commands:validate_all",
                "severity": "high",
                "required_action": "command exits 0",
            },
        ],
    }


def test_improvement_backlog_classifies_manual_vs_auto_items():
    report = improvement_backlog.build(_stress())
    by_id = {item["source_blocker_id"]: item for item in report["items"]}

    assert by_id["paper_evidence_thin"]["automatic_patch_allowed"] is False
    assert by_id["paper_evidence_thin"]["patch_class"] == "evidence_collection"
    assert by_id["paper_evidence_thin"]["title"] == "Collect real forward paper evidence"
    assert by_id["live_data_health_failed"]["automatic_patch_allowed"] is False
    assert by_id["live_data_health_failed"]["title"] == "Restore moomoo real-time market-data health"
    assert by_id["stress:commands:validate_all"]["automatic_patch_allowed"] is True
    assert by_id["stress:commands:validate_all"]["patch_class"] == "bug_fix"
    assert "Build -> Review -> Test -> Fix" in report["process_principle"]
    assert "enable live trading" in report["forbidden_actions"]


def test_improvement_backlog_writes_json_and_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(improvement_backlog, "JSON_OUT", tmp_path / "improvement-backlog.json")
    monkeypatch.setattr(improvement_backlog, "MD_OUT", tmp_path / "improvement-backlog.md")

    report = improvement_backlog.write(improvement_backlog.build(_stress()))

    assert report["item_count"] == 3
    assert (tmp_path / "improvement-backlog.json").exists()
    assert "Improvement Backlog" in (tmp_path / "improvement-backlog.md").read_text()


def test_hardening_loop_embeds_backlog(tmp_path, monkeypatch):
    monkeypatch.setattr(harden_live_readiness, "OUT", tmp_path / "hardening-live-readiness.json")
    monkeypatch.setattr(improvement_backlog, "JSON_OUT", tmp_path / "improvement-backlog.json")
    monkeypatch.setattr(improvement_backlog, "MD_OUT", tmp_path / "improvement-backlog.md")
    monkeypatch.setattr(harden_live_readiness.live_readiness_stress, "run", lambda all_categories=True: _stress())

    report = harden_live_readiness.run(max_iters=1)

    assert report["iterations"][0]["automatic_patch_candidates"] == 1
    assert report["improvement_backlog"]["item_count"] == 3
    assert "Build -> Review -> Test -> Fix" in report["improvement_backlog"]["process_principle"]
    assert (tmp_path / "hardening-live-readiness.json").exists()
    assert (tmp_path / "improvement-backlog.json").exists()
