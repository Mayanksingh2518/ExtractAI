"""app/services/classifier.py: the name cross-check (offline) and classification with the real model."""

import dataclasses

import pytest

from app.schemas.classification import Classification, DocumentType
from app.services.classifier import ClassificationError, DocumentClassifier, check_type_against_name
from app.services.ollama import OllamaClient
from app.utils.pdf import to_page_images

T = DocumentType
ANY = object()  # "don't care" for ownerName

# (model's documentName, model's type) -> expected final type
CROSS_CHECKS = [
    ("Aadhaar card", T.AADHAAR, T.AADHAAR),
    ("AADHAR", T.AADHAAR, T.AADHAAR),
    ("UIDAI e-Aadhaar letter", T.AADHAAR, T.AADHAAR),
    ("Permanent Account Number Card", T.AADHAAR, T.PAN_CARD),  # named PAN -> panCard
    ("Voter ID card", T.AADHAAR, T.UNKNOWN),
    (None, T.AADHAAR, T.UNKNOWN),  # can't confirm Aadhaar -> don't guess
    ("PAN card", T.TAX_RETURN, T.PAN_CARD),
    ("Permanent Account Number Card", T.TAX_RETURN, T.PAN_CARD),
    ("e-PAN", T.AADHAAR, T.PAN_CARD),
    ("Income Tax PAN Card", T.PAN_CARD, T.PAN_CARD),
    ("Driving Licence", T.PAN_CARD, T.UNKNOWN),  # panCard needs a PAN name
    (None, T.PAN_CARD, T.UNKNOWN),
    ("ITR-V Acknowledgement", T.TAX_RETURN, T.TAX_RETURN),
    ("2025 Income tax return", T.TAX_RETURN, T.TAX_RETURN),
    ("Travel Document", T.PASSPORT, T.PASSPORT),  # passports are not checked
    ("Japan passport", T.PASSPORT, T.PASSPORT),
    ("Grocery receipt", T.UNKNOWN, T.UNKNOWN),
]

# file -> (expected type, expected owner)
MODEL_CASES = {
    "sample_passport.png": (T.PASSPORT, "JOHN DOE"),
    "sample_passport_scan.pdf": (T.PASSPORT, "JOHN DOE"),
    "sample_aadhaar.png": (T.AADHAAR, "MARIA DOE"),
    "sample_tax_return.pdf": (T.TAX_RETURN, "JOHN DOE"),
    "sample_driving_licence.png": (T.UNKNOWN, ANY),  # other ID type -> unknown
    "sample_pan_card.png": (T.PAN_CARD, "SARA LEE"),
    "realistic_pan_card.png": (T.PAN_CARD, "KAVITA NAIR"),  # father's name decoy
    "sample_receipt.png": (T.UNKNOWN, None),  # not an identity document, no owner
    "sample_passport_no_name.png": (T.PASSPORT, None),  # name fields blank -> null
}


@pytest.mark.parametrize("doc_name, model_type, expected", CROSS_CHECKS,
                         ids=[f"{n}-{t.value}" for n, t, _ in CROSS_CHECKS])
def test_name_cross_check(doc_name, model_type, expected):
    before = Classification(documentName=doc_name, documentType=model_type, ownerName="X")
    after = check_type_against_name(before)
    assert after.documentType is expected
    assert (after.documentName, after.ownerName) == (doc_name, "X")  # only the type may change


@pytest.mark.anyio
@pytest.mark.model
@pytest.mark.parametrize("name, case", MODEL_CASES.items(), ids=MODEL_CASES.keys())
async def test_classifies_samples(name, case, ollama, samples, settings, tmp_path):
    expected_type, expected_owner = case
    pages = await to_page_images(samples / name, tmp_path, settings.pdf_render_dpi, settings.max_pdf_pages)
    result = await DocumentClassifier(ollama).classify(pages)
    assert result.documentType is expected_type, result.documentName
    if expected_owner is not ANY:
        assert (result.ownerName or "").casefold() == (expected_owner or "").casefold()


@pytest.mark.anyio
@pytest.mark.parametrize("pages", [["sample_passport.png"], []], ids=["Ollama unreachable", "no pages"])
async def test_errors_raise_classification_error(pages, samples, settings):
    down = OllamaClient.from_settings(dataclasses.replace(settings, ollama_host="http://localhost:1"))
    try:
        with pytest.raises(ClassificationError):
            await DocumentClassifier(down).classify([samples / p for p in pages])
    finally:
        await down.aclose()
