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


def make_passport(path: Path) -> None:
    img = Image.new("RGB", (1000, 600), "white")
    draw = ImageDraw.Draw(img)
    draw.rectangle([10, 10, 990, 590], outline="black", width=4)
    draw.text((40, 40), "REPUBLIC OF TESTLAND", font=_font(40), fill="black")
    draw.text((40, 100), "PASSPORT", font=_font(56), fill="darkblue")
    rows = [
        ("Surname", "DOE"),
        ("Given names", "JOHN"),
        ("Passport No.", "AB1234567"),
        ("Date of birth", "15 MAY 1985"),
        ("Date of expiry", "31 DEC 2030"),
    ]
    for i, (label, value) in enumerate(rows):
        draw.text((40, 200 + i * 70), label, font=_font(26), fill="gray")
        draw.text((330, 200 + i * 70), value, font=_font(34), fill="black")
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
    for path in sorted(OUTPUT_DIR.glob("sample_*")):
        print(f"saved {path}")
