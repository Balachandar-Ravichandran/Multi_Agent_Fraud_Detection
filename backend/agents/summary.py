"""Produces the final user-facing message for every path (PRD Section 10).

Model: Claude Haiku, low effort. Mandatory final step for every path --
clean audit, flagged audit, escalated, Q&A answer, blocked, and
needs-upload all pass through here.

The fixed section order (facts before narrative) is templated
deterministically; only the "Narrative" paragraph is LLM-phrased, since the
facts above it are already fully determined by the report and need no
interpretation.

Not executed in this pass -- no live API call has been made against this
module yet.
"""
from __future__ import annotations

from core.events import emit
from core.llm import HAIKU_MODEL, call
from core.prompts import NARRATIVE_GENERATION
from core.schemas import CheckJobResult, FraudReport


def _format_checks(job_results: list[CheckJobResult]) -> str:
    return "\n".join(f"  {i}. {r.check_name} ... {r.result}" for i, r in enumerate(job_results, start=1))


def _format_evidence(report: FraudReport) -> str:
    if not report.evidence:
        return "  - (none)"
    return "\n".join(f"  - {c.excerpt}" for c in report.evidence)


def _format_recommended_action(report: FraudReport) -> str:
    confidence_text = f"{report.confidence:.2f}" if report.confidence is not None else "n/a (certain)"
    if report.recommended_action == "none":
        return "n/a"
    if report.recommended_action == "auto_flagged":
        return f"auto-flagged (confidence {confidence_text})"
    return f"human review (confidence {confidence_text})"


def generate(
    invoice_id: str,
    vendor_name: str,
    amount: float,
    report: FraudReport,
    job_results: list[CheckJobResult],
    run_id: str,
    path: str = "audit",
) -> str:
    narrative_context = (
        f"Invoice {invoice_id}, vendor {vendor_name}, amount ${amount:,.2f}.\n"
        f"Verdict: {report.fraud_type.value}, severity {report.severity}, "
        f"confidence {report.confidence if report.confidence is not None else 'n/a'}.\n"
        f"Evidence:\n{_format_evidence(report)}"
    )
    narrative = call(HAIKU_MODEL, "low", NARRATIVE_GENERATION, narrative_context).strip()

    message = (
        f"INVOICE {invoice_id} — {vendor_name} — ${amount:,.2f}\n"
        f"VERDICT: {report.fraud_type.value} | Severity: {report.severity} | "
        f"Confidence: {report.confidence if report.confidence is not None else 'n/a'}\n\n"
        f"Checks completed:\n{_format_checks(job_results)}\n\n"
        f"Evidence:\n{_format_evidence(report)}\n\n"
        f"Narrative: {narrative}\n\n"
        f"Recommended action: {_format_recommended_action(report)}"
    )

    emit("summary", "SUMMARY_GENERATED", run_id=run_id, invoice_id=invoice_id, path=path)
    return message


def generate_fixed_template(message: str, run_id: str, path: str) -> str:
    """For blocked/needs_upload paths (Section 9's Gate 6 is skipped for these
    fixed template messages -- there's no report/job_results to check faithfulness against).
    """
    emit("summary", "SUMMARY_GENERATED", run_id=run_id, path=path)
    return message
