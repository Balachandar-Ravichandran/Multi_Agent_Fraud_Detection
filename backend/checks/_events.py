"""Shared event-emission helpers for the seven checks (PRD Section 11.3).

Each check's own run() calls these directly (JOB_STARTED on invocation,
JOB_RESULT + ANOMALY_DETECTED/ANOMALY_DISMISSED_WITHIN_TOLERANCE on
completion) -- factored out only to avoid repeating the same payload
construction seven times, not to move the emission site away from run().
"""
from __future__ import annotations

from core.events import emit
from core.schemas import CheckJobResult

CHECK_7_NAME = "price_po_contract"


def emit_job_started(check_name: str, invoice_id: str, run_id: str) -> None:
    emit("act", "JOB_STARTED", run_id=run_id, check_name=check_name, invoice_id=invoice_id)


def emit_job_result(result: CheckJobResult, invoice_id: str, run_id: str) -> None:
    emit(
        "act", "JOB_RESULT", run_id=run_id, check_name=result.check_name, invoice_id=invoice_id,
        result=result.result, fraud_type=result.fraud_type.value if result.fraud_type else None,
    )

    if result.result == "ANOMALY":
        emit(
            "act", "ANOMALY_DETECTED", run_id=run_id, check_name=result.check_name,
            invoice_id=invoice_id, fraud_type=result.fraud_type.value if result.fraud_type else None,
        )
    elif result.check_name == CHECK_7_NAME and result.result == "CLEAN":
        # Decision Point 2's other branch (Section 7) -- check 7 only.
        emit("act", "ANOMALY_DISMISSED_WITHIN_TOLERANCE", run_id=run_id, check_name=result.check_name, invoice_id=invoice_id)
