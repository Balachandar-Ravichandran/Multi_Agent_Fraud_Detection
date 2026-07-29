"""Orchestrator working state, adapted from FraudCaseState (Section 12.2) for LangGraph.

LangGraph's StateGraph works most simply over a TypedDict; this wraps
FraudCaseState's fields plus a couple of orchestration-only fields
(retry counters, run_id, the Q&A tool choice) that don't belong in the
persisted case schema itself.
"""
from __future__ import annotations

from typing import Literal, TypedDict

from core.schemas import Citation, CheckJobResult, FraudCaseState, FraudReport, ValidationResult


class GraphState(TypedDict, total=False):
    run_id: str
    mode: Literal["audit", "follow_up", "blocked", "needs_upload"]
    invoice_id: str
    vendor_id: str
    po_reference: str
    raw_fields: dict
    job_results: list[CheckJobResult]
    draft_report: FraudReport | None
    validation_log: list[ValidationResult]
    conversation_history: list[dict]
    status: str
    retry_counts: dict[str, int]
    qa_question: str
    qa_tool_choice: str
    qa_citations: list[Citation]  # gathered by act_qa, checked by the qa_grounding gate
    jobs: list[str]  # Audit Mode's 7-job checklist, threaded from plan -> decide -> act
    message: str  # Summary's final user-facing text


def to_case_state(state: GraphState) -> FraudCaseState:
    """Project the graph's working state into the persisted case schema (Section 12.2)."""
    return FraudCaseState(
        invoice_id=state["invoice_id"],
        vendor_id=state.get("vendor_id", ""),
        po_reference=state.get("po_reference", ""),
        raw_fields=state.get("raw_fields", {}),
        job_results=state.get("job_results", []),
        draft_report=state.get("draft_report"),
        validation_log=state.get("validation_log", []),
        conversation_history=state.get("conversation_history", []),
        status=state.get("status", "planning"),
    )
