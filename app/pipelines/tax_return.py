from pathlib import Path

from app.pipelines.base import BaseDocumentPipeline
from app.schemas.extraction import TaxReturnData

PROMPT = """Extract these fields from the income tax return or its acknowledgement (ITR-V):
- assessmentYear: the Assessment Year (AY) as one number, its first year: "2025-26" -> 2025.
- taxPayerName: the taxpayer's full name.
- totalIncome: the "Total Income" amount.
- taxPaid: the "Taxes Paid" amount.
- taxDue: the balance still to be paid after taxes paid: "Amount payable", "Balance tax payable",
  "Tax Payable / Due" or "Tax Due". NOT the total tax liability ("Total Tax, Fee and Interest",
  "Tax payable on total income") and not the refund.
Copy each amount exactly as printed. Do not calculate anything. Use null for anything not visible."""


class TaxReturnPipeline(BaseDocumentPipeline):
    document_type = "taxReturn"
    # An ITR-V acknowledgement has every field on page 1 (one call). In a full ITR form the
    # totals follow the personal details on pages 2-3, so pages 1-3 are read if page 1 lacks them.
    max_pages = 3

    async def extract(self, page_images: list[Path]) -> TaxReturnData:
        return await self._generate(TaxReturnData, PROMPT, page_images)
