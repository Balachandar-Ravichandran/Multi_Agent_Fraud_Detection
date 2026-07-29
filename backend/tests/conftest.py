from __future__ import annotations

from pathlib import Path

import pytest

from checks import (
    bank_account_match, delivery_inspection, duplicate_billing,
    price_po_contract, quantity_check, split_invoicing, vendor_po_validity,
)
from tools import storage_tool
from tools.invoice_pdf import extract_invoice_fields

BACKEND_DIR = Path(__file__).resolve().parent.parent
INVOICES_DIR = BACKEND_DIR / "data" / "golden_dataset" / "invoices"
LABELS_PATH = BACKEND_DIR / "data" / "golden_dataset" / "golden_dataset_labels.json"

# Fixed order per Section 7 -- not that order matters for correctness (all
# seven run in parallel in the real pipeline), but a stable order makes
# assertions/debugging easier.
CHECK_MODULES = [
    vendor_po_validity, bank_account_match, quantity_check,
    delivery_inspection, duplicate_billing, split_invoicing, price_po_contract,
]


@pytest.fixture
def conn():
    connection = storage_tool.get_connection()
    yield connection
    connection.close()


def build_invoice(invoice_id: str) -> dict:
    connection = storage_tool.get_connection()
    try:
        row = connection.execute(
            "SELECT * FROM invoice_ledger WHERE invoice_id = ?", (invoice_id,)
        ).fetchone()
    finally:
        connection.close()
    if row is None:
        raise KeyError(f"No invoice_ledger row for {invoice_id}")

    ledger = dict(row)
    pdf_fields = extract_invoice_fields(INVOICES_DIR / f"{invoice_id}.pdf")
    return {**ledger, **pdf_fields}


def run_all_checks(connection, invoice: dict) -> list:
    return [module.run(connection, invoice) for module in CHECK_MODULES]
