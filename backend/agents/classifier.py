"""Consolidates CheckJobResults into a draft FraudReport (PRD Section 8).

The confidence formula, "highest severity wins" consolidation, and the
certain-by-construction shortcut for checks 1-6 are fully specified,
deterministic rules -- no LLM call is needed to apply them correctly. (The
PRD's "Model: Claude Sonnet" note describes the agentic system a full
deployment would wrap this in for narrative phrasing; that phrasing is
Summary's job (Section 10), not Classifier's.)
"""
from __future__ import annotations

from core.events import emit
from core.schemas import CheckJobResult, Citation, FraudReport, FraudType

# Severity ranking for the rare multi-check-fire case (Section 8): "the
# highest-severity finding becomes fraud_type; others are appended to
# evidence with a note." The PRD does not define an explicit ranking; this
# one orders by direct financial/audit harm, most severe first.
#
# Invariant this relies on: price_po_contract (check 7) is ranked last, so
# "the primary finding is from checks 1-6" and "any of checks 1-6 fired" are
# equivalent -- which is what lets the single `check_1_to_6_fired` test below
# stand in for Section 8's "if checks 1-6 fired (with or without check 7
# also firing)" rule.
CHECK_SEVERITY_RANK = [
    "bank_account_match",    # ALTERED_BANK_DETAILS -- funds redirected to an attacker
    "vendor_po_validity",    # PHANTOM_VENDOR -- fabricated vendor/PO entirely
    "duplicate_billing",     # DUPLICATE_BILLING -- double payment
    "delivery_inspection",   # NON_DELIVERY -- paying for goods never received
    "split_invoicing",       # SPLIT_INVOICING -- control circumvention
    "price_po_contract",     # PRICE_INFLATION / PO_EXCEEDS_CONTRACT_CEILING -- overpayment
    "quantity_check",        # QUANTITY_MISMATCH -- overbilling quantity
]


def compute_confidence(rule_certainty: float, retrieval_confidence: float) -> float:
    """Section 8's formula. Only applies when check 7 is the finding that fired."""
    return round(0.6 * rule_certainty + 0.4 * retrieval_confidence, 4)


def _severity_for_confidence(confidence: float) -> str:
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.60:
        return "medium"
    return "low"


def classify(
    invoice_id: str,
    job_results: list[CheckJobResult],
    retrieval_confidence: float | None = None,
    run_id: str | None = None,
) -> FraudReport:
    """`retrieval_confidence` is Gate 2's output (Section 8) -- not yet wired
    up since agents/validator.py doesn't exist yet. Defaults to 0.5, Section
    8's own "Gate 2 exhausted its retries" fallback value, until it is.
    """
    anomalies = [r for r in job_results if r.result == "ANOMALY"]

    if not anomalies:
        report = FraudReport(
            invoice_id=invoice_id, fraud_type=FraudType.CLEAN, confidence=None,
            severity="low", evidence=[], recommended_action="none",
        )
    else:
        anomalies_sorted = sorted(
            anomalies,
            key=lambda r: CHECK_SEVERITY_RANK.index(r.check_name) if r.check_name in CHECK_SEVERITY_RANK else len(CHECK_SEVERITY_RANK),
        )
        primary = anomalies_sorted[0]
        others = anomalies_sorted[1:]

        evidence: list[Citation] = list(primary.citations)
        for other in others:
            for c in other.citations:
                evidence.append(Citation(
                    source_type=c.source_type, source_id=c.source_id,
                    excerpt=f"[secondary finding: {other.check_name} / {other.fraud_type}] {c.excerpt}",
                ))

        check_1_to_6_fired = primary.check_name != "price_po_contract"

        if check_1_to_6_fired:
            report = FraudReport(
                invoice_id=invoice_id, fraud_type=primary.fraud_type, confidence=None,
                severity="high", evidence=evidence, recommended_action="auto_flagged",
            )
        else:
            rule_certainty = primary.rule_certainty if primary.rule_certainty is not None else 0.7
            retrieval_conf = retrieval_confidence if retrieval_confidence is not None else 0.5
            confidence = compute_confidence(rule_certainty, retrieval_conf)
            report = FraudReport(
                invoice_id=invoice_id, fraud_type=primary.fraud_type, confidence=confidence,
                severity=_severity_for_confidence(confidence), evidence=evidence,
                recommended_action="auto_flagged" if confidence >= 0.85 else "human_review",
            )

    if run_id is not None:
        emit(
            "classification", "FRAUD_CLASSIFIED", run_id=run_id,
            invoice_id=invoice_id, fraud_type=report.fraud_type.value,
            confidence=report.confidence, recommended_action=report.recommended_action,
        )

    return report
