from agents.classifier import classify, compute_confidence
from core.schemas import CheckJobResult, FraudType


def test_all_clean_gives_clean_report():
    results = [CheckJobResult(check_name=name, result="CLEAN") for name in [
        "vendor_po_validity", "bank_account_match", "quantity_check",
        "delivery_inspection", "duplicate_billing", "split_invoicing", "price_po_contract",
    ]]
    report = classify("INV-2024-1001", results)
    assert report.fraud_type == FraudType.CLEAN
    assert report.confidence is None
    assert report.recommended_action == "none"


def test_check_1_to_6_anomaly_is_certain_auto_flag():
    results = [
        CheckJobResult(check_name="bank_account_match", result="ANOMALY", fraud_type=FraudType.ALTERED_BANK_DETAILS),
        CheckJobResult(check_name="vendor_po_validity", result="CLEAN"),
    ]
    report = classify("INV-2024-6001", results)
    assert report.fraud_type == FraudType.ALTERED_BANK_DETAILS
    assert report.confidence is None
    assert report.severity == "high"
    assert report.recommended_action == "auto_flagged"


def test_check_7_alone_uses_confidence_formula():
    results = [
        CheckJobResult(
            check_name="price_po_contract", result="ANOMALY",
            fraud_type=FraudType.PRICE_INFLATION, rule_certainty=0.9,
        ),
    ]
    report = classify("INV-2024-0842", results, retrieval_confidence=0.7)
    assert report.confidence == compute_confidence(0.9, 0.7)
    assert report.confidence == 0.82
    assert report.recommended_action == "human_review"  # 0.82 < 0.85


def test_multiple_anomalies_highest_severity_wins():
    results = [
        CheckJobResult(check_name="quantity_check", result="ANOMALY", fraud_type=FraudType.QUANTITY_MISMATCH),
        CheckJobResult(check_name="bank_account_match", result="ANOMALY", fraud_type=FraudType.ALTERED_BANK_DETAILS),
    ]
    report = classify("INV-2024-9999", results)
    assert report.fraud_type == FraudType.ALTERED_BANK_DETAILS
    assert report.confidence is None  # checks 1-6 fired -> certain, even though two fired


def test_confidence_at_or_above_085_auto_flags():
    results = [CheckJobResult(check_name="price_po_contract", result="ANOMALY", fraud_type=FraudType.PRICE_INFLATION, rule_certainty=1.0)]
    report = classify("INV-2024-2002", results, retrieval_confidence=1.0)
    assert report.confidence == 1.0
    assert report.recommended_action == "auto_flagged"
