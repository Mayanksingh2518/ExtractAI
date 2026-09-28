from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.security import authorize
from app.schemas.request import DocumentCheckRequest
from app.schemas.response import OwnerResult
from app.services.document_processor import DocumentProcessor, ModelUnavailableError

router = APIRouter(tags=["documents"])


def get_processor(request: Request) -> DocumentProcessor:
    """The processor created at startup (app/main.py). Tests replace it via app.dependency_overrides."""
    return request.app.state.processor


@router.post(
    "/document-check",
    response_model=list[OwnerResult],
    dependencies=[Depends(authorize)],
    responses={
        401: {"description": "Missing or invalid X-API-Key (only when the server sets API_KEYS)."},
        429: {"description": "Rate limit reached; see the Retry-After header (seconds)."},
        503: {"description": "The document model (Ollama) is not available; nothing was downloaded."},
    },
)
async def document_check(
    request: DocumentCheckRequest,
    processor: DocumentProcessor = Depends(get_processor),
) -> list[OwnerResult]:
    """Download, classify and extract every document, grouped by owner. One bad document never fails the batch."""
    try:
        return await processor.process([str(url) for url in request.documentUrls])
    except ModelUnavailableError:
        raise HTTPException(status_code=503, detail="document model is not available, try again later") from None
