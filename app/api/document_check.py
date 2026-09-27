from fastapi import APIRouter

from app.schemas.request import DocumentCheckRequest

router = APIRouter(tags=["documents"])


@router.post("/document-check")
async def document_check(request: DocumentCheckRequest) -> dict[str, int]:
    # Placeholder until the full flow (download -> classify -> extract) is wired in Stage 10.
    return {"received": len(request.documentUrls)}
