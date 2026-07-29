"""Check 5: duplicate billing (PRD Section 7).

(vendor_id, po_reference, amount) already present in the ledger under a
different invoice_id, received earlier. Fraud type: DUPLICATE_BILLING.
"""
from __future__ import annotations

import sqlite3

from checks._events import emit_job_result, emit_job_started
from core.schemas import Citation, CheckJobResult, FraudType
from tools import storage_tool

CHECK_NAME = "duplicate_billing"


def run(conn: sqlite3.Connection, invoice: dict, run_id: str | None = None) -> CheckJobResult:
    if run_id is not None:
        emit_job_started(CHECK_NAME, invoice["invoice_id"], run_id)

    matches = storage_tool.lookup_ledger_matches(
        conn, invoice["vendor_id"], invoice["po_reference"], invoice["amount"],
        invoice["invoice_id"], invoice["date_received"],
    )

    if not matches:
        result = CheckJobResult(check_name=CHECK_NAME, result="CLEAN", citations=[])
    else:
        citations = [
            Citation(
                source_type="ledger", source_id=m["invoice_id"],
                excerpt=f"Same vendor+PO+amount, status={m['status']}, received={m['date_received']}",
            )
            for m in matches
        ]
        result = CheckJobResult(
            check_name=CHECK_NAME, result="ANOMALY",
            fraud_type=FraudType.DUPLICATE_BILLING, citations=citations,
        )

    if run_id is not None:
        emit_job_result(result, invoice["invoice_id"], run_id)
    return result
