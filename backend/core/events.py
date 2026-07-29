"""Single JSONL logging call site (PRD Section 11's Event Catalogue).

Every named event in the catalogue is written here, one JSON line per event,
to /logs/run_<run_id>.jsonl. `emit()` rejects any event name not in the fixed
36-name catalogue below, so a typo or an invented event can never silently
ship as a phantom event (Section 11's stated goal).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BACKEND_DIR / "logs"

_lock = threading.Lock()

# Grouped exactly as Section 11.1-11.6. 36 event names total.
VALID_EVENTS: dict[str, set[str]] = {
    "preconditions": {
        "INJECTION_CHECKED", "INJECTION_BLOCKED", "MODE_DETECTED",
        "PRECONDITIONS_PASSED", "PRECONDITIONS_FAILED",
    },
    "plan": {
        "PLAN_CREATED", "QA_PLAN_CREATED", "REPLAN_TRIGGERED",
        "GATE_1_PASSED", "GATE_1_FAILED", "ESCALATION_TRIGGERED",
    },
    "act": {
        "DECIDE_DISPATCHED", "QA_TOOL_SELECTED", "JOB_STARTED", "JOB_RESULT",
        "ANOMALY_DETECTED", "ANOMALY_DISMISSED_WITHIN_TOLERANCE",
    },
    "retrieval": {
        "RETRIEVAL_STARTED", "RETRIEVAL_LOW_CONFIDENCE", "RETRY_QUERY",
        "RETRIEVAL_SUCCEEDED", "GATE_3_PASSED", "GATE_3_FAILED",
        "GATE_4_PASSED", "GATE_4_FAILED",
    },
    "classification": {
        "FRAUD_CLASSIFIED", "VALIDATION_PASSED", "VALIDATION_FAILED",
        "DECISION_AUTO_FLAG", "DECISION_HUMAN_REVIEW",
    },
    "summary": {
        "QA_GROUNDING_PASSED", "QA_GROUNDING_FAILED", "SUMMARY_GENERATED",
        "GATE_6_PASSED", "GATE_6_FAILED", "REPORT_FINALIZED",
    },
}

_ALL_VALID_EVENTS: frozenset[str] = frozenset().union(*VALID_EVENTS.values())


def emit(category: str, event: str, **payload) -> dict:
    """Append one JSON line to /logs/run_<run_id>.jsonl.

    `payload` must include `run_id` -- that's what routes the line to its
    run's log file; it's also kept in the record for traceability.
    """
    if event not in _ALL_VALID_EVENTS:
        raise ValueError(
            f"'{event}' is not in the Section 11 Event Catalogue. "
            "Add it there before emitting, or use the correct existing name."
        )
    if "run_id" not in payload:
        raise ValueError("emit() requires 'run_id' in payload to route the event to /logs/run_<run_id>.jsonl")

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": category,
        "event": event,
        **payload,
    }

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"run_{payload['run_id']}.jsonl"
    line = json.dumps(record, default=str)
    with _lock:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    return record
