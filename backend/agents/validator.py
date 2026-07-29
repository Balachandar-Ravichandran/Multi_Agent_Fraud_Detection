"""The single reusable gate function (PRD Section 9), called at all seven
checkpoints listed there. Each call is an independent model call (Haiku)
with no shared context with whatever it's checking.

Retry *mechanics* -- what actually changes between attempts -- are
stage-specific and owned by the caller (e.g. checks/price_po_contract.py's
three retrieval strategies for Gate 2, or orchestrator/plan.py's re-plan
for Gate 1). This module only renders the pass/fail judgment, tracks the
retry cap, and (for six of the seven stages) emits the matching event.

Gate 2 ("post_rag") is the one exception: Section 11.4 attributes its
events (RETRIEVAL_SUCCEEDED / RETRIEVAL_LOW_CONFIDENCE) to
checks/price_po_contract.py::retrieve_clause(), not to validate() itself --
unlike every other gate, whose PASSED/FAILED event the catalogue attributes
directly to this function. So validate("post_rag", ...) deliberately
returns without emitting; the caller does it under its own event names.

Not executed in this pass -- no live API call has been made against this
module yet.
"""
from __future__ import annotations

from core.events import emit
from core.llm import HAIKU_MODEL, call
from core.prompts import GATE_POST_CLASSIFICATION, GATE_POST_FINDING, GATE_POST_PLAN, GATE_POST_RAG, GATE_POST_STORAGE, GATE_POST_SUMMARY, GATE_QA_GROUNDING
from core.schemas import ValidationResult

# Section 9's table, column "Cap".
RETRY_CAPS: dict[str, int] = {
    "post_plan": 2,
    "post_rag": 3,
    "post_storage": 2,
    "post_finding": 2,
    "post_classification": 2,
    "post_summary": 2,
    "qa_grounding": 2,
}

# (category for emit(), (passed_event, failed_event)) -- omitted for
# "post_rag" per this module's docstring.
GATE_EVENTS: dict[str, tuple[str, tuple[str, str]]] = {
    "post_plan": ("plan", ("GATE_1_PASSED", "GATE_1_FAILED")),
    "post_storage": ("retrieval", ("GATE_3_PASSED", "GATE_3_FAILED")),
    "post_finding": ("retrieval", ("GATE_4_PASSED", "GATE_4_FAILED")),
    "post_classification": ("classification", ("VALIDATION_PASSED", "VALIDATION_FAILED")),
    "post_summary": ("summary", ("GATE_6_PASSED", "GATE_6_FAILED")),
    "qa_grounding": ("summary", ("QA_GROUNDING_PASSED", "QA_GROUNDING_FAILED")),
}

GATE_SYSTEM_PROMPTS: dict[str, str] = {
    "post_plan": GATE_POST_PLAN,
    "post_rag": GATE_POST_RAG,
    "post_storage": GATE_POST_STORAGE,
    "post_finding": GATE_POST_FINDING,
    "post_classification": GATE_POST_CLASSIFICATION,
    "post_summary": GATE_POST_SUMMARY,
    "qa_grounding": GATE_QA_GROUNDING,
}


def validate(stage: str, output: str, context: str, retry_count: int, run_id: str) -> ValidationResult:
    if stage not in GATE_SYSTEM_PROMPTS:
        raise ValueError(f"Unknown validation stage '{stage}'")

    prompt = f"Context:\n{context}\n\nOutput to judge:\n{output}"
    raw = call(HAIKU_MODEL, "low", GATE_SYSTEM_PROMPTS[stage], prompt)
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    passed = bool(lines) and lines[0].upper().startswith("PASS")
    reason = lines[1] if len(lines) > 1 else (lines[0] if lines else "No response from validator model")

    if stage in GATE_EVENTS:
        category, (passed_event, failed_event) = GATE_EVENTS[stage]
        emit(category, passed_event if passed else failed_event, run_id=run_id, stage=stage, retry_count=retry_count, reason=reason)

    if not passed and retry_count >= RETRY_CAPS[stage]:
        emit("plan", "ESCALATION_TRIGGERED", run_id=run_id, stage=stage, retry_count=retry_count)

    return ValidationResult(gate=stage, passed=passed, reason=reason, retry_count=retry_count, checked_by_model=HAIKU_MODEL)
