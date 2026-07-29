"""One-time loader: JSON reference data -> SQLite, contracts/policy markdown -> Chroma.

Implements PRD Section 4.4 (Startup Sequence, steps 1 and 4) and Section 13
(Database Schemas). Safe to re-run: reference tables use INSERT OR REPLACE,
and the Chroma collection is cleared before each reload.

Usage: python data/ingest.py
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import chromadb

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent
REFERENCE_DIR = DATA_DIR / "reference"
CONTRACTS_DIR = DATA_DIR / "contracts_policy"
DB_PATH = BACKEND_DIR / "fraud_system.db"
CHROMA_PATH = BACKEND_DIR / "chroma_db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendor_master (
    vendor_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    status TEXT NOT NULL,
    bank_account_last4 TEXT NOT NULL,
    contract_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL REFERENCES vendor_master(vendor_id),
    item_description TEXT NOT NULL,
    quantity_approved INTEGER NOT NULL,
    unit_price_approved REAL NOT NULL,
    approver TEXT,
    po_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deliveries (
    po_number TEXT PRIMARY KEY REFERENCES purchase_orders(po_number),
    quantity_delivered INTEGER NOT NULL,
    delivery_date TEXT NOT NULL,
    signed_by TEXT,
    inspection_confirmed BOOLEAN
);

CREATE TABLE IF NOT EXISTS invoice_ledger (
    invoice_id TEXT PRIMARY KEY,
    vendor_id TEXT NOT NULL,
    po_reference TEXT NOT NULL,
    amount REAL NOT NULL,
    date_received TEXT NOT NULL,
    status TEXT NOT NULL,
    fraud_type TEXT,
    confidence REAL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS episodic_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    invoice_id TEXT NOT NULL,
    fraud_type TEXT NOT NULL,
    confidence REAL,
    human_review_required BOOLEAN NOT NULL,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS procedural_heuristics (
    name TEXT PRIMARY KEY,
    threshold_value REAL,
    description TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);
"""

# Seed values for Section 4.4 step 2. Sources: Section 9 (Gate 2 threshold),
# Section 7 check 6 and Section 18's procurement_policy.md Section 3
# (split-invoicing window/threshold), Section 9 Decision Point 4 (confidence bands).
SEED_HEURISTICS = [
    ("confidence_auto_flag", 0.85, "Check-7-only confidence at/above this value auto-flags without human review (Decision Point 4).", 1),
    ("confidence_human_review_floor", 0.60, "Check-7-only confidence below this value always routes to human review, never auto-clears (Decision Point 4).", 1),
    ("split_invoicing_window_days", 7, "Window, in days, within which different-PO invoices from the same vendor are summed for the split-invoicing check.", 1),
    ("split_invoicing_threshold", 10000, "Combined value across the window above which split invoicing is flagged (Section 7, check 6).", 1),
    ("gate2_similarity_threshold", 0.55, "Minimum Chroma similarity score for retrieved evidence to pass Gate 2 (Section 9).", 1),
]

SECTION_PATTERN = re.compile(r"^## (\d+)\.\s*(.+)$", re.MULTILINE)
CONTRACT_ID_PATTERN = re.compile(r"\*\*Contract ID:\*\*\s*(\S+)")
VENDOR_ID_PATTERN = re.compile(r"\*\*Approved Vendor ID:\*\*\s*(\S+)")


