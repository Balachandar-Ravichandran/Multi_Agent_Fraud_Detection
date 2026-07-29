"""Builds the LangGraph StateGraph for both Audit Mode and Q&A Mode (PRD Section 4).

Not executed in this pass beyond a structural compile check -- every node
that calls an LLM (preconditions, Q&A plan, the Validator gates, summary's
narrative) needs a live ANTHROPIC_API_KEY, which this pass deliberately
does not exercise (see CLAUDE.md). checks/*.py and agents/classifier.py,
which this graph also calls, are fully exercised already in tests/.

Each DB-touching node opens and closes its own short-lived SQLite
connection via tools.storage_tool.get_connection() rather than threading a
connection through graph state.
"""
from __future__ import annotations

import uuid

from checks import (
    bank_account_match, delivery_inspection, duplicate_billing,
    price_po_contract, quantity_check, split_invoicing, vendor_po_validity,
)
from core.events import emit
from core.llm import HAIKU_MODEL, call
from core.schemas import Citation
from agents import classifier, summary, validator
from orchestrator import decide, plan
from orchestrator.state import GraphState
from preconditions import agent as preconditions_agent
from tools import rag_tool, storage_tool
from tools.invoice_pdf import extract_invoice_fields

from langgraph.graph import END, StateGraph

CHECK_MODULES = [
    vendor_po_validity, bank_account_match, quantity_check,
    delivery_inspection, duplicate_billing, split_invoicing, price_po_contract,
]


# ---- Shared entry ---------------------------------------------------------

def node_preconditions(state: GraphState) -> GraphState:
    run_id = state.get("run_id") or uuid.uuid4().hex[:12]
    result = preconditions_agent.run(
        message=state.get("qa_question", ""),
        document_text=state.get("raw_fields", {}).get("_raw_text"),
        has_attached_file=bool(state.get("raw_fields")),
        session_invoice_id=state.get("invoice_id"),
        has_prior_case=state.get("status") == "done",
        run_id=run_id,
    )
    return {
        **state, "run_id": run_id, "mode": result.mode,
        "invoice_id": result.invoice_id or state.get("invoice_id", ""),
        "status": "blocked" if result.mode == "blocked" else ("awaiting_upload" if result.mode == "needs_upload" else "planning"),
        "message": result.reason or "",
    }


def route_after_preconditions(state: GraphState) -> str:
    if state["mode"] in ("blocked", "needs_upload"):
        return "fixed_template"
    if state["mode"] == "follow_up":
        return "qa"
    return "audit"


# ---- Audit Mode -------------------------------------------------------------

def node_plan_audit(state: GraphState) -> GraphState:
    jobs = plan.create_audit_plan(state["run_id"])
    return {**state, "status": "planning", "jobs": jobs}


def node_decide_audit(state: GraphState) -> GraphState:
    jobs = decide.dispatch_jobs(state["jobs"], state["run_id"])
    return {**state, "jobs": jobs}


