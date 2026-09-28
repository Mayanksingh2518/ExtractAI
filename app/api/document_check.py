from fastapi import APIRouter, Depends, HTTPException, Request
from starlette.datastructures import FormData, UploadFile  # request.form() returns Starlette's UploadFile

from app.api.security import authorize
from app.config import get_settings
from app.schemas.request import MAX_DOCUMENTS, DocumentCheckRequest
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


UPLOAD_FIELD = "files"


@router.post(
    "/document-check/upload",
    response_model=list[OwnerResult],
    dependencies=[Depends(authorize)],
    responses={
        400: {"description": "The multipart body could not be parsed (or has too many parts)."},
        401: {"description": "Missing or invalid X-API-Key (only when the server sets API_KEYS)."},
        411: {"description": "Content-Length header missing."},
        413: {"description": "The whole request is larger than MAX_UPLOAD_REQUEST_BYTES."},
        415: {"description": "The body is not multipart/form-data."},
        422: {"description": f"No files, more than {MAX_DOCUMENTS}, or a part that isn't a file."},
        429: {"description": "Rate limit reached; see the Retry-After header (seconds)."},
        503: {"description": "The document model (Ollama) is not available; nothing was read."},
    },
    openapi_extra={"requestBody": {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "required": [UPLOAD_FIELD],
        "properties": {UPLOAD_FIELD: {"type": "array", "items": {"type": "string", "format": "binary"},
                                      "description": f"1 to {MAX_DOCUMENTS} PDF, PNG or JPG files."}},
    }}}}},
)
async def document_check_upload(
    request: Request,
    processor: DocumentProcessor = Depends(get_processor),
) -> list[OwnerResult]:
    """Like /document-check, for 1-50 uploaded files (form field "files"), in upload order.

    The body is parsed here, not by FastAPI, so that the API key, the rate limit, the model check
    and the size limit are all checked before any uploaded bytes are read.
    """
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise HTTPException(415, "send the files as multipart/form-data")
    length = request.headers.get("content-length")
    if length is None or not length.isdigit():
        raise HTTPException(411, "Content-Length header is required")
    limit = get_settings().max_upload_request_bytes
    if int(length) > limit:
        raise HTTPException(413, f"upload is larger than {limit} bytes")
    try:
        await processor.ensure_ready()
    except ModelUnavailableError:
        raise HTTPException(status_code=503, detail="document model is not available, try again later") from None

    form: FormData = await request.form(max_files=MAX_DOCUMENTS + 1, max_fields=0)
    try:
        items = form.multi_items()
        if any(key != UPLOAD_FIELD or not isinstance(value, UploadFile) for key, value in items):
            raise HTTPException(422, f"only file parts named '{UPLOAD_FIELD}' are accepted")
        if not 1 <= len(items) <= MAX_DOCUMENTS:
            raise HTTPException(422, f"send between 1 and {MAX_DOCUMENTS} files")
        try:
            return await processor.process_uploads([value.file for _, value in items])
        except ModelUnavailableError:
            raise HTTPException(503, "document model is not available, try again later") from None
    finally:
        await form.close()  # deletes Starlette's spooled temporary files
