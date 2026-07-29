"""Decide stage (PRD Section 6).

Audit Mode: dispatch is close to a lookup -- the job list is fixed, so
dispatch_jobs() is pure. Q&A Mode: a genuine per-question routing decision
among RAG, Storage, both, or neither (already made by Plan; Decide just
normalizes and logs it here). apply_confidence_threshold() is Decision
Point 4 (Section 9).
"""
from __future__ import annotations

from core.events import emit
from core.schemas import FraudReport

VALID_QA_TOOLS = ("RAG", "STORAGE", "BOTH", "NEITHER")


def dispatch_jobs(jobs: list[str], run_id: str) -> list[str]:
    emit("act", "DECIDE_DISPATCHED", run_id=run_id, jobs=jobs)
    return jobs


def select_qa_tool(tool_choice: str, run_id: str) -> str:
    normalized = tool_choice if tool_choice in VALID_QA_TOOLS else "NEITHER"
    emit("act", "QA_TOOL_SELECTED", run_id=run_id, tool=normalized)
    return normalized


def apply_confidence_threshold(report: FraudReport, run_id: str) -> str:
    """Decision Point 4 (Section 9): only reached if check 7 fired and Gate 5
    passed. >=0.85 -> auto-flag; 0.60-0.85 -> human review; <0.60 -> always
    human review, never auto-clears. Checks 1-6 (confidence is None) are
    certain by construction -- auto-flag directly, no threshold involved.
    """
    if report.confidence is None:
        emit("classification", "DECISION_AUTO_FLAG", run_id=run_id, invoice_id=report.invoice_id, via="certain")
        return "auto_flagged"

    if report.confidence >= 0.85:
        emit(
            "classification", "DECISION_AUTO_FLAG", run_id=run_id,
            invoice_id=report.invoice_id, via="confidence", confidence=report.confidence,
        )
        return "auto_flagged"

    emit("classification", "DECISION_HUMAN_REVIEW", run_id=run_id, invoice_id=report.invoice_id, confidence=report.confidence)
    return "human_review"
