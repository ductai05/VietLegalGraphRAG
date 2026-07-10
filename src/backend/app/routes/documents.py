from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from dependencies import RuntimeServices, get_runtime_services
from config import get_settings
from schemas import OcrResponseModel, OcrPageModel  # noqa: F401 - used in type stubs

router = APIRouter()


@router.post("/documents/ocr", response_model=OcrResponseModel)
def ocr_upload(
    file: UploadFile = File(...),
    runtime: RuntimeServices = Depends(get_runtime_services),
) -> OcrResponseModel:
    settings = get_settings()

    # Provider check
    provider = settings.ocr_provider.strip().lower()
    if provider in {"", "none"}:
        raise HTTPException(
            status_code=422,
            detail="ocr.disabled",
        )
    if provider not in {"google"}:
        raise HTTPException(
            status_code=422,
            detail="ocr.unknown_provider",
        )

    # Read content
    content = file.file.read()

    # Empty file
    if not content:
        raise HTTPException(
            status_code=422,
            detail="ocr.empty_file",
        )

    # Size check
    max_bytes = settings.ocr_max_file_bytes
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail="ocr.file_too_large",
        )

    # MIME check
    mime = file.content_type or ""
    allowed = settings.ocr_allowed_mime_types
    if mime not in allowed:
        raise HTTPException(
            status_code=415,
            detail="ocr.unsupported_media_type",
        )
    if mime == "application/pdf":
        try:
            from pypdf import PdfReader

            page_count = len(PdfReader(io.BytesIO(content)).pages)
        except Exception:
            raise HTTPException(
                status_code=422,
                detail="ocr.invalid_pdf",
            )
        if page_count > settings.ocr_max_pdf_pages:
            raise HTTPException(
                status_code=422,
                detail="ocr.pdf_too_many_pages",
            )

    # Process
    try:
        result = runtime.ocr_service.process(content, mime)
    except ValueError as e:
        raise HTTPException(status_code=415, detail=str(e))
    except RuntimeError:
        raise HTTPException(status_code=502, detail="ocr.provider_error")
    except Exception:
        raise HTTPException(status_code=502, detail="ocr.processing_error")

    warnings: list[str] = []
    if not result.get("success", False):
        warnings.append("ocr.no_text_extracted")

    return OcrResponseModel(
        success=result.get("success", False),
        text=result.get("text", ""),
        pages=[OcrPageModel(**p) for p in result.get("pages", [])],
        provider=runtime.status.get("ocr", "unknown"),
        warnings=warnings,
    )


@router.get("/documents/{doc_id}/graph")
def document_graph(
    doc_id: str,
    runtime: RuntimeServices = Depends(get_runtime_services),
) -> dict:
    result = runtime.graph_retriever.get_document_neighbors(doc_id)
    return result.to_dict()


@router.get("/documents/{doc_id}/version-chain")
def version_chain(
    doc_id: str,
    runtime: RuntimeServices = Depends(get_runtime_services),
) -> dict:
    chain: list[dict[str, Any]] = []
    if getattr(runtime.graph_retriever, "enabled", True):
        try:
            chain = runtime.graph_retriever.get_version_chain(doc_id)
        except Exception:
            pass  # No secrets in errors
    return {"doc_id": doc_id, "chain": chain}
