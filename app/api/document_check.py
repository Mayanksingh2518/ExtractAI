from fastapi import APIRouter, Depends, Request

from app.schemas.request import DocumentCheckRequest
from app.schemas.response import OwnerResult
from app.services.document_processor import DocumentProcessor

router = APIRouter(tags=["documents"])


def get_processor(request: Request) -> DocumentProcessor:
    """The processor created at startup (app/main.py). Tests replace it via app.dependency_overrides."""
    return request.app.state.processor


@router.post("/document-check", response_model=list[OwnerResult])
async def document_check(
    request: DocumentCheckRequest,
    processor: DocumentProcessor = Depends(get_processor),
) -> list[OwnerResult]:
    """Download, classify and extract every document, grouped by owner. One bad document never fails the batch."""
    return await processor.process([str(url) for url in request.documentUrls])
