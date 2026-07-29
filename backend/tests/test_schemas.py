from core.schemas import CheckJobResult, Citation, FraudReport, FraudType


def test_fraud_report_roundtrip():
    report = FraudReport(
        invoice_id="INV-2024-0842",
        fraud_type=FraudType.PRICE_INFLATION,
        confidence=0.82,
        severity="medium",
        evidence=[Citation(source_type="contract", source_id="apex_steel_contract::2", excerpt="ceiling $38.00")],
        recommended_action="human_review",
    )
    assert report.fraud_type == FraudType.PRICE_INFLATION
    assert report.model_dump()["schema_version"] == "3.0"


def test_check_job_result_defaults():
    result = CheckJobResult(check_name="vendor_po_validity", result="CLEAN")
    assert result.fraud_type is None
    assert result.citations == []
