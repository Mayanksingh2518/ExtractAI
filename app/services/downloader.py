"""Safe document downloads: SSRF checks, redirect re-validation, size/time limits, type allowlist."""

import asyncio
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import httpx

from app.config import Settings
from app.utils.url_safety import UnsafeURLError, resolve_public_ip

logger = logging.getLogger(__name__)

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
GENERIC_CONTENT_TYPES = {"application/octet-stream", "binary/octet-stream"}


class FileKind(str, Enum):
    PDF = "pdf"
    PNG = "png"
    JPEG = "jpg"


# Accepted Content-Type values and file signatures ("magic bytes") per kind.
CONTENT_TYPES = {
    "application/pdf": FileKind.PDF,
    "image/png": FileKind.PNG,
    "image/jpeg": FileKind.JPEG,
    "image/jpg": FileKind.JPEG,
}
SIGNATURES = {
    FileKind.PDF: b"%PDF-",
    FileKind.PNG: b"\x89PNG\r\n\x1a\n",
    FileKind.JPEG: b"\xff\xd8\xff",
}


class DownloadError(Exception):
    """A document could not be downloaded safely. Messages never include the full URL."""


@dataclass(frozen=True)
class DownloadedDocument:
    url: str
    path: Path
    kind: FileKind
    size_bytes: int


class DocumentDownloader:
    def __init__(self, settings: Settings, http_client: httpx.AsyncClient | None = None) -> None:
        self._timeout = settings.download_timeout_seconds
        self._max_bytes = settings.max_download_bytes
        self._max_redirects = settings.max_redirects
        self._http = http_client or httpx.AsyncClient(
            follow_redirects=False,  # redirects are followed manually so each hop is re-validated
            trust_env=False,  # ignore proxy env vars: a proxy would bypass the IP pinning
            timeout=httpx.Timeout(self._timeout, connect=10.0),
            headers={"User-Agent": "ExtractAI-DocumentFetcher/0.1"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def download(self, url: str, dest_dir: Path, name: str) -> DownloadedDocument:
        """Download `url` into `dest_dir/<name>.<ext>`. Raises DownloadError on any problem."""
        current = httpx.URL(url)
        try:
            async with asyncio.timeout(self._timeout):  # cap on the whole download, not per read
                for _ in range(self._max_redirects + 1):
                    result = await self._fetch_once(current, dest_dir, name)
                    if isinstance(result, DownloadedDocument):
                        logger.info(
                            "Downloaded document: host=%s kind=%s bytes=%d",
                            current.host, result.kind.value, result.size_bytes,
                        )
                        return DownloadedDocument(url, result.path, result.kind, result.size_bytes)
                    current = result  # a redirect target, validated again on the next loop
                raise DownloadError(f"too many redirects (max {self._max_redirects})")
        except TimeoutError as exc:
            raise DownloadError(f"download timed out after {self._timeout:.0f}s") from exc
        except UnsafeURLError as exc:
            raise DownloadError(f"blocked URL: {exc}") from exc
        except httpx.HTTPError as exc:
            raise DownloadError(f"network error from host '{current.host}': {type(exc).__name__}") from exc

    async def _fetch_once(
        self, url: httpx.URL, dest_dir: Path, name: str
    ) -> DownloadedDocument | httpx.URL:
        ip = await resolve_public_ip(url)

        # Connect to the IP we validated (no second DNS lookup => no DNS rebinding),
        # while keeping the real hostname for the Host header and TLS certificate check.
        request = self._http.build_request(
            "GET",
            url.copy_with(host=str(ip)),
            headers={"Host": url.netloc.decode("ascii")},
            extensions={"sni_hostname": url.host},
        )
        response = await self._http.send(request, stream=True)
        try:
            if response.status_code in REDIRECT_STATUSES:
                location = response.headers.get("location")
                if not location:
                    raise DownloadError("redirect without a Location header")
                return url.join(location)

            if response.status_code != 200:
                raise DownloadError(f"host '{url.host}' returned HTTP {response.status_code}")

            declared_kind = self._check_content_type(response)
            declared_size = response.headers.get("content-length")
            if declared_size and declared_size.isdigit() and int(declared_size) > self._max_bytes:
                raise DownloadError(f"file is larger than {self._max_bytes} bytes")

            path, size, kind = await self._stream_to_file(response, dest_dir, name, declared_kind)
            return DownloadedDocument(str(url), path, kind, size)
        finally:
            await response.aclose()

    def _check_content_type(self, response: httpx.Response) -> FileKind | None:
        """Return the kind the server declared, or None for a generic binary type."""
        content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
        if content_type in CONTENT_TYPES:
            return CONTENT_TYPES[content_type]
        if content_type in GENERIC_CONTENT_TYPES:
            return None  # decided by the file signature alone
        raise DownloadError(f"content type '{content_type or 'missing'}' is not allowed")

    async def _stream_to_file(
        self,
        response: httpx.Response,
        dest_dir: Path,
        name: str,
        declared_kind: FileKind | None,
    ) -> tuple[Path, int, FileKind]:
        partial = dest_dir / f"{name}.part"
        size = 0
        header = b""
        try:
            with partial.open("wb") as file:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > self._max_bytes:
                        raise DownloadError(f"file is larger than {self._max_bytes} bytes")
                    if len(header) < 8:
                        header += chunk[: 8 - len(header)]
                    file.write(chunk)

            kind = _detect_kind(header)
            if kind is None:
                raise DownloadError("file content is not a PDF, PNG or JPEG")
            if declared_kind is not None and kind is not declared_kind:
                raise DownloadError("file content does not match its declared content type")

            final = dest_dir / f"{name}.{kind.value}"
            partial.rename(final)
            return final, size, kind
        except BaseException:
            partial.unlink(missing_ok=True)
            raise


def _detect_kind(header: bytes) -> FileKind | None:
    for kind, signature in SIGNATURES.items():
        if header.startswith(signature):
            return kind
    return None