def node_act_audit(state: GraphState) -> GraphState:
    """All 7 checks (Section 7). Run sequentially here for simplicity --
    each is a fast local DB/RAG call, not slow enough to need real
    concurrency; the PRD's "run in parallel" is a logical guarantee (nothing
    is conditionally skipped) that this preserves regardless of execution order.

    Uses the freshly-uploaded file's own invoice_id, not state["invoice_id"]
    (which is Preconditions' chat-text-only mode detection -- a message like
    "can you audit this invoice?" never restates the ID the attached PDF
    already carries, so that field is often empty at this point).
    """
    invoice_id = state["raw_fields"].get("invoice_id") or state["invoice_id"]

    conn = storage_tool.get_connection()
    try:
        invoice = {"invoice_id": invoice_id, **state["raw_fields"]}
        ledger_row = conn.execute(
            "SELECT * FROM invoice_ledger WHERE invoice_id = ?", (invoice_id,),
        ).fetchone()
        if ledger_row:
            invoice = {**dict(ledger_row), **invoice}

        # Ensure vendor_id is present (required by all checks). If not in ledger,
        # look it up from vendor_master by PO reference, or use placeholder.
        if "vendor_id" not in invoice and invoice.get("po_reference"):
            po_ref = invoice["po_reference"]
            po_row = conn.execute(
                "SELECT vendor_id FROM purchase_orders WHERE po_number = ? LIMIT 1", (po_ref,)
            ).fetchone()
            if po_row:
                invoice["vendor_id"] = po_row[0]

        # Final fallback: use empty string (vendor_po_validity check will flag as PHANTOM_VENDOR)
        invoice.setdefault("vendor_id", "")

        job_results = [module.run(conn, invoice, run_id=state["run_id"]) for module in CHECK_MODULES]
    finally:
        conn.close()

    return {
        **state,
        "invoice_id": invoice_id,
        "vendor_id": invoice.get("vendor_id", ""),
        "po_reference": invoice.get("po_reference") or invoice.get("po_reference_on_invoice", ""),
        "job_results": job_results,
        "status": "classifying",
    }


def node_classify(state: GraphState) -> GraphState:
    report = classifier.classify(state["invoice_id"], state["job_results"], run_id=state["run_id"])
    return {**state, "draft_report": report, "status": "validating"}


def route_after_classify(state: GraphState) -> str:
    return "clean" if state["draft_report"].fraud_type.value == "CLEAN" else "anomaly"


def node_gate5(state: GraphState) -> GraphState:
    """Post-Classification gate (Decision Point 3, Section 9)."""
    report = state["draft_report"]
    context = f"Job results: {[r.model_dump() for r in state['job_results']]}"
    output = report.model_dump_json()
    validation = validator.validate("post_classification", output, context, retry_count=0, run_id=state["run_id"])
    log = state.get("validation_log", []) + [validation]

    if not validation.passed:
        # Section 9: finalize with severity capped medium, human_review --
        # not a hard failure, so we don't re-raise or loop here.
        report = report.model_copy(update={"severity": "medium", "recommended_action": "human_review"})

    return {**state, "draft_report": report, "validation_log": log}


def node_confidence_decision(state: GraphState) -> GraphState:
    action = decide.apply_confidence_threshold(state["draft_report"], state["run_id"])
    report = state["draft_report"].model_copy(update={"recommended_action": action})
    return {**state, "draft_report": report}


def node_summarize_audit(state: GraphState) -> GraphState:
    conn = storage_tool.get_connection()
    try:
        vendor = storage_tool.lookup_vendor(conn, state.get("vendor_id", "")) or {}
    finally:
        conn.close()

    report = state["draft_report"]
    message = summary.generate(
        invoice_id=state["invoice_id"],
        vendor_name=vendor.get("name", state.get("vendor_id", "unknown vendor")),
        amount=state["raw_fields"].get("total_due", 0.0),
        report=report,
        job_results=state["job_results"],
        run_id=state["run_id"],
        path="audit",
    )

    gate6 = validator.validate("post_summary", message, report.model_dump_json(), retry_count=0, run_id=state["run_id"])
    log = state.get("validation_log", []) + [gate6]

    return {**state, "message": message, "validation_log": log, "status": "done"}


# ---- Q&A Mode ---------------------------------------------------------------

def node_plan_qa(state: GraphState) -> GraphState:
    case_summary = state.get("draft_report").model_dump_json() if state.get("draft_report") else "no prior report"
    tool_choice = plan.create_qa_plan(
        state.get("qa_question", ""), case_summary, state.get("conversation_history", []), state["run_id"],
    )
    return {**state, "qa_tool_choice": tool_choice}


def node_decide_qa(state: GraphState) -> GraphState:
    tool = decide.select_qa_tool(state["qa_tool_choice"], state["run_id"])
    return {**state, "qa_tool_choice": tool}


