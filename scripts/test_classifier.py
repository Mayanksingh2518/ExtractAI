"""Manual checks for app/services/classifier.py on the FAKE sample documents.

Usage:  python -m scripts.make_sample_documents && python -m scripts.test_classifier
Needs Ollama running with OLLAMA_MODEL pulled.
"""

import asyncio
import dataclasses
import time
from pathlib import Path

from app.config import get_settings
from app.schemas.classification import Classification, DocumentType
from app.services.classifier import ClassificationError, DocumentClassifier, check_type_against_name
from app.services.ollama import OllamaClient
from app.utils.pdf import to_page_images
from app.utils.workspace import request_workspace

SAMPLES = Path("documents")
ANY = object()  # "don't care" for documentName

# (file, expected documentType, expected ownerName)
CASES = [
    ("sample_passport.png", DocumentType.PASSPORT, "JOHN DOE"),
    ("sample_passport_scan.pdf", DocumentType.PASSPORT, "JOHN DOE"),
    ("sample_aadhaar.png", DocumentType.AADHAAR, "MARIA DOE"),
    ("sample_tax_return.pdf", DocumentType.TAX_RETURN, "JOHN DOE"),
    ("sample_driving_licence.png", DocumentType.UNKNOWN, ANY),  # other ID type -> unknown
    ("sample_pan_card.png", DocumentType.UNKNOWN, ANY),  # Indian ID, but not Aadhaar -> unknown
    ("sample_receipt.png", DocumentType.UNKNOWN, None),  # not an identity document, no owner
    ("sample_passport_no_name.png", DocumentType.PASSPORT, None),  # name fields blank -> null
]

# Offline checks of the name cross-check: (model's documentName, model's type, expected final type)
CROSS_CHECKS = [
    ("Aadhaar card", DocumentType.AADHAAR, DocumentType.AADHAAR),
    ("AADHAR", DocumentType.AADHAAR, DocumentType.AADHAAR),
    ("UIDAI e-Aadhaar letter", DocumentType.AADHAAR, DocumentType.AADHAAR),
    ("Permanent Account Number Card", DocumentType.AADHAAR, DocumentType.UNKNOWN),
    ("Voter ID card", DocumentType.AADHAAR, DocumentType.UNKNOWN),
    (None, DocumentType.AADHAAR, DocumentType.UNKNOWN),  # can't confirm Aadhaar -> don't guess
    ("PAN card", DocumentType.TAX_RETURN, DocumentType.UNKNOWN),
    ("Permanent Account Number Card", DocumentType.TAX_RETURN, DocumentType.UNKNOWN),
    ("ITR-V Acknowledgement", DocumentType.TAX_RETURN, DocumentType.TAX_RETURN),
    ("2025 Income tax return", DocumentType.TAX_RETURN, DocumentType.TAX_RETURN),
    ("Travel Document", DocumentType.PASSPORT, DocumentType.PASSPORT),  # passports are not checked
    ("Grocery receipt", DocumentType.UNKNOWN, DocumentType.UNKNOWN),
]


def run_cross_checks() -> int:
    passed = 0
    for doc_name, model_type, expected in CROSS_CHECKS:
        before = Classification(documentName=doc_name, documentType=model_type, ownerName="X")
        after = check_type_against_name(before)
        ok = after.documentType is expected and after.ownerName == "X" and after.documentName == before.documentName
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'}  cross-check {doc_name!r:34} {model_type.value:9} -> {after.documentType.value}")
    return passed


def _same_name(actual: str | None, expected: object) -> bool:
    if expected is ANY:
        return True
    if expected is None or actual is None:
        return actual is expected
    return actual.casefold() == str(expected).casefold()


async def main() -> None:
    settings = get_settings()
    passed = run_cross_checks()
    print()
    async with OllamaClient.from_settings(settings) as ollama:
        classifier = DocumentClassifier(ollama)
        for name, expected_type, expected_owner in CASES:
            with request_workspace() as ws:
                pages = await to_page_images(SAMPLES / name, ws, settings.pdf_render_dpi, settings.max_pdf_pages)
                start = time.perf_counter()
                result = await classifier.classify(pages)
            ok = result.documentType is expected_type and _same_name(result.ownerName, expected_owner)
            passed += ok
            print(
                f"{'PASS' if ok else 'FAIL'}  {name:30} {result.documentType.value:9} "
                f"owner={result.ownerName!r:14} name={result.documentName!r} ({time.perf_counter() - start:.1f}s)"
            )

    # Error paths: Ollama unreachable, and no pages at all.
    down = OllamaClient.from_settings(dataclasses.replace(settings, ollama_host="http://localhost:1"))
    for label, classifier, pages in [
        ("Ollama unreachable", DocumentClassifier(down), [SAMPLES / "sample_passport.png"]),
        ("no page images", DocumentClassifier(down), []),
    ]:
        try:
            await classifier.classify(pages)
            print(f"FAIL  {label:30} no error raised")
        except ClassificationError as exc:
            passed += 1
            print(f"PASS  {label:30} ClassificationError: {exc}")
    await down.aclose()
    print(f"\n{passed}/{len(CROSS_CHECKS) + len(CASES) + 2} passed")


if __name__ == "__main__":
    asyncio.run(main())
