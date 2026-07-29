"""All Pydantic models for the fraud-detection pipeline (PRD Section 12).

Defined in dependency order (leaf types first) so no forward references
are needed.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel

SCHEMA_VERSION = "3.0"

# The seven checks always run, in this fixed order (Section 7).
CHECK_NAMES: tuple[str, ...] = (
    "vendor_po_validity",
    "bank_account_match",
    "quantity_check",
    "delivery_inspection",
    "duplicate_billing",
    "split_invoicing",
    "price_po_contract",
)


class FraudType(str, Enum):
    CLEAN = "CLEAN"
    PRICE_INFLATION = "PRICE_INFLATION"
    QUANTITY_MISMATCH = "QUANTITY_MISMATCH"
    PHANTOM_VENDOR = "PHANTOM_VENDOR"
    NON_DELIVERY = "NON_DELIVERY"
    ALTERED_BANK_DETAILS = "ALTERED_BANK_DETAILS"
    DUPLICATE_BILLING = "DUPLICATE_BILLING"
    SPLIT_INVOICING = "SPLIT_INVOICING"
    PO_EXCEEDS_CONTRACT_CEILING = "PO_EXCEEDS_CONTRACT_CEILING"


class Citation(BaseModel):
    source_type: Literal["contract", "policy", "po", "delivery", "vendor_master", "ledger"]
    source_id: str
    excerpt: str


class CheckJobResult(BaseModel):
    check_name: str
    result: Literal["ANOMALY", "CLEAN", "NOT_APPLICABLE"]
    fraud_type: FraudType | None = None
    magnitude: float | None = None
    rule_certainty: float | None = None  # only populated for check 7
    citations: list[Citation] = []


class FraudReport(BaseModel):
    schema_version: str = SCHEMA_VERSION
    invoice_id: str
    fraud_type: FraudType
    confidence: float | None = None  # null when checks 1-6 fired; certain by construction
    severity: Literal["low", "medium", "high"]
    evidence: list[Citation]
    recommended_action: Literal["none", "auto_flagged", "human_review"]


class ValidationResult(BaseModel):
    gate: str  # e.g. "post_classification"
    passed: bool
    reason: str
    retry_count: int
    checked_by_model: str


class FraudCaseState(BaseModel):
    schema_version: str = SCHEMA_VERSION
    invoice_id: str
    vendor_id: str
    po_reference: str
    raw_fields: dict
    job_results: list[CheckJobResult] = []
    draft_report: FraudReport | None = None
    validation_log: list[ValidationResult] = []
    conversation_history: list[dict] = []
    status: Literal[
        "awaiting_upload", "blocked", "planning", "acting",
        "classifying", "validating", "summarizing",
        "done", "escalated_human_review", "failed",
    ] = "planning"


class PreconditionsResult(BaseModel):
    injection_blocked: bool
    mode: Literal["audit", "follow_up", "blocked", "needs_upload"]
    invoice_id: str | None = None
    reason: str | None = None


class QAResponse(BaseModel):
    question: str
    answer: str
    citations: list[Citation]
    grounding_passed: bool
    caveat: str | None = None  # populated if grounding gate hit its cap