def load_reference_data(conn: sqlite3.Connection) -> dict[str, int]:
    conn.executescript(SCHEMA)
    counts: dict[str, int] = {}

    vendors = json.loads((REFERENCE_DIR / "vendor_master.json").read_text(encoding="utf-8"))
    conn.executemany(
        "INSERT OR REPLACE INTO vendor_master (vendor_id, name, status, bank_account_last4, contract_id) "
        "VALUES (:vendor_id, :name, :status, :bank_account_last4, :contract_id)",
        vendors,
    )
    counts["vendor_master"] = len(vendors)

    pos = json.loads((REFERENCE_DIR / "purchase_orders.json").read_text(encoding="utf-8"))
    for po in pos:
        po.setdefault("approver", None)
    conn.executemany(
        "INSERT OR REPLACE INTO purchase_orders "
        "(po_number, vendor_id, item_description, quantity_approved, unit_price_approved, approver, po_date) "
        "VALUES (:po_number, :vendor_id, :item_description, :quantity_approved, :unit_price_approved, :approver, :po_date)",
        pos,
    )
    counts["purchase_orders"] = len(pos)

    deliveries = json.loads((REFERENCE_DIR / "deliveries.json").read_text(encoding="utf-8"))
    for d in deliveries:
        d.setdefault("signed_by", None)
        d.setdefault("inspection_confirmed", None)
    conn.executemany(
        "INSERT OR REPLACE INTO deliveries "
        "(po_number, quantity_delivered, delivery_date, signed_by, inspection_confirmed) "
        "VALUES (:po_number, :quantity_delivered, :delivery_date, :signed_by, :inspection_confirmed)",
        deliveries,
    )
    counts["deliveries"] = len(deliveries)

    invoices = json.loads((REFERENCE_DIR / "invoice_tracking.json").read_text(encoding="utf-8"))
    recorded_at = datetime.now(timezone.utc).isoformat()
    for inv in invoices:
        inv.setdefault("fraud_type", None)
        inv.setdefault("confidence", None)
        inv["recorded_at"] = recorded_at
    conn.executemany(
        "INSERT OR REPLACE INTO invoice_ledger "
        "(invoice_id, vendor_id, po_reference, amount, date_received, status, fraud_type, confidence, recorded_at) "
        "VALUES (:invoice_id, :vendor_id, :po_reference, :amount, :date_received, :status, :fraud_type, :confidence, :recorded_at)",
        invoices,
    )
    counts["invoice_ledger"] = len(invoices)

    conn.executemany(
        "INSERT OR REPLACE INTO procedural_heuristics (name, threshold_value, description, version) VALUES (?, ?, ?, ?)",
        SEED_HEURISTICS,
    )
    counts["procedural_heuristics"] = len(SEED_HEURISTICS)

    conn.commit()
    return counts


def chunk_markdown(text: str) -> list[dict]:
    """One chunk per '## N. Title' clause section (Section 13's chunking design)."""
    matches = list(SECTION_PATTERN.finditer(text))
    sections = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append({
            "section_number": m.group(1),
            "section_title": m.group(2).strip(),
            "text": text[m.start():end].strip(),
        })
    return sections


def load_contracts_policy(client: "chromadb.ClientAPI"):
    # Cosine space so similarity = 1 - distance is a well-defined [-1, 1]
    # score -- Section 9 Gate 2's >=0.55 threshold and Section 8's
    # retrieval_confidence both assume a normalized similarity score.
    collection = client.get_or_create_collection(
        "contracts_policy", metadata={"hnsw:space": "cosine"}
    )
    existing = collection.get()
    if existing["ids"]:
        collection.delete(ids=existing["ids"])

    ids, documents, metadatas = [], [], []
    for path in sorted(CONTRACTS_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        doc_type = "policy" if path.stem == "procurement_policy" else "contract"
        contract_id_match = CONTRACT_ID_PATTERN.search(text)
        vendor_id_match = VENDOR_ID_PATTERN.search(text)
        contract_id = contract_id_match.group(1) if contract_id_match else ""
        vendor_id = vendor_id_match.group(1) if vendor_id_match else ""

        for section in chunk_markdown(text):
            ids.append(f"{path.stem}::{section['section_number']}")
            documents.append(section["text"])
            metadatas.append({
                "vendor_id": vendor_id,
                "contract_id": contract_id,
                "section_number": section["section_number"],
                "section_title": section["section_title"],
                "doc_type": doc_type,
                "source_file": path.name,
            })

    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    return collection, len(ids)


def warm_collection(collection) -> None:
    """Section 4.4 step 4: surface Chroma connection errors at startup, not on the first real request."""
    collection.query(query_texts=["warm up"], n_results=1)


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        sqlite_counts = load_reference_data(conn)
    finally:
        conn.close()

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    collection, chunk_count = load_contracts_policy(client)
    warm_collection(collection)

    print(f"SQLite ({DB_PATH}):")
    for table, count in sqlite_counts.items():
        print(f"  {table}: {count} rows")
    print(f"Chroma ({CHROMA_PATH}), collection 'contracts_policy': {chunk_count} chunks")


if __name__ == "__main__":
    main()
