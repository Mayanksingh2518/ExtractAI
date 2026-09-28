"""Classify + extract the realistic FAKE documents and report every field.

Usage:  python -m scripts.make_realistic_documents
        caffeinate -i python -u -m scripts.test_realistic [--dpi 150] [--pages taxReturn=1 idCard=1]
--dpi overrides PDF_RENDER_DPI; --pages overrides a pipeline's max_pages (to compare settings).
Needs Ollama with OLLAMA_MODEL pulled.
"""

import argparse
import asyncio
import dataclasses
import time
from collections.abc import Callable
from pathlib import Path

from app.config import get_settings
from app.pipelines.registry import PipelineRegistry
from app.schemas.classification import DocumentType
from app.services.classifier import DocumentClassifier
from app.services.ollama import OllamaClient
from app.utils.pdf import to_page_images
from app.utils.workspace import request_workspace

SAMPLES = Path("documents")


def contains(*parts: str) -> Callable[[object], bool]:
    """For free text like addresses: every part must appear (case-insensitive)."""
    return lambda value: isinstance(value, str) and all(p.casefold() in value.casefold() for p in parts)


PASSPORT_A = {"passportNumber": "K4821937", "dateOfBirth": "1991-03-07", "expiryDate": "2029-08-11"}
# (file, documentType, owner name words (any order), expected data)
CASES = [
    ("realistic_passport.png", DocumentType.PASSPORT, "PRIYA ANJALI SHARMA", PASSPORT_A),
    ("realistic_passport_photo.jpg", DocumentType.PASSPORT, "RAHUL VERMA",
     {"passportNumber": "Z9053318", "dateOfBirth": "1979-11-02", "expiryDate": "2031-01-16"}),
    ("realistic_passport_sideways.pdf", DocumentType.PASSPORT, "PRIYA ANJALI SHARMA", PASSPORT_A),
    ("realistic_e_aadhaar.pdf", DocumentType.AADHAAR, "NEHA KAPOOR",
     {"aadharNumber": "4821-7390-5612", "dateOfBirth": "1988-06-14", "address": contains("Lotus Residency", "400058")}),
    ("realistic_aadhaar_card_scan.pdf", DocumentType.AADHAAR, "VIKRAM SINGH",  # address is on page 2 (the back)
     {"aadharNumber": "6130-2297-4485", "dateOfBirth": "1995-12-05", "address": contains("Sector 21", "160022")}),
    ("realistic_itr_full.pdf", DocumentType.TAX_RETURN, "ARJUN MEHTA",  # totals on pages 2-3
     {"assessmentYear": 2024, "taxPayerName": "ARJUN MEHTA", "totalIncome": "1023500", "taxPaid": "110000",
      "taxDue": "15570"}),
]


def _matches(actual: object, expected: object) -> bool:
    if callable(expected):
        return expected(actual)
    if isinstance(actual, str) and isinstance(expected, str):
        return actual.casefold() == expected.casefold()
    return actual == expected


def _same_person(actual: str | None, expected: str) -> bool:
    return actual is not None and sorted(actual.casefold().split()) == sorted(expected.casefold().split())


async def main(dpi: int | None, page_overrides: dict[str, int]) -> None:
    settings = get_settings()
    if dpi:
        settings = dataclasses.replace(settings, pdf_render_dpi=dpi)
    print(f"model={settings.ollama_model} dpi={settings.pdf_render_dpi} num_ctx={settings.ollama_num_ctx}")
    passed_fields = total_fields = passed_docs = 0
    async with OllamaClient.from_settings(settings) as ollama:
        classifier, registry = DocumentClassifier(ollama), PipelineRegistry.build(ollama)
        for doc_type, pages in page_overrides.items():
            registry.get(doc_type).max_pages = pages  # instance attribute: only this run
        print("max_pages:", {t: registry.get(t).max_pages for t in registry.types}, "\n")
        for name, doc_type, owner, expected in CASES:
            with request_workspace() as ws:
                pages = await to_page_images(SAMPLES / name, ws, settings.pdf_render_dpi, settings.max_pdf_pages)
                start = time.perf_counter()
                result = await classifier.classify(pages)
                classify_s = time.perf_counter() - start
                data = await registry.extract(doc_type, pages)  # extract even if misclassified, to see both
                extract_s = time.perf_counter() - start - classify_s
            data = data.model_dump() if data else {}
            type_ok, owner_ok = result.documentType is doc_type, _same_person(result.ownerName, owner)
            wrong = {k: data.get(k) for k, v in expected.items() if not _matches(data.get(k), v)}
            doc_ok = type_ok and owner_ok and not wrong
            passed_docs += doc_ok
            passed_fields += 2 + len(expected) - (not type_ok) - (not owner_ok) - len(wrong)
            total_fields += 2 + len(expected)
            print(f"{'PASS' if doc_ok else 'FAIL'}  {name:33} classify {classify_s:4.1f}s  extract {extract_s:4.1f}s")
            if not type_ok:
                print(f"        type: {result.documentType.value} (name {result.documentName!r})")
            if not owner_ok:
                print(f"        owner: {result.ownerName!r}")
            for key, value in wrong.items():
                print(f"        {key}: {value!r}")
    print(f"\n{passed_docs}/{len(CASES)} documents, {passed_fields}/{total_fields} fields correct")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dpi", type=int)
    parser.add_argument("--pages", nargs="*", default=[], help="documentType=max_pages, e.g. taxReturn=3")
    args = parser.parse_args()
    asyncio.run(main(args.dpi, {k: int(v) for k, v in (p.split("=") for p in args.pages)}))
