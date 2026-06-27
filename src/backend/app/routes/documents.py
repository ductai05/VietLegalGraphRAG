from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()


@router.get("/documents/{doc_id}/graph")
def document_graph(doc_id: str) -> dict:
    return {
        "center": {"id": f"doc:{doc_id}", "label": "Document", "properties": {"doc_id": doc_id}},
        "nodes": [],
        "edges": [],
        "related_chunks": [],
        "query_intent": "general",
    }


@router.get("/documents/{doc_id}/version-chain")
def version_chain(doc_id: str) -> dict:
    return {"doc_id": doc_id, "chain": []}
