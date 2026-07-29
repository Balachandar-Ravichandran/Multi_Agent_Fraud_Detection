from tools import rag_tool


def test_search_returns_pricing_schedule_top_match():
    results = rag_tool.search_contract_clauses(
        "Apex Steel Grade-A Steel Brackets unit price ceiling", vendor_id="VEND-1001", top_k=3,
    )
    assert results[0]["metadata"]["section_title"] == "Pricing Schedule"
    assert results[0]["similarity"] >= 0.55  # Section 9 Gate 2 threshold


def test_search_scoped_to_vendor():
    results = rag_tool.search_contract_clauses("unit price ceiling", vendor_id="VEND-1002", top_k=5)
    assert all(r["metadata"]["vendor_id"] == "VEND-1002" for r in results)


def test_fetch_by_section_title_deterministic():
    results = rag_tool.fetch_by_section_title("Pricing Schedule", vendor_id="VEND-1003")
    assert len(results) == 1
    assert "Control Module" in results[0]["document"]
