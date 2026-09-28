"""Identify what a document is and whose it is, using the vision model."""

from pathlib import Path

from app.schemas.classification import Classification, DocumentType
from app.services.ollama import OllamaClient, OllamaError
from app.services.prompts import SYSTEM_PROMPT

CLASSIFY_PROMPT = """Classify this document.

documentName: first, say what the document is in a short title, based on its printed heading,
e.g. "Indian Passport", "Aadhaar card", "2025 Income tax return", "Driving Licence", "Grocery receipt".

documentType - choose exactly one:
- "passport": a passport (data page with passport number, nationality, often an MRZ code at the bottom).
- "idCard": an Indian Aadhaar card or Aadhaar letter ONLY (Government of India / UIDAI, 12-digit Aadhaar number).
  "idCard" does NOT mean "any ID card".
- "taxReturn": an income tax RETURN FILING or its acknowledgement (ITR / ITR-V): it reports an assessment
  year and income/tax figures such as total income, tax paid, tax payable.
- "panCard": an Indian PAN card (Permanent Account Number card, or e-PAN) issued by the Income Tax
  Department, with a 10-character PAN like ABCDE1234F. It is an ID card, NOT a tax return.
- "unknown": anything else. This includes every other kind of ID card - driving licence, voter ID,
  employee or student ID - as well as receipts, letters, photos, or if you are not sure.

ownerName: ONLY the full name of the person the document belongs to (passport holder, Aadhaar holder,
taxpayer, PAN card holder), given names then surname. Do not include labels, numbers, dates, relatives' names
(S/O, D/O, W/O, father's name) or the issuing authority. null if no holder name is visible."""


AADHAAR_MARKERS = ("aadhaar", "aadhar", "uidai")
PAN_MARKERS = ("permanent account number", "pan card", "e-pan")


class ClassificationError(Exception):
    """The document could not be classified. Messages never include document content."""


def check_type_against_name(result: Classification) -> Classification:
    """Correct the model's documentType when its own documentName contradicts it.

    The model names documents reliably ("Permanent Account Number Card") but reads the
    idCard enum as "any ID card", so the name is used as a cross-check:
    - a PAN card named as such but typed idCard or taxReturn -> panCard
    - idCard without an Aadhaar name, or panCard without a PAN name -> unknown (can't confirm)
    """
    name = (result.documentName or "").casefold()
    doc_type = result.documentType
    named_pan = any(m in name for m in PAN_MARKERS)
    if named_pan and doc_type in (DocumentType.AADHAAR, DocumentType.TAX_RETURN):
        doc_type = DocumentType.PAN_CARD
    elif doc_type is DocumentType.AADHAAR and not any(m in name for m in AADHAAR_MARKERS):
        doc_type = DocumentType.UNKNOWN
    elif doc_type is DocumentType.PAN_CARD and not named_pan:
        doc_type = DocumentType.UNKNOWN
    if doc_type is result.documentType:
        return result
    return result.model_copy(update={"documentType": doc_type})


class DocumentClassifier:
    def __init__(self, ollama: OllamaClient, max_pages: int = 1) -> None:
        self._ollama = ollama
        # Page 1 identifies almost every document; each extra page costs up to ~2,000 tokens.
        self._max_pages = max_pages

    async def is_ready(self) -> bool:
        """True if the model can be used right now."""
        return await self._ollama.is_model_available()

    async def classify(self, page_images: list[Path]) -> Classification:
        if not page_images:
            raise ClassificationError("no page images to classify")
        try:
            result = await self._ollama.generate_structured(
                Classification,
                CLASSIFY_PROMPT,
                page_images[: self._max_pages],
                system_prompt=SYSTEM_PROMPT,
            )
        except OllamaError as exc:
            raise ClassificationError(f"classification failed: {exc}") from exc
        return check_type_against_name(result)
