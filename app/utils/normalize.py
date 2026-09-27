"""Turn values copied from documents into consistent formats.

The model copies values exactly as printed; these functions reformat them in code.
A value that doesn't match a known format is kept as printed (tidied), never guessed.
"""

import re
from datetime import datetime

NULL_WORDS = {"", "null", "none", "n/a", "na", "-", "not visible", "not available"}

# Day-first, as printed on Indian documents and passports. US month-first dates are not supported.
DATE_FORMATS = (
    "%Y-%m-%d",
    "%d %b %Y", "%d %B %Y", "%d-%b-%Y", "%d %b, %Y",
    "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
)

AADHAAR_RE = re.compile(r"^([0-9X]{4})[ -]?([0-9X]{4})[ -]?(\d{4})$")  # X for masked Aadhaar
CURRENCY_RE = re.compile(r"(₹|rs\.?|inr|/-)", re.IGNORECASE)
AMOUNT_RE = re.compile(r"^\d+(\.\d+)?$")


def clean_text(value: str | None) -> str | None:
    """Collapse whitespace; treat empty and 'null'-like text as missing."""
    if value is None:
        return None
    cleaned = " ".join(value.split())
    return None if cleaned.casefold() in NULL_WORDS else cleaned


def to_iso_date(value: str | None) -> str | None:
    """'15 MAY 1985' or '15/05/1985' -> '1985-05-15'. Unknown formats are kept as printed."""
    text = clean_text(value)
    if text is None:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text.title(), fmt).date().isoformat()
        except ValueError:
            continue
    return text


def to_aadhaar_number(value: str | None) -> str | None:
    """'2345 6789 0123' -> '2345-6789-0123' (masked 'XXXX XXXX 0123' too). Otherwise kept as printed."""
    text = clean_text(value)
    if text is None:
        return None
    match = AADHAAR_RE.match(text.upper())
    return "-".join(match.groups()) if match else text


def to_amount(value: str | None) -> str | None:
    """'₹ 5,00,000/-' -> '500000', '1,234.50' -> '1234.50', '500000.00' -> '500000'. Otherwise kept as printed."""
    text = clean_text(value)
    if text is None:
        return None
    digits = CURRENCY_RE.sub("", text).replace(",", "").replace(" ", "")
    if not AMOUNT_RE.match(digits):
        return text
    whole, _, fraction = digits.partition(".")
    return whole if not fraction.strip("0") else digits
