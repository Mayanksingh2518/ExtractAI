"""Manual checks for app/utils/pdf.py.

Usage:  python -m scripts.make_sample_documents && python -m scripts.test_pdf
"""

import asyncio
import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path

import pymupdf
from PIL import Image

from app.config import get_settings
from app.utils.pdf import PdfConversionError, to_page_images
from app.utils.workspace import request_workspace

SAMPLES = Path("documents")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text_pdf(path: Path, pages: int, width: float = 595, height: float = 842, **save_kwargs) -> Path:
    document = pymupdf.open()
    for number in range(pages):
        document.new_page(width=width, height=height).insert_text((50, 70), f"Fake page {number + 1}")
    document.save(path, **save_kwargs)
    document.close()
    return path


def _copy(name: str) -> Callable[[Path], Path]:
    return lambda ws: Path(shutil.copy(SAMPLES / name, ws / name))


def _truncated(ws: Path) -> Path:
    data = (SAMPLES / "sample_tax_return.pdf").read_bytes()
    path = ws / "truncated.pdf"
    path.write_bytes(data[: len(data) // 3])
    return path


def _garbage(ws: Path) -> Path:
    path = ws / "garbage.pdf"
    path.write_bytes(b"%PDF-1.7\nthis is not really a pdf \x00\x01\x02")
    return path


def _text_file(ws: Path) -> Path:
    path = ws / "notes.txt"
    path.write_text("hello")
    return path


ENCRYPT = {"encryption": pymupdf.PDF_ENCRYPT_AES_256, "owner_pw": "owner"}

# (label, make input file in workspace, expected number of images or None for an error)
CASES = [
    ("scanned 1-page PDF", _copy("sample_passport_scan.pdf"), 1),
    ("3-page tax return PDF", _copy("sample_tax_return.pdf"), 3),
    ("12-page PDF, limit 10", lambda ws: _text_pdf(ws / "long.pdf", 12), 10),
    ("PNG passes through", _copy("sample_passport.png"), 1),
    ("JPEG passes through", lambda ws: _jpeg(ws), 1),
    ("huge 200x200in page is capped", lambda ws: _text_pdf(ws / "huge.pdf", 1, 14400, 14400), 1),
    ("owner-password-only PDF (opens)", lambda ws: _text_pdf(ws / "owner.pdf", 1, **ENCRYPT), 1),
    ("user-password PDF", lambda ws: _text_pdf(ws / "locked.pdf", 1, user_pw="secret", **ENCRYPT), None),
    ("garbage bytes named .pdf", _garbage, None),
    ("truncated PDF", _truncated, "any"),
    ("unsupported .txt", _text_file, None),
]


def _jpeg(ws: Path) -> Path:
    path = ws / "photo.jpg"
    Image.open(SAMPLES / "sample_passport.png").convert("RGB").save(path, "JPEG")
    return path


async def main() -> None:
    settings = get_settings()
    passed = 0
    for label, make_input, expected in CASES:
        with request_workspace() as ws:
            source = make_input(ws)
            before = _sha(source)
            try:
                images = await to_page_images(source, ws, settings.pdf_render_dpi, settings.max_pdf_pages)
            except PdfConversionError as exc:
                ok = expected is None or expected == "any"
                print(f"{'PASS' if ok else 'FAIL'}  {label:34} ERR {exc}")
                passed += ok
                continue

            sizes = [Image.open(p).size for p in images]
            checks = {
                "count": expected == "any" or len(images) == expected,
                "original kept + unchanged": source.exists() and _sha(source) == before,
                "all images exist": all(p.exists() for p in images),
                "max side <= 4000px": all(max(s) <= 4000 for s in sizes),
            }
            if source.suffix != ".pdf":
                checks["not re-processed (same file)"] = images == [source]
            ok = all(checks.values())
            failed = [name for name, good in checks.items() if not good]
            print(
                f"{'PASS' if ok else 'FAIL'}  {label:34} {len(images)} image(s), "
                f"first {sizes[0][0]}x{sizes[0][1]}{'  failed: ' + ', '.join(failed) if failed else ''}"
            )
            passed += ok
    print(f"\n{passed}/{len(CASES)} passed")


if __name__ == "__main__":
    asyncio.run(main())
