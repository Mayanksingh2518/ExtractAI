"""Save an uploaded file into the request's private workspace, with the same checks as downloads.

The client's file name and declared content type are never trusted, used or logged: the type
is decided by the file's first bytes, and the file is saved as <name>.<pdf|png|jpg>.
"""

import shutil
from pathlib import Path
from typing import BinaryIO

from app.services.downloader import FileKind, detect_kind

CHUNK_BYTES = 1024 * 1024


class UploadError(Exception):
    """An uploaded file was rejected. Messages never include file names or contents."""


def save_upload(source: BinaryIO, dest_dir: Path, name: str, max_bytes: int) -> tuple[Path, FileKind]:
    """Copy `source` to dest_dir/<name>.<ext>. Blocking: run it in a thread."""
    partial = dest_dir / f"{name}.part"
    size = 0
    header = b""
    try:
        source.seek(0)
        with partial.open("wb") as out:
            while chunk := source.read(CHUNK_BYTES):
                size += len(chunk)
                if size > max_bytes:
                    raise UploadError(f"file is larger than {max_bytes} bytes")
                if len(header) < 8:
                    header += chunk[: 8 - len(header)]
                out.write(chunk)
        if size == 0:
            raise UploadError("file is empty")
        kind = detect_kind(header)
        if kind is None:
            raise UploadError("file content is not a PDF, PNG or JPEG")
        final = dest_dir / f"{name}.{kind.value}"
        shutil.move(partial, final)
        return final, kind
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
