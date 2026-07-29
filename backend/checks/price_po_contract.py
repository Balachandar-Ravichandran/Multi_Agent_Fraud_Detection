"""Check 7: price/PO/contract check (PRD Section 7). Tools: RAG then Storage.

(a) does the invoice's unit price equal the PO's unit_price_approved?
(b) does whichever of those two prices applies exceed the contract ceiling
    (plus any COLA the contract's own text permits)?

Kept as one job with an if/else so the two outcomes are mutually exclusive:
- prices match, but that shared price itself exceeds the ceiling ->
  PO_EXCEEDS_CONTRACT_CEILING (the PO, not the vendor, is at fault).
- prices don't match and the invoice's billed price exceeds the ceiling ->
  PRICE_INFLATION.

Decision Point 2 (Section 7): the fraud judgment itself lives in this
if/else, not in a Validator gate.
"""
from __future__ import annotations

import re
import sqlite3

from checks._events import emit_job_result, emit_job_started
from core.events import emit
from core.schemas import Citation, CheckJobResult, FraudType
from tools import rag_tool, storage_tool

CHECK_NAME = "price_po_contract"

# Section 9 Gate 2's relevance threshold.
GATE2_SIMILARITY_THRESHOLD = 0.55

PRICE_ROW_PATTERN = re.compile(r"\|\s*([^|]+?)\s*\|\s*\$([\d,]+\.\d+)\s*per unit\s*\|")
COLA_PATTERN = re.compile(r"up to (\d+(?:\.\d+)?)%.*?cost-of-living", re.IGNORECASE | re.DOTALL)


def retrieve_clause(
    vendor_id: str, vendor_name: str, item_description: str, attempt: int = 1, run_id: str | None = None,
) -> dict:
    """One retrieval attempt for the item's pricing clause (Section 9 Gate 2's ladder).

    attempt 1: semantic search, top_k=3, query = vendor + item description.
    attempt 2: semantic search, top_k=5, query = the exact line-item text.
    attempt 3: deterministic metadata filter, section_title == "Pricing Schedule".

    Emits Section 11.4's retrieval events itself (not agents/validator.py --
    see that module's docstring for why Gate 2 is the one exception).
    """
    if run_id is not None:
        emit("retrieval", "RETRIEVAL_STARTED", run_id=run_id, vendor_id=vendor_id, item=item_description, attempt=attempt)
        if attempt > 1:
            strategy = {2: "widen_top_k_exact_line_item", 3: "deterministic_section_title_filter"}[attempt]
            emit("retrieval", "RETRY_QUERY", run_id=run_id, attempt=attempt, strategy=strategy)

    if attempt == 1:
        results = rag_tool.search_contract_clauses(
            f"{vendor_name} {item_description} unit price ceiling", vendor_id=vendor_id, top_k=3,
        )
    elif attempt == 2:
        results = rag_tool.search_contract_clauses(item_description, vendor_id=vendor_id, top_k=5)
    elif attempt == 3:
        results = rag_tool.fetch_by_section_title("Pricing Schedule", vendor_id=vendor_id)
    else:
        raise ValueError(f"attempt must be 1, 2, or 3, got {attempt}")

    if not results:
        clause = {"found": False, "text": "", "similarity": 0.0, "source_id": None}
    else:
        top = results[0]
        clause = {
            "found": True,
            "text": top["document"],
            "similarity": top.get("similarity", 1.0),  # attempt 3 has no ranking; treat as certain
            "source_id": top["id"],
        }

    if run_id is not None:
        passed = clause["found"] and clause["similarity"] >= GATE2_SIMILARITY_THRESHOLD
        emit(
            "retrieval", "RETRIEVAL_SUCCEEDED" if passed else "RETRIEVAL_LOW_CONFIDENCE",
            run_id=run_id, attempt=attempt, similarity=clause["similarity"],
        )

    return clause


