"""Confirms checks/*.py actually emit Section 11.3's events when given a
run_id -- not just that the emit() plumbing works in isolation (test_events.py)
but that the checks call it correctly on a real anomaly.
"""
import json

import core.events as events_module
from checks import bank_account_match
from tests.conftest import build_invoice


def test_bank_account_check_emits_job_events_on_anomaly(tmp_path, monkeypatch, conn):
    monkeypatch.setattr(events_module, "LOGS_DIR", tmp_path)

    invoice = build_invoice("INV-2024-6001")  # golden-set ALTERED_BANK_DETAILS case
    result = bank_account_match.run(conn, invoice, run_id="evt-test")

    assert result.result == "ANOMALY"

    log_file = tmp_path / "run_evt-test.jsonl"
    records = [json.loads(line) for line in log_file.read_text(encoding="utf-8").splitlines()]
    events = [r["event"] for r in records]

    assert events == ["JOB_STARTED", "JOB_RESULT", "ANOMALY_DETECTED"]
    assert records[1]["fraud_type"] == "ALTERED_BANK_DETAILS"


def test_clean_check_emits_no_anomaly_event(tmp_path, monkeypatch, conn):
    monkeypatch.setattr(events_module, "LOGS_DIR", tmp_path)

    invoice = build_invoice("INV-2024-1001")  # golden-set CLEAN case
    result = bank_account_match.run(conn, invoice, run_id="evt-test2")
    assert result.result == "CLEAN"

    log_file = tmp_path / "run_evt-test2.jsonl"
    events = [json.loads(line)["event"] for line in log_file.read_text(encoding="utf-8").splitlines()]
    assert events == ["JOB_STARTED", "JOB_RESULT"]