QA_ANSWER_SYSTEM_PROMPT = (
    "Answer the user's follow-up question about a fraud-audit case, using "
    "only facts present in the context below (the case's own report plus "
    "whatever was just retrieved). If the context doesn't answer the "
    "question, say so plainly rather than guessing or inventing a fact."
)


def node_act_qa(state: GraphState) -> GraphState:
    """Executes whatever Decide picked (Section 6): RAG, Storage, both, or
    neither. Citations gathered here feed the qa_grounding gate in
    node_summarize_qa below.
    """
    tool = state["qa_tool_choice"]
    report = state.get("draft_report")
    citations: list[Citation] = list(report.evidence) if report else []

    conn = storage_tool.get_connection()
    try:
        vendor = storage_tool.lookup_vendor(conn, state.get("vendor_id", "")) if state.get("vendor_id") else None

        if tool in ("STORAGE", "BOTH"):
            if vendor:
                citations.append(Citation(
                    source_type="vendor_master", source_id=vendor["vendor_id"],
                    excerpt=f"{vendor['name']}, status={vendor['status']}, bank_account_last4={vendor['bank_account_last4']}",
                ))
            po = storage_tool.lookup_po(conn, state.get("po_reference", "")) if state.get("po_reference") else None
            if po:
                citations.append(Citation(
                    source_type="po", source_id=po["po_number"],
                    excerpt=f"item={po['item_description']}, quantity_approved={po['quantity_approved']}, unit_price_approved={po['unit_price_approved']}",
                ))
    finally:
        conn.close()

    if tool in ("RAG", "BOTH") and state.get("vendor_id"):
        results = rag_tool.search_contract_clauses(
            state.get("qa_question", ""), vendor_id=state["vendor_id"], top_k=3,
        )
        for r in results[:2]:
            citations.append(Citation(source_type="contract", source_id=r["id"], excerpt=r["document"][:300]))

    context = (
        f"Case report: {report.model_dump_json() if report else 'no prior report for this invoice'}\n"
        f"Evidence available: {[c.model_dump() for c in citations]}"
    )
    answer = call(HAIKU_MODEL, "low", QA_ANSWER_SYSTEM_PROMPT, f"{context}\n\nQuestion: {state.get('qa_question', '')}")

    return {**state, "message": answer.strip(), "qa_citations": citations}


def node_summarize_qa(state: GraphState) -> GraphState:
    citations = state.get("qa_citations", [])
    context = f"Citations available: {[c.model_dump() for c in citations]}"
    grounding = validator.validate("qa_grounding", state["message"], context, retry_count=0, run_id=state["run_id"])
    log = state.get("validation_log", []) + [grounding]

    answer = state["message"]
    if not grounding.passed:
        # Section 9's Q&A Grounding Gate: ship with an explicit caveat on
        # cap exceeded, not a block.
        answer += "\n\n[Caveat: this answer includes a claim that could not be fully verified against on-file evidence.]"

    message = summary.generate_fixed_template(answer, state["run_id"], path="qa")
    return {**state, "message": message, "validation_log": log, "status": "done"}


# ---- Fixed-template path (blocked / needs_upload) --------------------------

def node_summarize_fixed(state: GraphState) -> GraphState:
    message = summary.generate_fixed_template(
        state.get("message") or "Please upload an invoice to begin.", state["run_id"], path=state["mode"],
    )
    return {**state, "message": message}


# ---- Finalize ----------------------------------------------------------------