def extract_ceiling(clause_text: str, item_description: str) -> float | None:
    for name, price in PRICE_ROW_PATTERN.findall(clause_text):
        if name.strip().lower() == item_description.strip().lower():
            return float(price.replace(",", ""))
    return None


def extract_cola_allowance(clause_text: str) -> float:
    """COLA % from the clause's own text -- 0.0 if it states none applies."""
    match = COLA_PATTERN.search(clause_text)
    return float(match.group(1)) / 100 if match else 0.0


def run(conn: sqlite3.Connection, invoice: dict, run_id: str | None = None) -> CheckJobResult:
    if run_id is not None:
        emit_job_started(CHECK_NAME, invoice["invoice_id"], run_id)

    vendor = storage_tool.lookup_vendor(conn, invoice["vendor_id"])
    po = storage_tool.lookup_po(conn, invoice["po_reference"])
    invoice_price = invoice["unit_price_billed"]
    po_price = po["unit_price_approved"] if po else None
    vendor_name = vendor["name"] if vendor else invoice["vendor_id"]

    clause = retrieve_clause(invoice["vendor_id"], vendor_name, invoice["line_item_description"], attempt=1, run_id=run_id)
    if not clause["found"] or clause["similarity"] < GATE2_SIMILARITY_THRESHOLD:
        # The full retry ladder (attempt 2 in between, gated by Validator
        # judgment) is Section 9's Gate 2 loop -- owned by the
        # orchestrator/validator. Jump straight to the deterministic
        # attempt 3 so this check still resolves today without that loop.
        clause = retrieve_clause(invoice["vendor_id"], vendor_name, invoice["line_item_description"], attempt=3, run_id=run_id)

    citations = [Citation(
        source_type="ledger", source_id=invoice["invoice_id"],
        excerpt=f"Invoice bills {invoice['line_item_description']} at unit_price={invoice_price}",
    )]
    if clause["found"] and clause["source_id"]:
        citations.append(Citation(
            source_type="contract", source_id=clause["source_id"], excerpt=clause["text"][:300],
        ))
    if po is not None:
        citations.append(Citation(
            source_type="po", source_id=po["po_number"], excerpt=f"unit_price_approved={po_price}",
        ))

    if not clause["found"]:
        # Only reachable if even the deterministic fallback finds nothing --
        # the clause is genuinely missing from the corpus (Section 9).
        result = CheckJobResult(check_name=CHECK_NAME, result="NOT_APPLICABLE", citations=citations)
    else:
        ceiling = extract_ceiling(clause["text"], invoice["line_item_description"])
        if ceiling is None:
            result = CheckJobResult(check_name=CHECK_NAME, result="NOT_APPLICABLE", citations=citations)
        else:
            cola = extract_cola_allowance(clause["text"])
            ceiling_with_cola = ceiling * (1 + cola)

            price_matches_po = po_price is not None and invoice_price == po_price
            applicable_price = po_price if price_matches_po else invoice_price

            if applicable_price <= ceiling_with_cola:
                result = CheckJobResult(check_name=CHECK_NAME, result="CLEAN", citations=citations)
            else:
                overage_ratio = (applicable_price - ceiling_with_cola) / ceiling_with_cola
                # Section 8: "near 1.0 when well past the ceiling+COLA line,
                # drops toward 0.7 the closer to that line." Linear from 0.7
                # at the line to 1.0 at >=20% past it -- a defensible curve;
                # the PRD gives no exact formula.
                rule_certainty = min(1.0, 0.7 + (overage_ratio / 0.20) * 0.3)
                fraud_type = FraudType.PO_EXCEEDS_CONTRACT_CEILING if price_matches_po else FraudType.PRICE_INFLATION

                result = CheckJobResult(
                    check_name=CHECK_NAME, result="ANOMALY", fraud_type=fraud_type,
                    magnitude=round(overage_ratio, 4), rule_certainty=round(rule_certainty, 4),
                    citations=citations,
                )

    if run_id is not None:
        emit_job_result(result, invoice["invoice_id"], run_id)
    return result
