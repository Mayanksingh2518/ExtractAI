from typing import Any

from pydantic import BaseModel, Field

from app.schemas.classification import DocumentType


class DocumentResult(BaseModel):
    documentType: DocumentType
    documentName: str | None
    data: dict[str, Any] | None = Field(
        description="Type-specific extracted data; null for types without a pipeline or when extraction failed."
    )
    sourceIndex: int = Field(description="Position of this document in the request's documentUrls (0-based).")
    error: str | None = Field(default=None, description="Why this document could not be fully processed; null on success.")


class OwnerResult(BaseModel):
    ownerName: str | None = Field(description="null groups documents with no visible owner (or that failed).")
    documents: list[DocumentResult]
