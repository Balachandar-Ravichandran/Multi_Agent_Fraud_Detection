from tools import storage_tool


def test_lookup_vendor_found(conn):
    vendor = storage_tool.lookup_vendor(conn, "VEND-1001")
    assert vendor["name"] == "Apex Steel Components Ltd."
    assert vendor["status"] == "Approved"


def test_lookup_vendor_missing(conn):
    assert storage_tool.lookup_vendor(conn, "VEND-9999") is None


def test_lookup_po_found(conn):
    po = storage_tool.lookup_po(conn, "PO-2024-1101")
    assert po["vendor_id"] == "VEND-1001"
    assert po["unit_price_approved"] == 38.0


def test_lookup_po_missing_phantom(conn):
    assert storage_tool.lookup_po(conn, "PO-2024-9001") is None


def test_lookup_delivery_missing_for_non_delivery_case(conn):
    # Golden set 5001: PO exists and is approved, but no delivery record.
    assert storage_tool.lookup_delivery(conn, "PO-2024-1304") is None


def test_lookup_ledger_matches_finds_earlier_duplicate(conn):
    matches = storage_tool.lookup_ledger_matches(
        conn, "VEND-1002", "PO-2024-1204", 12900.0, "INV-2024-7002", "2024-03-29",
    )
    assert len(matches) == 1
    assert matches[0]["invoice_id"] == "INV-2024-7001"


def test_lookup_ledger_matches_original_has_no_earlier_match(conn):
    # INV-2024-7001 was received before 7002 existed -- it must not match itself-in-the-future.
    matches = storage_tool.lookup_ledger_matches(
        conn, "VEND-1002", "PO-2024-1204", 12900.0, "INV-2024-7001", "2024-03-25",
    )
    assert matches == []


def test_lookup_vendor_invoices_in_window(conn):
    others = storage_tool.lookup_vendor_invoices_in_window(conn, "VEND-1001", "2024-04-01", 7, "INV-2024-8001")
    ids = {o["invoice_id"] for o in others}
    assert "INV-2024-8002" in ids


def test_get_heuristic(conn):
    assert storage_tool.get_heuristic(conn, "split_invoicing_threshold") == 10000
    assert storage_tool.get_heuristic(conn, "confidence_auto_flag") == 0.85
