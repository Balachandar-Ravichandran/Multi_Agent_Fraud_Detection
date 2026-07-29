"""Check 2: bank account match (PRD Section 7).

Invoice's stated account vs. vendor_master.bank_account_last4.
Fraud type on mismatch: ALTERED_BANK_DETAILS.
"""
from __future__ import annotations

import sqlite3

from checks._events import emit_job_result, emit_job_started
from core.schemas import Citation, CheckJobResult, FraudType
from tools import storage_tool

CHECK_NAME = "bank_account_match"


def run(conn: sqlite3.Connection, invoice: dict, run_id: str | None = None) -> CheckJobResult:
    if run_id is not None:
        emit_job_started(CHECK_NAME, invoice["invoice_id"], run_id)

    vendor = storage_tool.lookup_vendor(conn, invoice["vendor_id"])
    if vendor is None:
        # Check 1 already reports this as PHANTOM_VENDOR -- nothing to compare here.
        result = CheckJobResult(check_name=CHECK_NAME, result="NOT_APPLICABLE", citations=[])
    else:
        invoice_account = invoice["bank_account_last4_on_invoice"]
        vendor_account = vendor["bank_account_last4"]
        citations = [Citation(
            source_type="vendor_master", source_id=vendor["vendor_id"],
            excerpt=f"Bank account on file ends {vendor_account}",
        )]

        if invoice_account == vendor_account:
            result = CheckJobResult(check_name=CHECK_NAME, result="CLEAN", citations=citations)
        else:
            result = CheckJobResult(
                check_name=CHECK_NAME, result="ANOMALY",
                fraud_type=FraudType.ALTERED_BANK_DETAILS,
                citations=citations + [Citation(
                    source_type="ledger", source_id=invoice["invoice_id"],
                    excerpt=f"Invoice lists account ending {invoice_account}",
                )],
            )

    if run_id is not None:
        emit_job_result(result, invoice["invoice_id"], run_id)
    return result
