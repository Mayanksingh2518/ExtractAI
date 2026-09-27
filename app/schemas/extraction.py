"""Type-specific data extracted from each document. Every field is nullable: null = not visible.

Field names are part of the API contract: note 'aadharNumber' and 'assessmentYear'.
"""

from pydantic import BaseModel, Field, field_validator

from app.utils.normalize import clean_text, to_aadhaar_number, to_amount, to_iso_date

AS_PRINTED = "Copy exactly as printed. null if not visible."


class PassportData(BaseModel):
    passportNumber: str | None = Field(description=f"Passport number. {AS_PRINTED}")
    dateOfBirth: str | None = Field(description=f"Holder's date of birth. {AS_PRINTED}")
    expiryDate: str | None = Field(description=f"Date of expiry of the passport. {AS_PRINTED}")

    @field_validator("passportNumber")
    @classmethod
    def _passport_number(cls, value: str | None) -> str | None:
        text = clean_text(value)
        return text.replace(" ", "").upper() if text else None

    @field_validator("dateOfBirth", "expiryDate")
    @classmethod
    def _dates(cls, value: str | None) -> str | None:
        return to_iso_date(value)


class AadhaarData(BaseModel):
    aadharNumber: str | None = Field(description=f"The 12-digit Aadhaar number, e.g. '1234 5678 9012'. {AS_PRINTED}")
    dateOfBirth: str | None = Field(description=f"Holder's date of birth (DOB). {AS_PRINTED}")
    address: str | None = Field(description=f"Holder's full address on one line. {AS_PRINTED}")

    @field_validator("aadharNumber")
    @classmethod
    def _aadhaar_number(cls, value: str | None) -> str | None:
        return to_aadhaar_number(value)

    @field_validator("dateOfBirth")
    @classmethod
    def _date(cls, value: str | None) -> str | None:
        return to_iso_date(value)

    @field_validator("address")
    @classmethod
    def _address(cls, value: str | None) -> str | None:
        return clean_text(value)


class TaxReturnData(BaseModel):
    assessmentYear: int | None = Field(
        description="The FIRST year of the printed Assessment Year (AY), e.g. 'AY 2025-26' -> 2025. "
        "Not the financial year (FY). null if no assessment year is printed."
    )
    taxPayerName: str | None = Field(description=f"Full name of the taxpayer (assessee). {AS_PRINTED}")
    totalIncome: str | None = Field(description=f"The amount on the 'Total Income' line (not gross total income). {AS_PRINTED}")
    taxPaid: str | None = Field(description=f"The amount on the 'Taxes Paid' line. {AS_PRINTED}")
    taxDue: str | None = Field(description=f"The amount on the 'Tax Payable' / 'Tax Due' line. {AS_PRINTED}")

    @field_validator("assessmentYear")
    @classmethod
    def _year(cls, value: int | None) -> int | None:
        return value if value is None or 1900 <= value <= 2100 else None  # out of range = misread

    @field_validator("taxPayerName")
    @classmethod
    def _name(cls, value: str | None) -> str | None:
        return clean_text(value)

    @field_validator("totalIncome", "taxPaid", "taxDue")
    @classmethod
    def _amounts(cls, value: str | None) -> str | None:
        return to_amount(value)