def node_finalize(state: GraphState) -> GraphState:
    report = state.get("draft_report")
    # Only a genuine audit completion re-records the case outcome -- a
    # follow_up turn also carries draft_report (copied in from the prior
    # case so Q&A has something to answer from), but re-writing the ledger
    # and appending another episodic_memory row for a question that changed
    # nothing about the actual finding would be a duplicate, not a new outcome.
    if report is not None and state.get("mode") != "follow_up":
        conn = storage_tool.get_connection()
        try:
            storage_tool.record_case_outcome(
                conn, state["invoice_id"], state.get("vendor_id", ""), state.get("po_reference", ""),
                report.fraud_type.value, report.confidence,
                human_review_required=report.recommended_action == "human_review",
            )
        finally:
            conn.close()

    emit("summary", "REPORT_FINALIZED", run_id=state["run_id"], invoice_id=state.get("invoice_id", ""), mode=state.get("mode", ""))

    # REPORT_FINALIZED fires for every path (Section 11.6), but "done" only
    # applies to a genuinely completed audit/Q&A turn -- blocked/awaiting_upload
    # are their own terminal statuses (Section 6) and shouldn't be clobbered.
    status = state.get("status", "done")
    if status not in ("blocked", "awaiting_upload"):
        status = "done"
    return {**state, "status": status}


def build_graph():
    graph = StateGraph(GraphState)

    graph.add_node("preconditions", node_preconditions)
    graph.add_node("plan_audit", node_plan_audit)
    graph.add_node("decide_audit", node_decide_audit)
    graph.add_node("act_audit", node_act_audit)
    graph.add_node("classify", node_classify)
    graph.add_node("gate5", node_gate5)
    graph.add_node("confidence_decision", node_confidence_decision)
    graph.add_node("summarize_audit", node_summarize_audit)
    graph.add_node("plan_qa", node_plan_qa)
    graph.add_node("decide_qa", node_decide_qa)
    graph.add_node("act_qa", node_act_qa)
    graph.add_node("summarize_qa", node_summarize_qa)
    graph.add_node("summarize_fixed", node_summarize_fixed)
    graph.add_node("finalize", node_finalize)

    graph.set_entry_point("preconditions")
    graph.add_conditional_edges(
        "preconditions", route_after_preconditions,
        {"fixed_template": "summarize_fixed", "qa": "plan_qa", "audit": "plan_audit"},
    )

    graph.add_edge("plan_audit", "decide_audit")
    graph.add_edge("decide_audit", "act_audit")
    graph.add_edge("act_audit", "classify")
    graph.add_edge("classify", "gate5")
    graph.add_conditional_edges(
        "gate5", route_after_classify,
        {"clean": "summarize_audit", "anomaly": "confidence_decision"},
    )
    graph.add_edge("confidence_decision", "summarize_audit")
    graph.add_edge("summarize_audit", "finalize")

    graph.add_edge("plan_qa", "decide_qa")
    graph.add_edge("decide_qa", "act_qa")
    graph.add_edge("act_qa", "summarize_qa")
    graph.add_edge("summarize_qa", "finalize")

    graph.add_edge("summarize_fixed", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


def run_audit_pipeline(
    invoice_id: str, vendor_id: str, po_reference: str, raw_fields: dict, run_id: str | None = None,
) -> GraphState:
    """Runs the Audit Mode path directly, node by node, bypassing the
    compiled graph's single fixed entry point ("preconditions").

    Useful when the caller already knows it's an audit and doesn't need
    Preconditions' LLM-based mode detection (e.g. eval/run_golden_set.py,
    Section 17 Phase 4). Real chat turns should invoke build_graph()'s
    compiled app from "preconditions" instead, via app.invoke(...).
    """
    state: GraphState = {
        "run_id": run_id or uuid.uuid4().hex[:12],
        "mode": "audit",
        "invoice_id": invoice_id,
        "vendor_id": vendor_id,
        "po_reference": po_reference,
        "raw_fields": raw_fields,
        "status": "planning",
    }
    state = node_plan_audit(state)
    state = node_decide_audit(state)
    state = node_act_audit(state)
    state = node_classify(state)
    state = node_gate5(state)
    if route_after_classify(state) == "anomaly":
        state = node_confidence_decision(state)
    state = node_summarize_audit(state)
    return node_finalize(state)
