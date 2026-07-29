"""End-to-end check on the golden dataset (PRD Section 18): for every one of
the 20 invoices, run all 7 checks against the real ingested SQLite/Chroma
data plus the real PDF, classify the result, and compare against
golden_dataset_labels.json. This is the deterministic slice of what
eval/run_golden_set.py (Section 17, Phase 4) will do for the full pipeline.
"""
import json

import pytest

from agents.classifier import classify
from tests.conftest import LABELS_PATH, build_invoice, run_all_checks
from tools import storage_tool

LABELS = json.loads(LABELS_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("label", LABELS, ids=lambda label: label["invoice_id"])
def test_golden_invoice_matches_expected_fraud_type(label):
    conn = storage_tool.get_connection()
    try:
        invoice = build_invoice(label["invoice_id"])
        results = run_all_checks(conn, invoice)
        report = classify(label["invoice_id"], results)
    finally:
        conn.close()

    assert report.fraud_type.value == label["expected_fraud_type"], (
        f"{label['invoice_id']}: expected {label['expected_fraud_type']}, "
        f"got {report.fraud_type.value}. ground_truth_notes: {label['ground_truth_notes']}"
    )
    assert (report.fraud_type.value != "CLEAN") == label["expected_flag"]
