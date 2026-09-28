"""app/utils/pdf.py: PDF pages to images; images pass through untouched."""

import hashlib
import shutil
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

from app.utils.pdf import PdfConversionError, to_page_images

ENCRYPT = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "owner_pw": "owner"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_pdf(path: Path, pages: int, width: float = 595, height: float = 842, **save_kwargs) -> Path:
    document = pymupdf.open()
    for number in range(pages):
        document.new_page(width=width, height=height).insert_text((50, 70), f"Fake page {number + 1}")
    document.save(path, **save_kwargs)
    document.close()
    return path


def copy(name: str):
    return lambda ws, samples: Path(shutil.copy(samples / name, ws / name))


def jpeg(ws: Path, samples: Path) -> Path:
    Image.open(samples / "sample_passport.png").convert("RGB").save(ws / "photo.jpg", "JPEG")
    return ws / "photo.jpg"


def truncated(ws: Path, samples: Path) -> Path:
    data = (samples / "sample_tax_return.pdf").read_bytes()
    (ws / "truncated.pdf").write_bytes(data[: len(data) // 3])
    return ws / "truncated.pdf"


def write(name: str, data: bytes):
    def make(ws: Path, samples: Path) -> Path:
        (ws / name).write_bytes(data)
        return ws / name
    return make


# (make input, expected number of images; "any" = MuPDF may repair it)
CONVERTS = {
    "scanned 1-page PDF": (copy("sample_passport_scan.pdf"), 1),
    "3-page tax return PDF": (copy("sample_tax_return.pdf"), 3),
    "12-page PDF, limit 10": (lambda ws, s: text_pdf(ws / "long.pdf", 12), 10),
    "PNG passes through": (copy("sample_passport.png"), 1),
    "JPEG passes through": (jpeg, 1),
    "huge 200x200 inch page is capped": (lambda ws, s: text_pdf(ws / "huge.pdf", 1, 14400, 14400), 1),
    "owner-password-only PDF opens": (lambda ws, s: text_pdf(ws / "owner.pdf", 1, **ENCRYPT), 1),
    "truncated PDF is repaired or rejected": (truncated, "any"),
}

REJECTS = {
    "user-password PDF": lambda ws, s: text_pdf(ws / "locked.pdf", 1, user_pw="secret", **ENCRYPT),
    "garbage bytes named .pdf": write("garbage.pdf", b"%PDF-1.7\nthis is not really a pdf \x00\x01\x02"),
    "unsupported .txt": write("notes.txt", b"hello"),
}


@pytest.mark.anyio
@pytest.mark.parametrize("make_input, expected", CONVERTS.values(), ids=CONVERTS.keys())
async def test_converts(make_input, expected, samples, settings, tmp_path):
    source = make_input(tmp_path, samples)
    before = sha(source)
    try:
        images = await to_page_images(source, tmp_path, settings.pdf_render_dpi, settings.max_pdf_pages)
    except PdfConversionError:
        assert expected == "any"
        return
    assert expected == "any" or len(images) == expected
    assert source.exists() and sha(source) == before  # original kept and unchanged
    assert all(p.exists() and max(Image.open(p).size) <= 4000 for p in images)
    if source.suffix != ".pdf":
        assert images == [source]  # the same file: not re-encoded or copied


@pytest.mark.anyio
@pytest.mark.parametrize("make_input", REJECTS.values(), ids=REJECTS.keys())
async def test_rejects(make_input, samples, settings, tmp_path):
    with pytest.raises(PdfConversionError):
        await to_page_images(make_input(tmp_path, samples), tmp_path, settings.pdf_render_dpi, settings.max_pdf_pages)
