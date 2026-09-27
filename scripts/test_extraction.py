"""Checks for the Stage 9 extraction pipelines on the FAKE sample documents.

Usage:  python -m scripts.make_sample_documents && python -m scripts.test_extraction [--offline]
Part A (formats, schemas, registry) needs nothing. Part B needs Ollama with OLLAMA_MODEL pulled.
"""

import asyncio
import dataclasses
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.pipelines.base import ExtractionError
from app.pipelines.registry import PipelineRegistry
from app.schemas.classification import DocumentType
from app.schemas.extraction import AadhaarData, PassportData, TaxReturnData
from app.services.ollama import OllamaClient
from app.utils.normalize import to_aadhaar_number, to_amount, to_iso_date
from app.utils.pdf import to_page_images
from app.utils.workspace import request_workspace

SAMPLES = Path("documents")
results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")


def part_a() -> None:
    for raw, want in [
        ("15 MAY 1985", "1985-05-15"), ("31 DEC 2030", "2030-12-31"), ("01/01/1990", "1990-01-01"),
        ("23-11-1975", "1975-11-23"), ("05.08.1988", "1988-08-05"), ("1985-05-15", "1985-05-15"),
        ("15 September 1985", "1985-09-15"), ("15-Sep-1985", "1985-09-15"),
        ("31/02/1990", "31/02/1990"),  # impossible date: kept as printed, not "fixed"
        ("1990", "1990"), (" null ", None), ("", None), (None, None),
    ]:
        check(f"date {raw!r} -> {want!r}", to_iso_date(raw) == want, repr(to_iso_date(raw)))
    for raw, want in [
        ("2345 6789 0123", "2345-6789-0123"), ("234567890123", "2345-6789-0123"), ("2345-6789-0123", "2345-6789-0123"),
        ("XXXX XXXX 0123", "XXXX-XXXX-0123"), ("xxxx xxxx 0123", "XXXX-XXXX-0123"),
        ("2345 6789 012", "2345 6789 012"),  # 11 digits: kept as printed, not padded
        ("N/A", None), (None, None),
    ]:
        check(f"aadhaar {raw!r} -> {want!r}", to_aadhaar_number(raw) == want, repr(to_aadhaar_number(raw)))
    for raw, want in [
        ("5,00,000", "500000"), ("₹ 5,00,000/-", "500000"), ("Rs. 50,000", "50000"), ("INR 4,50,000", "450000"),
        ("500000.00", "500000"), ("1,234.50", "1234.50"), ("0", "0"),
        ("Nil", "Nil"),  # not a number: kept as printed
        ("-", None), (None, None),
    ]:
        check(f"amount {raw!r} -> {want!r}", to_amount(raw) == want, repr(to_amount(raw)))

    p = PassportData(passportNumber="ab 1234567", dateOfBirth="15 MAY 1985", expiryDate="null")
    check("PassportData normalises", p.model_dump() == {"passportNumber": "AB1234567", "dateOfBirth": "1985-05-15", "expiryDate": None})
    a = AadhaarData(aadharNumber="2345 6789 0123", dateOfBirth="01/01/1990", address="  123,  Main St ")
    check("AadhaarData uses 'aadharNumber' and normalises",
          a.model_dump() == {"aadharNumber": "2345-6789-0123", "dateOfBirth": "1990-01-01", "address": "123, Main St"})
    t = TaxReturnData(assessmentYear=2025, taxPayerName="JOHN  DOE", totalIncome="5,00,000", taxPaid="50,000", taxDue=None)
    check("TaxReturnData uses 'assessmentYear' (int) and normalises",
          t.model_dump() == {"assessmentYear": 2025, "taxPayerName": "JOHN DOE", "totalIncome": "500000", "taxPaid": "50000", "taxDue": None})
    check("assessmentYear out of range -> None", TaxReturnData(assessmentYear=202526, taxPayerName=None, totalIncome=None, taxPaid=None, taxDue=None).assessmentYear is None)
    schema = TaxReturnData.model_json_schema()["properties"]["assessmentYear"]
    check("model is asked for an integer year", {"type": "integer"} in schema.get("anyOf", []), str(schema.get("anyOf")))

    registry = PipelineRegistry.build(None)  # type: ignore[arg-type]  # no calls made in Part A
    check("registry has the 3 pipelines", registry.types == ["passport", "idCard", "taxReturn"], str(registry.types))
    check("every pipeline key is a real DocumentType", all(t in {d.value for d in DocumentType} for t in registry.types))
    check("'unknown' still has no pipeline", registry.get(DocumentType.UNKNOWN) is None)


