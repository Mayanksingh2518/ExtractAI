"""Generate FAKE sample documents for local testing (no real personal data).

Usage:  python -m scripts.make_sample_documents
Writes to documents/ (gitignored).
"""

from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw, ImageFont

OUTPUT_DIR = Path("documents")


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", size)
    except OSError:
        return ImageFont.load_default(size)


def _card(path: Path, header: str, title: str, title_color: str, rows: list[tuple[str, str]],
          size: tuple[int, int] = (1000, 600)) -> None:
    """A simple ID-card-like image: header, title, then label/value rows."""
    img = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, size[0] - 10, size[1] - 10], outline="black", width=4)
    draw.text((40, 40), header, font=_font(30), fill="black")
    draw.text((40, 100), title, font=_font(52), fill=title_color)
    for i, (label, value) in enumerate(rows):
        draw.text((40, 200 + i * 70), label, font=_font(26), fill="gray")
        draw.text((330, 200 + i * 70), value, font=_font(32), fill="black")
    img.save(path)


def make_passport(path: Path) -> None:
    _card(path, "REPUBLIC OF TESTLAND", "PASSPORT", "darkblue", [
        ("Surname", "DOE"),
        ("Given names", "JOHN"),
        ("Passport No.", "AB1234567"),
        ("Date of birth", "15 MAY 1985"),
        ("Date of expiry", "31 DEC 2030"),
    ])


def make_passport_without_name(path: Path) -> None:
    _card(path, "REPUBLIC OF TESTLAND", "PASSPORT", "darkblue", [
        ("Surname", ""),
        ("Given names", ""),
        ("Passport No.", "CD7654321"),
        ("Date of birth", "02 FEB 1979"),
        ("Date of expiry", "01 JAN 2029"),
    ])


def make_aadhaar(path: Path) -> None:
    _card(path, "GOVERNMENT OF INDIA  (SAMPLE - NOT A REAL DOCUMENT)", "AADHAAR", "darkred", [
        ("Name", "MARIA DOE"),
        ("DOB", "01/01/1990"),
        ("Gender", "FEMALE"),
        ("Aadhaar No.", "2345 6789 0123"),
        ("Address", "123, Main Street, Testcity, Teststate 400001"),
    ], size=(1100, 620))


def make_driving_licence(path: Path) -> None:
    _card(path, "TESTLAND TRANSPORT AUTHORITY", "DRIVING LICENCE", "darkgreen", [
        ("Name", "ALEX KUMAR"),
        ("Licence No.", "DL-0420110012345"),
        ("Date of birth", "10 JUN 1992"),
        ("Valid till", "09 JUN 2032"),
        ("Class", "LMV, MCWG"),
    ])


def make_pan_card(path: Path) -> None:
    _card(path, "INCOME TAX DEPARTMENT - GOVT. OF INDIA (SAMPLE)", "PERMANENT ACCOUNT NUMBER CARD", "navy", [
        ("Name", "SARA LEE"),
        ("Father's Name", "PETER LEE"),
        ("Date of Birth", "05/08/1988"),
        ("PAN", "FGHIJ5678K"),
    ], size=(1100, 520))


def make_receipt(path: Path) -> None:
    img = Image.new("RGB", (600, 800), "white")
    draw = ImageDraw.Draw(img)
    lines = ["FRESH MART GROCERY", "Receipt #000123", "", "Milk 1L ........ 60.00", "Bread .......... 45.00",
             "Eggs x12 ....... 90.00", "", "TOTAL ......... 195.00", "Paid: CASH", "Thank you!"]
    for i, line in enumerate(lines):
        draw.text((40, 40 + i * 60), line, font=_font(30), fill="black")
    img.save(path)


def make_scanned_pdf(image_path: Path, path: Path) -> None:
    """A PDF whose only page is an image, like a scanned document."""
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)  # A4 in points
    page.insert_image(pymupdf.Rect(40, 40, 555, 349), filename=str(image_path))
    document.save(path)
    document.close()


def make_tax_return(path: Path) -> None:
    """A 3-page text PDF loosely modelled on an Indian ITR acknowledgement."""
    pages = [
        [
            "INCOME TAX DEPARTMENT - TESTLAND",
            "INDIAN INCOME TAX RETURN ACKNOWLEDGEMENT (SAMPLE)",
            "Assessment Year: 2025-26",
            "",
            "Name: JOHN DOE",
            "PAN: ABCDE1234F",
            "Status: Individual",
            "",
            "1. Gross Total Income ............ 5,00,000",
            "2. Total Income .................. 5,00,000",
            "3. Taxes Paid .................... 50,000",
            "4. Tax Payable / Due ............. 4,50,000",
        ],
        ["Schedule S - Details of Income from Salary", "", "Employer: TESTLAND WIDGETS PVT LTD", "Salary: 5,00,000"],
        ["Schedule TDS - Tax Deducted at Source", "", "TDS on salary: 50,000", "", "This is a sample document for testing."],
    ]
    document = pymupdf.open()
    for lines in pages:
        page = document.new_page(width=595, height=842)
        page.insert_text((50, 70), "\n".join(lines), fontsize=13, lineheight=1.6)
    document.save(path)
    document.close()


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(exist_ok=True)
    passport_png = OUTPUT_DIR / "sample_passport.png"
    make_passport(passport_png)
    make_scanned_pdf(passport_png, OUTPUT_DIR / "sample_passport_scan.pdf")
    make_tax_return(OUTPUT_DIR / "sample_tax_return.pdf")
    make_aadhaar(OUTPUT_DIR / "sample_aadhaar.png")
    make_passport_without_name(OUTPUT_DIR / "sample_passport_no_name.png")
    make_driving_licence(OUTPUT_DIR / "sample_driving_licence.png")
    make_receipt(OUTPUT_DIR / "sample_receipt.png")
    make_pan_card(OUTPUT_DIR / "sample_pan_card.png")
    for path in sorted(OUTPUT_DIR.glob("sample_*")):
        print(f"saved {path}")
