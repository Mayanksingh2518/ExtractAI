"""app/utils/normalize.py and app/schemas/extraction.py: formats, field names, and the real registry."""

import pytest

from app.pipelines.registry import PipelineRegistry
from app.schemas.classification import DocumentType
from app.schemas.extraction import AadhaarData, PanCardData, PassportData, TaxReturnData
from app.utils.normalize import to_aadhaar_number, to_amount, to_iso_date, to_pan


@pytest.mark.parametrize("raw, want", [
    ("15 MAY 1985", "1985-05-15"), ("31 DEC 2030", "2030-12-31"), ("01/01/1990", "1990-01-01"),
    ("23-11-1975", "1975-11-23"), ("05.08.1988", "1988-08-05"), ("1985-05-15", "1985-05-15"),
    ("15 September 1985", "1985-09-15"), ("15-Sep-1985", "1985-09-15"),
    ("31/02/1990", "31/02/1990"),  # impossible date: kept as printed, not "fixed"
    ("1990", "1990"), (" null ", None), ("", None), (None, None),
])
def test_dates(raw, want):
    assert to_iso_date(raw) == want


@pytest.mark.parametrize("raw, want", [
    ("2345 6789 0123", "2345-6789-0123"), ("234567890123", "2345-6789-0123"), ("2345-6789-0123", "2345-6789-0123"),
    ("XXXX XXXX 0123", "XXXX-XXXX-0123"), ("xxxx xxxx 0123", "XXXX-XXXX-0123"),
    ("2345 6789 012", "2345 6789 012"),  # 11 digits: kept as printed, not padded
    ("N/A", None), (None, None),
])
def test_aadhaar_numbers(raw, want):
    assert to_aadhaar_number(raw) == want


@pytest.mark.parametrize("raw, want", [
    ("5,00,000", "500000"), ("₹ 5,00,000/-", "500000"), ("Rs. 50,000", "50000"), ("INR 4,50,000", "450000"),
    ("500000.00", "500000"), ("1,234.50", "1234.50"), ("0", "0"),
    ("Nil", "Nil"),  # not a number: kept as printed
    ("-", None), (None, None),
])
def test_amounts(raw, want):
    assert to_amount(raw) == want


@pytest.mark.parametrize("raw, want", [
    ("ABCDE1234F", "ABCDE1234F"), ("abcde1234f", "ABCDE1234F"), ("ABCDE 1234 F", "ABCDE1234F"),
    ("ABCD1234F", "ABCD1234F"),  # 9 characters: kept as printed
    ("null", None), (None, None),
])
def test_pan_numbers(raw, want):
    assert to_pan(raw) == want


def test_passport_data_normalises():
    p = PassportData(passportNumber="ab 1234567", dateOfBirth="15 MAY 1985", expiryDate="null")
    assert p.model_dump() == {"passportNumber": "AB1234567", "dateOfBirth": "1985-05-15", "expiryDate": None}


def test_aadhaar_data_uses_aadharNumber_and_normalises():
    a = AadhaarData(aadharNumber="2345 6789 0123", dateOfBirth="01/01/1990", address="  123,  Main St ")
    assert a.model_dump() == {"aadharNumber": "2345-6789-0123", "dateOfBirth": "1990-01-01", "address": "123, Main St"}


def test_tax_return_data_uses_integer_assessmentYear_and_normalises():
    t = TaxReturnData(assessmentYear=2025, taxPayerName="JOHN  DOE", totalIncome="5,00,000", taxPaid="50,000", taxDue=None)
    assert t.model_dump() == {"assessmentYear": 2025, "taxPayerName": "JOHN DOE", "totalIncome": "500000",
                              "taxPaid": "50000", "taxDue": None}
    assert {"type": "integer"} in TaxReturnData.model_json_schema()["properties"]["assessmentYear"]["anyOf"]


def test_assessment_year_out_of_range_is_treated_as_a_misread():
    t = TaxReturnData(assessmentYear=202526, taxPayerName=None, totalIncome=None, taxPaid=None, taxDue=None)
    assert t.assessmentYear is None


def test_pan_card_data_normalises():
    c = PanCardData(panNumber="fghij 5678 k", dateOfBirth="05/08/1988", fatherName=" PETER  LEE ")
    assert c.model_dump() == {"panNumber": "FGHIJ5678K", "dateOfBirth": "1988-08-05", "fatherName": "PETER LEE"}


def test_registry_has_a_pipeline_for_every_known_type_except_unknown():
    registry = PipelineRegistry.build(None)  # type: ignore[arg-type]  # no calls are made
    assert registry.types == ["passport", "idCard", "taxReturn", "panCard"]
    assert set(registry.types) == {t.value for t in DocumentType} - {"unknown"}
    assert registry.get(DocumentType.UNKNOWN) is None