# (file, documentType, pages to use (None = all), expected data)
CASES = [
    ("sample_passport.png", DocumentType.PASSPORT, None,
     {"passportNumber": "AB1234567", "dateOfBirth": "1985-05-15", "expiryDate": "2030-12-31"}),
    ("sample_passport_scan.pdf", DocumentType.PASSPORT, None,
     {"passportNumber": "AB1234567", "dateOfBirth": "1985-05-15", "expiryDate": "2030-12-31"}),
    ("sample_passport_no_name.png", DocumentType.PASSPORT, None,
     {"passportNumber": "CD7654321", "dateOfBirth": "1979-02-02", "expiryDate": "2029-01-01"}),
    ("sample_aadhaar.png", DocumentType.AADHAAR, None,
     {"aadharNumber": "2345-6789-0123", "dateOfBirth": "1990-01-01", "address": "123, Main Street, Testcity, Teststate 400001"}),
    ("sample_aadhaar_front.png", DocumentType.AADHAAR, None,  # no address printed -> null
     {"aadharNumber": "9876-5432-1098", "dateOfBirth": "1975-11-23", "address": None}),
    ("sample_tax_return.pdf", DocumentType.TAX_RETURN, None,
     {"assessmentYear": 2025, "taxPayerName": "JOHN DOE", "totalIncome": "500000", "taxPaid": "50000", "taxDue": "450000"}),
    ("sample_tax_return.pdf", DocumentType.TAX_RETURN, slice(1, 2),  # page 2 only: salary schedule, no totals
     {"assessmentYear": None, "taxPayerName": None, "totalIncome": None, "taxPaid": None, "taxDue": None}),
]


def _same(actual: object, expected: object) -> bool:
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.casefold() == expected.casefold()
    return actual == expected


async def part_b() -> None:
    settings = get_settings()
    async with OllamaClient.from_settings(settings) as ollama:
        registry = PipelineRegistry.build(ollama)
        for name, doc_type, pages_slice, expected in CASES:
            with request_workspace() as ws:
                pages = await to_page_images(SAMPLES / name, ws, settings.pdf_render_dpi, settings.max_pdf_pages)
                pages = pages[pages_slice] if pages_slice else pages
                start = time.perf_counter()
                data = (await registry.extract(doc_type, pages)).model_dump()
            wrong = {k: data.get(k) for k, v in expected.items() if not _same(data.get(k), v)}
            label = f"{name}{' (page 2 only)' if pages_slice else ''}"
            check(f"{label:36} ({time.perf_counter() - start:.1f}s)", not wrong and data.keys() == expected.keys(),
                  f"wrong: {wrong}" if wrong else str(data))

    down = OllamaClient.from_settings(dataclasses.replace(settings, ollama_host="http://localhost:1"))
    try:
        await PipelineRegistry.build(down).extract(DocumentType.PASSPORT, [SAMPLES / "sample_passport.png"])
        check("Ollama unreachable -> ExtractionError", False, "no error raised")
    except ExtractionError as exc:
        check("Ollama unreachable -> ExtractionError", True, str(exc))
    finally:
        await down.aclose()


async def main() -> None:
    part_a()
    if "--offline" not in sys.argv:
        print()
        await part_b()
    print(f"\n{sum(results)}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
