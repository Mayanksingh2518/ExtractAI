from pathlib import Path

from app.pipelines.base import BaseDocumentPipeline
from app.schemas.extraction import PassportData

PROMPT = """Extract these fields from the passport data page:
- passportNumber: the passport number (not the file number or MRZ line).
- dateOfBirth: the holder's date of birth.
- expiryDate: the date of expiry.
Copy each value exactly as printed. Use null for anything not visible."""


class PassportPipeline(BaseDocumentPipeline):
    document_type = "passport"

    async def extract(self, page_images: list[Path]) -> PassportData:
        return await self._generate(PassportData, PROMPT, page_images)
