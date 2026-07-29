"""Chroma query wrapper (PRD Section 4.1) over the `contracts_policy` collection (Section 13).

The collection is created with cosine space (see data/ingest.py) so
`similarity = 1 - distance` is a well-defined score, matching Section 9
Gate 2's >=0.55 relevance threshold and Section 8's retrieval_confidence.
"""
from __future__ import annotations

from pathlib import Path

import chromadb

BACKEND_DIR = Path(__file__).resolve().parent.parent
CHROMA_PATH = BACKEND_DIR / "chroma_db"
COLLECTION_NAME = "contracts_policy"

_client: chromadb.ClientAPI | None = None


def get_collection():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    return _client.get_collection(COLLECTION_NAME)


def search_contract_clauses(
    query_text: str,
    vendor_id: str | None = None,
    top_k: int = 3,
) -> list[dict]:
    """Semantic search over contract/policy clauses, optionally scoped to a vendor.

    Returns [{id, document, metadata, similarity}, ...], best match first.
    Used for Gate 2 attempts 1 and 2 (Section 9) -- only top_k and query_text
    differ between those two attempts; the caller (checks/price_po_contract.py)
    owns that retry sequencing.
    """
    collection = get_collection()
    where = {"vendor_id": vendor_id} if vendor_id else None
    res = collection.query(query_texts=[query_text], n_results=top_k, where=where)

    results = []
    for id_, doc, meta, dist in zip(
        res["ids"][0], res["documents"][0], res["metadatas"][0], res["distances"][0]
    ):
        results.append({
            "id": id_,
            "document": doc,
            "metadata": meta,
            "similarity": 1 - dist,
        })
    return results


def fetch_by_section_title(section_title: str, vendor_id: str) -> list[dict]:
    """Deterministic metadata-filtered fetch -- Gate 2 attempt 3 (Section 9).

    Guaranteed correct given the corpus's known, consistent '## N. Title'
    header structure (see data/ingest.py's chunking), not a probabilistic
    retry. No similarity score: this bypasses ranking entirely.
    """
    collection = get_collection()
    res = collection.get(
        where={"$and": [{"vendor_id": vendor_id}, {"section_title": section_title}]}
    )
    return [
        {"id": id_, "document": doc, "metadata": meta}
        for id_, doc, meta in zip(res["ids"], res["documents"], res["metadatas"])
    ]
