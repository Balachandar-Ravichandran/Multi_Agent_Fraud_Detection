"""Full sequential run over all 20 golden-set invoices (PRD Section 17, Phase 4).

Produces:
- backend/logs/run_golden_set_eval.jsonl -- one continuous event trace across
  all 20 invoices (Section 20's /logs deliverable).
- backend/evaluation/results.json -- per-invoice predictions, the 9x9
  confusion matrix, precision/recall per fraud type, the citation-validity
  rate, and check 7's retrieval context precision/recall (Section 19's
  metrics).

Bypasses Preconditions' chat-based mode detection (each invoice's mode is
already known here) by calling orchestrator.graph.run_audit_pipeline()
directly, same as the smoke test. Real chat turns go through
build_graph()'s compiled app instead (see app/main.py).

Run: backend/.venv/python.exe eval/run_golden_set.py
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))  # run as a plain script, not `python -m` -- backend/ isn't on sys.path otherwise

from orchestrator.graph import run_audit_pipeline  # noqa: E402
from tools import rag_tool, storage_tool  # noqa: E402
from tools.invoice_pdf import extract_invoice_fields  # noqa: E402
GOLDEN_DIR = BACKEND_DIR / "data" / "golden_dataset"
LABELS_PATH = GOLDEN_DIR / "golden_dataset_labels.json"
EVAL_DIR = BACKEND_DIR / "evaluation"

RUN_ID = "golden_set_eval"

# All 9 label classes (Section 18).
FRAUD_TYPES = [
    "CLEAN", "PRICE_INFLATION", "QUANTITY_MISMATCH", "PHANTOM_VENDOR",
    "NON_DELIVERY", "ALTERED_BANK_DETAILS", "DUPLICATE_BILLING",
    "SPLIT_INVOICING", "PO_EXCEEDS_CONTRACT_CEILING",
]

# Vendor -> contract document stem, for check 7's context-precision check.
VENDOR_CONTRACT_STEM = {
    "VEND-1001": "apex_steel_contract",
    "VEND-1002": "boltcraft_contract",
    "VEND-1003": "meridian_contract",
}


def build_invoice(invoice_id: str) -> dict:
    conn = storage_tool.get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM invoice_ledger WHERE invoice_id = ?", (invoice_id,),
        ).fetchone()
    finally:
        conn.close()
    ledger = dict(row) if row else {}
    pdf_fields = extract_invoice_fields(GOLDEN_DIR / "invoices" / f"{invoice_id}.pdf")
    return {**ledger, **pdf_fields}


def verify_citation(citation: dict) -> bool:
    """Citation-validity check (Section 19): is the cited fact actually
    true against the record/collection it claims to come from?

    Most citations assert a record exists and cite its content -- valid
    when that record is found. But checks 1 and 4 also cite the confirmed
    *absence* of a record as the evidence itself (e.g. PHANTOM_VENDOR's "No
    vendor_master record found for this vendor_id"); those are valid
    precisely when that absence is confirmed -- checking "does source_id
    exist" for those would invalidate genuine evidence, not catch a
    fabrication. Matched by substring, not position, since the classifier
    prepends a "[secondary finding: ...]" tag when this citation isn't the
    report's primary finding (Section 8).
    """
    source_type, source_id, excerpt = citation["source_type"], citation["source_id"], citation["excerpt"]
    ABSENCE_PHRASES = (
        "No vendor_master record found",
        "No purchase_orders record found",
        "No delivery record on file",
    )
    asserts_absence = any(phrase in excerpt for phrase in ABSENCE_PHRASES)

    if source_type == "contract":
        try:
            got = rag_tool.get_collection().get(ids=[source_id])
            exists = len(got["ids"]) > 0
        except Exception:
            exists = False
        return (not exists) if asserts_absence else exists

    conn = storage_tool.get_connection()
    try:
        table_and_key = {
            "vendor_master": ("vendor_master", "vendor_id"),
            "po": ("purchase_orders", "po_number"),
            "delivery": ("deliveries", "po_number"),
            "ledger": ("invoice_ledger", "invoice_id"),
        }.get(source_type)
        if table_and_key is None:
            return False
        table, key = table_and_key
        exists = conn.execute(f"SELECT 1 FROM {table} WHERE {key} = ?", (source_id,)).fetchone() is not None
        return (not exists) if asserts_absence else exists
    finally:
        conn.close()


def context_precision_recall(job_results, invoice: dict) -> tuple[float, float] | tuple[None, None]:
    """Check 7's RAG correctness (Section 19): with a 4-document corpus,
    verified exactly rather than estimated. Precision: did the retrieved
    clause belong to the invoice's own vendor's Pricing Schedule? Recall:
    since the corpus is small and exhaustive (the right clause always
    exists), recall collapses to whether that clause was the one found.
    """
    if invoice["vendor_id"] not in VENDOR_CONTRACT_STEM:
        # No real contract exists for this vendor (e.g. PHANTOM_VENDOR cases)
        # -- there is no correct clause to retrieve, so this invoice can't
        # score a retrieval failure or success. Excluded, not counted as 0.
        return None, None

    check7 = next((r for r in job_results if r.check_name == "price_po_contract"), None)
    if check7 is None:
        return None, None

    contract_citations = [c for c in check7.citations if c.source_type == "contract"]
    if not contract_citations:
        return 0.0, 0.0

    citation = contract_citations[0]
    doc_stem = citation.source_id.split("::")[0]
    correct_doc = doc_stem == VENDOR_CONTRACT_STEM.get(invoice["vendor_id"])
    correct_section = "Pricing Schedule" in citation.excerpt
    score = 1.0 if (correct_doc and correct_section) else 0.0
    return score, score


def main() -> None:
    labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))

    confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_invoice_results = []
    citation_checks: list[bool] = []
    context_scores: list[tuple[float, float]] = []

    for label in labels:
        invoice_id = label["invoice_id"]
        invoice = build_invoice(invoice_id)

        state = run_audit_pipeline(
            invoice_id=invoice_id, vendor_id=invoice["vendor_id"], po_reference=invoice["po_reference"],
            raw_fields=invoice, run_id=RUN_ID,
        )
        report = state["draft_report"]
        predicted = report.fraud_type.value
        expected = label["expected_fraud_type"]
        confusion[expected][predicted] += 1

        citation_checks.extend(verify_citation(c.model_dump()) for c in report.evidence)

        precision, recall = context_precision_recall(state["job_results"], invoice)
        if precision is not None:
            context_scores.append((precision, recall))

        per_invoice_results.append({
            "invoice_id": invoice_id,
            "expected": expected,
            "predicted": predicted,
            "correct": expected == predicted,
            "confidence": report.confidence,
            "recommended_action": report.recommended_action,
            "gate_log": [[v.gate, v.passed] for v in state["validation_log"]],
        })

        print(f"{invoice_id}: expected={expected} predicted={predicted} "
              f"{'OK' if expected == predicted else 'MISMATCH'}")

    per_type_metrics = {}
    for ft in FRAUD_TYPES:
        tp = confusion[ft][ft]
        fn = sum(confusion[ft][p] for p in FRAUD_TYPES if p != ft)
        fp = sum(confusion[e][ft] for e in FRAUD_TYPES if e != ft)
        per_type_metrics[ft] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": tp / (tp + fp) if (tp + fp) > 0 else None,
            "recall": tp / (tp + fn) if (tp + fn) > 0 else None,
        }

    citation_validity_rate = sum(citation_checks) / len(citation_checks) if citation_checks else None
    avg_precision = sum(p for p, _ in context_scores) / len(context_scores) if context_scores else None
    avg_recall = sum(r for _, r in context_scores) / len(context_scores) if context_scores else None

    results = {
        "run_id": RUN_ID,
        "total_invoices": len(labels),
        "correct": sum(1 for r in per_invoice_results if r["correct"]),
        "confusion_matrix": {ft: dict(confusion[ft]) for ft in FRAUD_TYPES},
        "per_fraud_type": per_type_metrics,
        "citation_validity_rate": citation_validity_rate,
        "citations_checked": len(citation_checks),
        "check7_context_precision": avg_precision,
        "check7_context_recall": avg_recall,
        "per_invoice": per_invoice_results,
    }

    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    (EVAL_DIR / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")

    print()
    print(f"{results['correct']}/{results['total_invoices']} correct")
    print(f"Citation validity rate: {citation_validity_rate} ({len(citation_checks)} citations checked)")
    print(f"Check 7 context precision/recall: {avg_precision} / {avg_recall}")
    print()
    for ft, m in per_type_metrics.items():
        print(f"  {ft:30s} precision={m['precision']} recall={m['recall']} (tp={m['tp']}, fp={m['fp']}, fn={m['fn']})")
    print()
    print(f"Full results written to {EVAL_DIR / 'results.json'}")
    print(f"Event log written to {BACKEND_DIR / 'logs' / f'run_{RUN_ID}.jsonl'}")


if __name__ == "__main__":
    main()
