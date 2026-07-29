"""Exercises the orchestrator's deterministic node prefix (plan -> decide ->
act -> classify) for real, using the graph's own node functions -- not
mocks. Stops before gate5/summarize, which need a live ANTHROPIC_API_KEY
and are out of scope for this pass (see CLAUDE.md).
"""
import pytest

import core.events as events_module
from orchestrator.graph import (
    node_act_audit, node_classify, node_decide_audit, node_plan_audit, route_after_classify,
)
from tests.conftest import build_invoice


@pytest.fixture(autouse=True)
def isolated_logs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(events_module, "LOGS_DIR", tmp_path)


def test_audit_pipeline_prefix_flags_price_inflation():
    invoice = build_invoice("INV-2024-0842")
    state = {
        "run_id": "orchestrator-test-1",
        "invoice_id": invoice["invoice_id"],
        "vendor_id": invoice["vendor_id"],
        "po_reference": invoice["po_reference"],
        "raw_fields": invoice,
    }

    state = node_plan_audit(state)
    assert len(state["jobs"]) == 7

    state = node_decide_audit(state)
    assert len(state["jobs"]) == 7  # dispatch is a pass-through for Audit Mode

    state = node_act_audit(state)
    assert len(state["job_results"]) == 7

    state = node_classify(state)
    assert state["draft_report"].fraud_type.value == "PRICE_INFLATION"
    assert route_after_classify(state) == "anomaly"


def test_audit_pipeline_prefix_clean_invoice():
    invoice = build_invoice("INV-2024-1001")
    state = {
        "run_id": "orchestrator-test-2",
        "invoice_id": invoice["invoice_id"],
        "vendor_id": invoice["vendor_id"],
        "po_reference": invoice["po_reference"],
        "raw_fields": invoice,
    }

    state = node_plan_audit(state)
    state = node_decide_audit(state)
    state = node_act_audit(state)
    state = node_classify(state)

    assert state["draft_report"].fraud_type.value == "CLEAN"
    assert route_after_classify(state) == "clean"
