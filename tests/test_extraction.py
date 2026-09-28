"""Extraction pipelines with the real model on the FAKE sample documents."""

import dataclasses

import pytest

from app.pipelines.base import ExtractionError
from app.pipelines.registry import PipelineRegistry
from app.schemas.classification import DocumentType
from app.services.ollama import OllamaClient
from app.utils.pdf import to_page_images

pytestmark = pytest.mark.anyio

PASSPORT = {"passportNumber": "AB1234567", "dateOfBirth": "1985-05-15", "expiryDate": "2030-12-31"}
# file: (documentType, pages to use (None = all), expected data)
CASES = {
    "sample_passport.png": (DocumentType.PASSPORT, None, PASSPORT),
    "sample_passport_scan.pdf": (DocumentType.PASSPORT, None, PASSPORT),
    "sample_passport_no_name.png": (DocumentType.PASSPORT, None,
                                    {"passportNumber": "CD7654321", "dateOfBirth": "1979-02-02", "expiryDate": "2029-01-01"}),
    "sample_aadhaar.png": (DocumentType.AADHAAR, None, {"aadharNumber": "2345-6789-0123", "dateOfBirth": "1990-01-01",
                                                       "address": "123, Main Street, Testcity, Teststate 400001"}),
    "sample_aadhaar_front.png": (DocumentType.AADHAAR, None,  # no address printed -> null
                                 {"aadharNumber": "9876-5432-1098", "dateOfBirth": "1975-11-23", "address": None}),
    "sample_tax_return.pdf": (DocumentType.TAX_RETURN, None, {"assessmentYear": 2025, "taxPayerName": "JOHN DOE",
                                                             "totalIncome": "500000", "taxPaid": "50000", "taxDue": "450000"}),
    "sample_tax_return.pdf, page 2 only": (DocumentType.TAX_RETURN, slice(1, 2),  # salary schedule, no totals
                                          dict.fromkeys(["assessmentYear", "taxPayerName", "totalIncome", "taxPaid", "taxDue"])),
    "sample_pan_card.png": (DocumentType.PAN_CARD, None,
                            {"panNumber": "FGHIJ5678K", "dateOfBirth": "1988-08-05", "fatherName": "PETER LEE"}),
    "realistic_pan_card.png": (DocumentType.PAN_CARD, None,
                               {"panNumber": "BQTPK7302M", "dateOfBirth": "1993-04-19", "fatherName": "MOHAN NAIR"}),
}


def same(actual, expected) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.casefold() == expected.casefold()
    return actual == expected


@pytest.mark.model
@pytest.mark.parametrize("name, case", CASES.items(), ids=CASES.keys())
async def test_extracts_exact_values(name, case, ollama, samples, settings, tmp_path):
    doc_type, pages_slice, expected = case
    pages = await to_page_images(samples / name.split(",")[0], tmp_path, settings.pdf_render_dpi, settings.max_pdf_pages)
    data = (await PipelineRegistry.build(ollama).extract(doc_type, pages[pages_slice] if pages_slice else pages)).model_dump()
    assert data.keys() == expected.keys()
    assert {k: v for k, v in data.items() if not same(v, expected[k])} == {}


async def test_ollama_unreachable_raises_extraction_error(samples, settings):
    down = OllamaClient.from_settings(dataclasses.replace(settings, ollama_host="http://localhost:1"))
    try:
        with pytest.raises(ExtractionError, match="Could not reach Ollama"):
            await PipelineRegistry.build(down).extract(DocumentType.PASSPORT, [samples / "sample_passport.png"])
    finally:
        await down.aclose()
