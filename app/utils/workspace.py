import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def request_workspace() -> Iterator[Path]:
    """A private temp directory (mode 0700) for one request, always deleted afterwards."""
    path = Path(tempfile.mkdtemp(prefix="extractai-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
