"""Turn a downloaded document into the page images the vision model reads.

PDFs are rendered page by page to PNG (the original PDF is kept).
PNG/JPEG files are already images and are returned untouched.
"""

import asyncio
import logging
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)

# MuPDF prints repair/syntax messages straight to stderr, bypassing our logging;
# keep them quiet (failures still surface as exceptions below).
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.TOOLS.mupdf_display_warnings(False)

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
# Guard against PDFs that declare huge pages (memory bomb). Ollama downsizes anything
# above ~2 MP anyway, so nothing useful is lost.
MAX_RENDER_SIDE_PX = 4000


class PdfConversionError(Exception):
    """The document could not be turned into images. Messages never include document text."""


async def to_page_images(file_path: Path, out_dir: Path, dpi: int, max_pages: int) -> list[Path]:
    """Return the images to send to the model for this document, in page order."""
    suffix = file_path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return [file_path]
    if suffix == ".pdf":
        # Rendering is CPU-bound: run it in a thread so the event loop stays responsive.
        return await asyncio.to_thread(render_pdf_pages, file_path, out_dir, dpi, max_pages)
    raise PdfConversionError(f"unsupported file type '{suffix}'")


def render_pdf_pages(pdf_path: Path, out_dir: Path, dpi: int, max_pages: int) -> list[Path]:
    try:
        document = pymupdf.open(pdf_path)
    except Exception as exc:  # pymupdf raises FileDataError / RuntimeError for broken files
        raise PdfConversionError("file is not a readable PDF") from exc

    with document:
        if document.needs_pass:
            raise PdfConversionError("PDF is password-protected")
        if document.page_count == 0:
            raise PdfConversionError("PDF has no pages")
        if document.page_count > max_pages:
            logger.info("PDF has %d pages; rendering the first %d", document.page_count, max_pages)

        images: list[Path] = []
        for index in range(min(document.page_count, max_pages)):
            page = document[index]
            page_dpi = _safe_dpi(page.rect, dpi)
            try:
                pixmap = page.get_pixmap(dpi=page_dpi)
            except Exception as exc:
                raise PdfConversionError(f"could not render page {index + 1}") from exc
            image_path = out_dir / f"{pdf_path.stem}_page{index + 1}.png"
            pixmap.save(image_path)
            images.append(image_path)
        return images


def _safe_dpi(rect: pymupdf.Rect, dpi: int) -> int:
    """Lower the DPI if the page would render wider/taller than MAX_RENDER_SIDE_PX."""
    longest_side_inches = max(rect.width, rect.height) / 72  # PDF units are 1/72 inch
    if longest_side_inches * dpi <= MAX_RENDER_SIDE_PX:
        return dpi
    return max(1, int(MAX_RENDER_SIDE_PX / longest_side_inches))
