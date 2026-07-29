"""Check 4: delivery & inspection (PRD Section 7).

Delivery record must exist for the po_reference; if the vendor requires
inspection sign-off, inspection_confirmed must also be true, else the
sub-result is ANOMALY, not silently passed. Fraud type: NON_DELIVERY.
"""
from __future__ import annotations

import sqlite3

from checks._events import emit_job_result, emit_job_started
from core.schemas import Citation, CheckJobResult, FraudType
from tools import storage_tool

CHECK_NAME = "delivery_inspection"

# Meridian Electronics Corp (VEND-1003) is the vendor the PRD names explicitly
# (Section 7): its contract's Section 5 requires a signed inspection
# confirmation in addition to the standard receiving-dock confirmation.
VENDORS_REQUIRING_INSPECTION = {"VEND-1003"}


def run(conn: sqlite3.Connection, invoice: dict, run_id: str | None = None) -> CheckJobResult:
    if run_id is not None:
        emit_job_started(CHECK_NAME, invoice["invoice_id"], run_id)

    delivery = storage_tool.lookup_delivery(conn, invoice["po_reference"])

    if delivery is None:
        result = CheckJobResult(
            check_name=CHECK_NAME, result="ANOMALY", fraud_type=FraudType.NON_DELIVERY,
            citations=[Citation(
                source_type="delivery", source_id=invoice["po_reference"],
                excerpt="No delivery record on file for this po_reference.",
            )],
        )
    else:
        citations = [Citation(
            source_type="delivery", source_id=invoice["po_reference"],
            excerpt=f"quantity_delivered={delivery['quantity_delivered']}, signed_by={delivery['signed_by']}",
        )]

        requires_inspection = invoice["vendor_id"] in VENDORS_REQUIRING_INSPECTION
        if requires_inspection and not delivery.get("inspection_confirmed"):
            result = CheckJobResult(
                check_name=CHECK_NAME, result="ANOMALY", fraud_type=FraudType.NON_DELIVERY,
                citations=citations + [Citation(
                    source_type="delivery", source_id=invoice["po_reference"],
                    excerpt="Vendor requires inspection sign-off; none on file.",
                )],
            )
        else:
            result = CheckJobResult(check_name=CHECK_NAME, result="CLEAN", citations=citations)

    if run_id is not None:
        emit_job_result(result, invoice["invoice_id"], run_id)
    return result
