"""Check 3: quantity check (PRD Section 7).

Invoice qty > min(quantity_approved, quantity_delivered).
Fraud type on overbilling: QUANTITY_MISMATCH.
"""
from __future__ import annotations

import sqlite3

from checks._events import emit_job_result, emit_job_started
from core.schemas import Citation, CheckJobResult, FraudType
from tools import storage_tool

CHECK_NAME = "quantity_check"


def run(conn: sqlite3.Connection, invoice: dict, run_id: str | None = None) -> CheckJobResult:
    if run_id is not None:
        emit_job_started(CHECK_NAME, invoice["invoice_id"], run_id)

    po = storage_tool.lookup_po(conn, invoice["po_reference"])
    delivery = storage_tool.lookup_delivery(conn, invoice["po_reference"])

    if po is None or delivery is None:
        # Undetermined without both a PO and a delivery record -- checks 1/4
        # separately report the missing record itself as an anomaly.
        result = CheckJobResult(check_name=CHECK_NAME, result="NOT_APPLICABLE", citations=[])
    else:
        qty_billed = invoice["qty_billed"]
        max_allowed = min(po["quantity_approved"], delivery["quantity_delivered"])

        citations = [
            Citation(source_type="po", source_id=po["po_number"], excerpt=f"quantity_approved={po['quantity_approved']}"),
            Citation(source_type="delivery", source_id=po["po_number"], excerpt=f"quantity_delivered={delivery['quantity_delivered']}"),
        ]

        if qty_billed <= max_allowed:
            result = CheckJobResult(check_name=CHECK_NAME, result="CLEAN", citations=citations)
        else:
            result = CheckJobResult(
                check_name=CHECK_NAME, result="ANOMALY",
                fraud_type=FraudType.QUANTITY_MISMATCH,
                magnitude=qty_billed - max_allowed,
                citations=citations,
            )

    if run_id is not None:
        emit_job_result(result, invoice["invoice_id"], run_id)
    return result
