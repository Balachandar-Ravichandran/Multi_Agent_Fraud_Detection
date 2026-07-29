"""Plan stage (PRD Section 6).

Audit Mode's plan is the fixed 7-job checklist (Section 7) -- no LLM
judgment is needed to produce it, so create_audit_plan() is pure and
deterministic. Q&A Mode's plan is a genuine LLM decision over conversation
history and the existing case (Sonnet, high effort).

Not executed in this pass for create_qa_plan()/replan() (LLM calls) --
create_audit_plan() is pure and was exercised indirectly via the checks
test suite already.
"""
from __future__ import annotations

from core.events import emit
from core.llm import SONNET_MODEL, call
from core.schemas import CHECK_NAMES

QA_PLAN_SYSTEM_PROMPT = (
    "Given a fraud case's conversation history and existing report, decide "
    "what information is needed to answer the user's latest question. "
    "Respond with exactly one word: RAG, STORAGE, BOTH, or NEITHER."
)


def create_audit_plan(run_id: str) -> list[str]:
    """The fixed 7-job checklist -- Audit Mode never varies this (Section 7)."""
    jobs = list(CHECK_NAMES)
    emit("plan", "PLAN_CREATED", run_id=run_id, jobs=jobs)
    return jobs


def create_qa_plan(question: str, case_summary: str, conversation_history: list[dict], run_id: str) -> str:
    history_text = "\n".join(f"{h.get('role')}: {h.get('content')}" for h in conversation_history)
    prompt = f"Case summary:\n{case_summary}\n\nConversation so far:\n{history_text}\n\nLatest question:\n{question}"
    tool_choice = call(SONNET_MODEL, "high", QA_PLAN_SYSTEM_PROMPT, prompt).strip().upper()
    emit("plan", "QA_PLAN_CREATED", run_id=run_id, question=question, tool_choice=tool_choice)
    return tool_choice


def replan(objection: str, run_id: str) -> list[str]:
    """Gate 1 retry: re-plan with the Validator's specific objection appended (Section 9).

    Audit Mode's plan is fixed regardless of objection content -- the only
    sane re-plan is still the complete 7-job list. Gate 1 exists as a
    defect safety net here (same role Gate 4 plays for checks 1-6), not a
    routine correction path.
    """
    emit("plan", "REPLAN_TRIGGERED", run_id=run_id, objection=objection)
    return list(CHECK_NAMES)
