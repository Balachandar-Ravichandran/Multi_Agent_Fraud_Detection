"""Check 1: vendor & PO validity (PRD Section 7).

vendor_master.status == "Approved" AND po_reference exists in purchase_orders.
Fraud type on failure: PHANTOM_VENDOR.
"""
from __future__ import annotations

import sqlite3

from checks._events import emit_job_result, emit_job_started
from core.schemas import Citation, CheckJobResult, FraudType
from tools import storage_tool

CHECK_NAME = "vendor_po_validity"


def run(conn: sqlite3.Connection, invoice: dict, run_id: str | None = None) -> CheckJobResult:
    if run_id is not None:
        emit_job_started(CHECK_NAME, invoice["invoice_id"], run_id)

    vendor = storage_tool.lookup_vendor(conn, invoice["vendor_id"])
    po = storage_tool.lookup_po(conn, invoice["po_reference"])

    citations = []
    if vendor is not None:
        citations.append(Citation(
            source_type="vendor_master", source_id=vendor["vendor_id"],
            excerpt=f"{vendor['name']}, status={vendor['status']}",
        ))
    else:
        citations.append(Citation(
            source_type="vendor_master", source_id=invoice["vendor_id"],
            excerpt="No vendor_master record found for this vendor_id.",
        ))
    if po is not None:
        citations.append(Citation(
            source_type="po", source_id=po["po_number"],
            excerpt=f"On file for vendor {po['vendor_id']}, item {po['item_description']}",
        ))
    else:
        citations.append(Citation(
            source_type="po", source_id=invoice["po_reference"],
            excerpt="No purchase_orders record found for this po_reference.",
        ))

    vendor_ok = vendor is not None and vendor["status"] == "Approved"
    po_ok = po is not None

    if vendor_ok and po_ok:
        result = CheckJobResult(check_name=CHECK_NAME, result="CLEAN", citations=citations)
    else:
        result = CheckJobResult(
            check_name=CHECK_NAME, result="ANOMALY",
            fraud_type=FraudType.PHANTOM_VENDOR, citations=citations,
        )

    if run_id is not None:
        emit_job_result(result, invoice["invoice_id"], run_id)
    return result
