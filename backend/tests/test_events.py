import json

import pytest

import core.events as events_module
from core.events import emit


@pytest.fixture(autouse=True)
def isolated_logs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(events_module, "LOGS_DIR", tmp_path)
    yield tmp_path


def test_emit_rejects_unknown_event():
    with pytest.raises(ValueError):
        emit("preconditions", "NOT_A_REAL_EVENT", run_id="run1")


def test_emit_requires_run_id():
    with pytest.raises(ValueError):
        emit("preconditions", "INJECTION_CHECKED")


def test_emit_writes_one_jsonl_line(isolated_logs_dir):
    emit("preconditions", "INJECTION_CHECKED", run_id="run1", invoice_id="INV-2024-0842")
    log_file = isolated_logs_dir / "run_run1.jsonl"
    assert log_file.exists()

    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "INJECTION_CHECKED"
    assert record["invoice_id"] == "INV-2024-0842"
    assert "timestamp" in record


def test_emit_appends_across_calls(isolated_logs_dir):
    emit("preconditions", "INJECTION_CHECKED", run_id="run2")
    emit("plan", "PLAN_CREATED", run_id="run2")
    log_file = isolated_logs_dir / "run_run2.jsonl"
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_all_36_events_are_registered():
    total = sum(len(v) for v in events_module.VALID_EVENTS.values())
    assert total == 36
