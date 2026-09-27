from pathlib import Path

from app.pipelines.base import BaseDocumentPipeline
from app.schemas.extraction import AadhaarData

PROMPT = """Extract these fields from the Aadhaar card or letter:
- aadharNumber: the 12-digit Aadhaar number (not the VID or enrolment number).
- dateOfBirth: the holder's date of birth (DOB).
- address: the holder's address. Not printed on the front of the card: use null if it isn't shown.
Copy each value exactly as printed. Use null for anything not visible."""


class AadhaarPipeline(BaseDocumentPipeline):
    document_type = "idCard"

    async def extract(self, page_images: list[Path]) -> AadhaarData:
        return await self._generate(AadhaarData, PROMPT, page_images)
