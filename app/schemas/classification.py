from enum import Enum

from pydantic import BaseModel, Field, field_validator


class DocumentType(str, Enum):
    PASSPORT = "passport"
    AADHAAR = "idCard"
    TAX_RETURN = "taxReturn"
    PAN_CARD = "panCard"
    UNKNOWN = "unknown"


class Classification(BaseModel):
    # Field order matters: the model generates fields in schema order, so naming the
    # document first grounds the documentType choice (e.g. "Driving Licence" -> unknown).
    documentName: str | None = Field(
        description="Short human-readable title of the document, e.g. 'Indian Passport'. null if unclear."
    )
    documentType: DocumentType = Field(
        description="passport, idCard (Indian Aadhaar only), taxReturn, panCard (Indian PAN card), "
        "or unknown (any other document or ID card)."
    )
    ownerName: str | None = Field(
        description="Full name of the person the document belongs to, and nothing else. null if not visible."
    )

    @field_validator("documentName", "ownerName")
    @classmethod
    def blank_to_none(cls, value: str | None) -> str | None:
        """Collapse whitespace; treat empty strings and 'null'-like text as missing."""
        if value is None:
            return None
        cleaned = " ".join(value.split())
        if cleaned.lower() in {"", "null", "none", "n/a", "unknown"}:
            return None
        return cleaned
