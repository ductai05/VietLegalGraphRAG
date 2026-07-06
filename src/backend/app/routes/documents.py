from __future__ import annotations

from fastapi import APIRouter, Depends

from dependencies import RuntimeServices, get_runtime_services

router = APIRouter()


@router.get("/documents/{doc_id}/graph")
def document_graph(
    doc_id: str,
    runtime: RuntimeServices = Depends(get_runtime_services),
) -> dict:
    return runtime.graph_retriever.get_document_neighbors(doc_id).to_dict()


@router.get("/documents/{doc_id}/version-chain")
def version_chain(doc_id: str) -> dict:
    return {"doc_id": doc_id, "chain": []}
