"""Extracts structured fields from a golden-set invoice PDF.

Not a named Section 4.1 component -- the PRD's non-goals state invoices are
"clean, machine-readable PDFs" (no OCR needed), but some check-facing fields
(billed unit price, billed quantity, bank account on the invoice) only exist
on the PDF itself, never in the JSON reference data. This fills that gap
with plain regex over pypdf's extracted text; results feed FraudCaseState's
generic `raw_fields` dict (Section 12.2).
"""
from __future__ import annotations

import io
import re
from pathlib import Path

from pypdf import PdfReader

INVOICE_ID_PATTERN = re.compile(r"INVOICE\n(INV-\S+)")
PO_REFERENCE_PATTERN = re.compile(r"PO Reference\n(PO-\S+)")
INVOICE_DATE_PATTERN = re.compile(r"Invoice Date\n(\d{4}-\d{2}-\d{2})")
ACCOUNT_LAST4_PATTERN = re.compile(r"Account ending (\d+)")
LINE_ITEM_PATTERN = re.compile(
    r"Line Total\n(.+?)\n(\d+)\n\$([\d,]+\.\d+)\n\$([\d,]+\.\d+)\nTotal Due",
    re.DOTALL,
)
TOTAL_DUE_PATTERN = re.compile(r"Total Due\n\$([\d,]+\.\d+)")


def _to_float(amount_str: str) -> float:
    return float(amount_str.replace(",", ""))


def extract_invoice_fields(pdf_source: str | Path | bytes) -> dict:
    """`pdf_source` is a file path (golden-set fixtures) or raw PDF bytes
    (an uploaded file, e.g. from app/main.py's /api/v1/chat endpoint)."""
    stream = io.BytesIO(pdf_source) if isinstance(pdf_source, bytes) else str(pdf_source)
    text = PdfReader(stream).pages[0].extract_text()

    invoice_id_match = INVOICE_ID_PATTERN.search(text)
    po_reference_match = PO_REFERENCE_PATTERN.search(text)
    date_match = INVOICE_DATE_PATTERN.search(text)
    account_match = ACCOUNT_LAST4_PATTERN.search(text)
    line_item_match = LINE_ITEM_PATTERN.search(text)
    total_due_match = TOTAL_DUE_PATTERN.search(text)

    if not (invoice_id_match and po_reference_match and line_item_match):
        raise ValueError("Could not parse required fields from the invoice PDF")

    return {
        "invoice_id": invoice_id_match.group(1),
        "po_reference_on_invoice": po_reference_match.group(1),
        "invoice_date": date_match.group(1) if date_match else None,
        "bank_account_last4_on_invoice": account_match.group(1) if account_match else None,
        "line_item_description": line_item_match.group(1).strip(),
        "qty_billed": int(line_item_match.group(2)),
        "unit_price_billed": _to_float(line_item_match.group(3)),
        "line_total": _to_float(line_item_match.group(4)),
        "total_due": _to_float(total_due_match.group(1)) if total_due_match else None,
        "_raw_text": text,  # for the Preconditions Agent's document-channel injection check only
    }
