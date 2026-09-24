"""Generate FAKE sample documents for local testing (no real personal data).

Usage:  python -m scripts.make_sample_documents
Writes to documents/ (gitignored).
"""

from pathlib import Path

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


if __name__ == "__main__":
    OUTPUT_DIR.mkdir(exist_ok=True)
    passport_path = OUTPUT_DIR / "sample_passport.png"
    make_passport(passport_path)
    print(f"saved {passport_path}")
