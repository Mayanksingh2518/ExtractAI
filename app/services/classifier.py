"""Identify what a document is and whose it is, using the vision model."""

from pathlib import Path

from app.schemas.classification import Classification
from app.services.ollama import OllamaClient, OllamaError

SYSTEM_PROMPT = (
    "You are a careful document classifier for identity and tax documents. "
    "Report only what is clearly visible in the image. Never guess or invent values. "
    "If a field is not visible or not readable, use null."
)

CLASSIFY_PROMPT = """Classify this document.

documentName: first, say what the document is in a short title, based on its printed heading,
e.g. "Indian Passport", "Aadhaar card", "2025 Income tax return", "Driving Licence", "Grocery receipt".

documentType - choose exactly one:
- "passport": a passport (data page with passport number, nationality, often an MRZ code at the bottom).
- "idCard": an Indian Aadhaar card or Aadhaar letter ONLY (Government of India / UIDAI, 12-digit Aadhaar number).
  "idCard" does NOT mean "any ID card".
- "taxReturn": an income tax RETURN FILING or its acknowledgement (ITR / ITR-V): it reports an assessment
  year and income/tax figures such as total income, tax paid, tax payable.
- "unknown": anything else. This includes every other kind of ID card - driving licence, voter ID,
  employee or student ID, and the PAN card (Permanent Account Number card): a PAN card is an ID card,
  NOT a tax return, even though it is issued by the Income Tax Department - as well as receipts,
  letters, photos, or if you are not sure.

ownerName: ONLY the full name of the person the document belongs to (passport holder, Aadhaar holder,
taxpayer), given names then surname. Do not include labels, numbers, dates, relatives' names
(S/O, D/O, W/O, father's name) or the issuing authority. null if no holder name is visible."""


class ClassificationError(Exception):
    """The document could not be classified. Messages never include document content."""


class DocumentClassifier:
    def __init__(self, ollama: OllamaClient, max_pages: int = 1) -> None:
        self._ollama = ollama
        # Page 1 identifies almost every document; each extra page costs up to ~2,000 tokens.
        self._max_pages = max_pages

    async def classify(self, page_images: list[Path]) -> Classification:
        if not page_images:
            raise ClassificationError("no page images to classify")
        try:
            return await self._ollama.generate_structured(
                Classification,
                CLASSIFY_PROMPT,
                page_images[: self._max_pages],
                system_prompt=SYSTEM_PROMPT,
            )
        except OllamaError as exc:
            raise ClassificationError(f"classification failed: {exc}") from exc
