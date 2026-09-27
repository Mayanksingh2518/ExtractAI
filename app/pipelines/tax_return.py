from pathlib import Path

from app.pipelines.base import BaseDocumentPipeline
from app.schemas.extraction import TaxReturnData

PROMPT = """Extract these fields from the income tax return or its acknowledgement (ITR-V):
- assessmentYear: the Assessment Year (AY) as one number, its first year: "2025-26" -> 2025.
- taxPayerName: the taxpayer's full name.
- totalIncome: the "Total Income" amount.
- taxPaid: the "Taxes Paid" amount.
- taxDue: the "Tax Payable" or "Tax Due" amount.
Copy each amount exactly as printed. Do not calculate anything. Use null for anything not visible."""


class TaxReturnPipeline(BaseDocumentPipeline):
    document_type = "taxReturn"
    # The ITR-V acknowledgement has every field on page 1; raise to 2-3 for full ITR forms.
    max_pages = 1

    async def extract(self, page_images: list[Path]) -> TaxReturnData:
        return await self._generate(TaxReturnData, PROMPT, page_images)
