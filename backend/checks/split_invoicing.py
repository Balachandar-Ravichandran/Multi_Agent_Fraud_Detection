"""Check 6: split invoicing (PRD Section 7).

Same vendor, different po_reference values, within a 7-day window, combined
value > $10,000. Same po_reference across invoices is a legitimate partial
shipment and is never flagged here.

Refinement beyond Section 7's one-line description, needed to match Section
18's own dataset notes: only invoices that are each *individually* under the
secondary-approval threshold are eligible to be grouped. Section 18 states
this explicitly for invoice 1002 ("Above $10k policy threshold but properly
single-invoiced; no anomaly" -- an approval-workflow fact, not a fraud
signal) and for 8001/8002 ("Individually under the $10k secondary-approval
threshold"). procurement_policy.md Section 3's anti-splitting rule is about
*avoiding* the threshold; an invoice that's already over it on its own was
never hiding from anything, so it can't anchor or join a splitting group.
Without this filter, two unrelated large invoices from the same vendor a few
days apart (e.g. golden-set invoices 1001 and 1004) would false-positive.
"""
from __future__ import annotations

import sqlite3

from checks._events import emit_job_result, emit_job_started
from core.schemas import Citation, CheckJobResult, FraudType
from tools import storage_tool

CHECK_NAME = "split_invoicing"


def run(conn: sqlite3.Connection, invoice: dict, run_id: str | None = None) -> CheckJobResult:
    if run_id is not None:
        emit_job_started(CHECK_NAME, invoice["invoice_id"], run_id)

    window_days = int(storage_tool.get_heuristic(conn, "split_invoicing_window_days"))
    threshold = storage_tool.get_heuristic(conn, "split_invoicing_threshold")

    if invoice["amount"] > threshold:
        # Already independently over the threshold -- not a splitting attempt.
        result = CheckJobResult(check_name=CHECK_NAME, result="CLEAN", citations=[])
    else:
        others = storage_tool.lookup_vendor_invoices_in_window(
            conn, invoice["vendor_id"], invoice["date_received"], window_days, invoice["invoice_id"],
        )
        group = [
            o for o in others
            if o["po_reference"] != invoice["po_reference"] and o["amount"] <= threshold
        ]
        combined = invoice["amount"] + sum(o["amount"] for o in group)

        if not group or combined <= threshold:
            result = CheckJobResult(check_name=CHECK_NAME, result="CLEAN", citations=[])
        else:
            citations = [
                Citation(
                    source_type="ledger", source_id=o["invoice_id"],
                    excerpt=f"Same vendor, PO {o['po_reference']}, ${o['amount']:,.2f}, received {o['date_received']}",
                )
                for o in group
            ]
            result = CheckJobResult(
                check_name=CHECK_NAME, result="ANOMALY",
                fraud_type=FraudType.SPLIT_INVOICING,
                magnitude=combined - threshold,
                citations=citations,
            )

    if run_id is not None:
        emit_job_result(result, invoice["invoice_id"], run_id)
    return result
