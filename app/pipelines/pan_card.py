from pathlib import Path

from app.pipelines.base import BaseDocumentPipeline
from app.schemas.extraction import PanCardData

PROMPT = """Extract these fields from the PAN card (Permanent Account Number card or e-PAN):
- panNumber: the Permanent Account Number (5 letters, 4 digits, 1 letter).
- dateOfBirth: the holder's date of birth.
- fatherName: the father's name (not the holder's own name).
Copy each value exactly as printed. Use null for anything not visible."""


class PanCardPipeline(BaseDocumentPipeline):
    document_type = "panCard"

    async def extract(self, page_images: list[Path]) -> PanCardData:
        return await self._generate(PanCardData, PROMPT, page_images)
