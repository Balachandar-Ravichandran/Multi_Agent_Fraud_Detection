"""SQLite query/write wrapper (PRD Section 4.1, Section 13's schema).

Every lookup returns a plain dict (or None / list of dicts), never a raw
cursor or sqlite3.Row, so callers (the seven checks) never touch SQL.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BACKEND_DIR / "fraud_system.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _row_or_none(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def lookup_vendor(conn: sqlite3.Connection, vendor_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM vendor_master WHERE vendor_id = ?", (vendor_id,)
    ).fetchone()
    return _row_or_none(row)


def lookup_po(conn: sqlite3.Connection, po_number: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM purchase_orders WHERE po_number = ?", (po_number,)
    ).fetchone()
    return _row_or_none(row)


def lookup_delivery(conn: sqlite3.Connection, po_number: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM deliveries WHERE po_number = ?", (po_number,)
    ).fetchone()
    return _row_or_none(row)


def lookup_ledger_matches(
    conn: sqlite3.Connection,
    vendor_id: str,
    po_reference: str,
    amount: float,
    exclude_invoice_id: str,
    received_before: str,
) -> list[dict]:
    """Earlier invoices sharing (vendor_id, po_reference, amount) -- Check 5, duplicate billing.

    Only matches with date_received strictly before `received_before` count:
    of a matching pair, the earlier one was legitimate at the time it was
    recorded, and the later one is the resubmission that's actually the
    duplicate (Section 18's 7001/7002 pair -- without this ordering, both
    invoices in the pair would symmetrically flag each other).
    """
    rows = conn.execute(
        "SELECT * FROM invoice_ledger "
        "WHERE vendor_id = ? AND po_reference = ? AND amount = ? AND invoice_id != ? AND date_received < ?",
        (vendor_id, po_reference, amount, exclude_invoice_id, received_before),
    ).fetchall()
    return [dict(r) for r in rows]


def lookup_vendor_invoices_in_window(
    conn: sqlite3.Connection,
    vendor_id: str,
    center_date: str,
    window_days: int,
    exclude_invoice_id: str,
) -> list[dict]:
    """Other invoices from the same vendor within +/- window_days of center_date -- Check 6, split invoicing.

    Filtering by *different* po_reference is the caller's job (Section 7,
    check 6): this only narrows by vendor and date window.
    """
    center = datetime.fromisoformat(center_date)
    rows = conn.execute(
        "SELECT * FROM invoice_ledger WHERE vendor_id = ? AND invoice_id != ?",
        (vendor_id, exclude_invoice_id),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        other_date = datetime.fromisoformat(d["date_received"])
        if abs((other_date - center).days) <= window_days:
            result.append(d)
    return result


def record_case_outcome(
    conn: sqlite3.Connection,
    invoice_id: str,
    vendor_id: str,
    po_reference: str,
    fraud_type: str,
    confidence: float | None,
    human_review_required: bool,
) -> None:
    """Update invoice_ledger and append an episodic_memory row for a finalized case."""
    now = datetime.now(timezone.utc).isoformat()
    status = "flagged" if fraud_type != "CLEAN" else "paid"
    conn.execute(
        "UPDATE invoice_ledger SET status = ?, fraud_type = ?, confidence = ?, "
        "vendor_id = ?, po_reference = ? WHERE invoice_id = ?",
        (status, fraud_type, confidence, vendor_id, po_reference, invoice_id),
    )
    conn.execute(
        "INSERT INTO episodic_memory (invoice_id, fraud_type, confidence, human_review_required, recorded_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (invoice_id, fraud_type, confidence, human_review_required, now),
    )
    conn.commit()


def flag_for_human_review(
    conn: sqlite3.Connection,
    invoice_id: str,
    vendor_id: str,
    po_reference: str,
    fraud_type: str,
    confidence: float | None,
) -> None:
    record_case_outcome(
        conn, invoice_id, vendor_id, po_reference, fraud_type, confidence,
        human_review_required=True,
    )


def get_heuristic(conn: sqlite3.Connection, name: str) -> float:
    row = conn.execute(
        "SELECT threshold_value FROM procedural_heuristics WHERE name = ?", (name,)
    ).fetchone()
    if row is None:
        raise KeyError(f"No procedural_heuristics row named '{name}'")
    return row["threshold_value"]
