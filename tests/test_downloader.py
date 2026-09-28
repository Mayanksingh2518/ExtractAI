"""app/services/downloader.py: safe downloads (SSRF, limits, allowlist) against real public test servers."""

import dataclasses

import httpx
import pytest

from app.services.downloader import DocumentDownloader, DownloadError
from app.utils.url_safety import resolve_public_ip

pytestmark = [pytest.mark.anyio, pytest.mark.network]  # every case resolves DNS; most use public servers

HB = "https://httpbin.org"
PDF_URL = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"

# label: (url, expect success, settings overrides)
LIVE = {
    "PDF over https": (PDF_URL, True, {}),
    "PNG over https": (f"{HB}/image/png", True, {}),
    "JPEG over https": (f"{HB}/image/jpeg", True, {}),
    "redirect to public PNG": (f"{HB}/redirect-to?url={HB}/image/png", True, {}),
    "HTTP 404": (f"{HB}/status/404", False, {}),
    "HTTP 500": (f"{HB}/status/500", False, {}),
    "HTML content type": (f"{HB}/html", False, {}),
    "JSON content type": (f"{HB}/json", False, {}),
    "claims image/png, body is JSON": (f"{HB}/response-headers?Content-Type=image/png", False, {}),
    "redirect to 127.0.0.1": (f"{HB}/redirect-to?url=http://127.0.0.1:11434/api/tags", False, {}),
    "redirect to cloud metadata": (f"{HB}/redirect-to?url=http://169.254.169.254/latest/meta-data/", False, {}),
    "redirect to a name resolving to 10.0.0.1": (f"{HB}/redirect-to?url=http://10.0.0.1.nip.io/", False, {}),
    "too many redirects (5 > 3)": (f"{HB}/redirect/5", False, {}),
    "direct localhost (Ollama)": ("http://localhost:11434/api/tags", False, {}),
    "size limit via Content-Length": (PDF_URL, False, {"max_download_bytes": 1000}),
    "size limit while streaming": (f"{HB}/stream-bytes/50000?chunk_size=1000", False, {"max_download_bytes": 10000}),
    "slow server hits total timeout": (f"{HB}/drip?duration=8&numbytes=8&delay=0", False, {"download_timeout_seconds": 3}),
    "expired TLS certificate": ("https://expired.badssl.com/", False, {}),
    "TLS certificate for wrong host": ("https://wrong.host.badssl.com/", False, {}),
}

# label: (content type, body, expect success); the HTTP layer is mocked, the SSRF DNS check is real
MOCKED = {
    "octet-stream with PDF bytes": ("application/octet-stream", b"%PDF-1.7 fake", True),
    "octet-stream with random bytes": ("application/octet-stream", b"MZ\x90\x00 exe", False),
    "says PDF, body is PNG": ("application/pdf", b"\x89PNG\r\n\x1a\n rest", False),
    "missing content type": ("", b"%PDF-1.7", False),
}


async def download(downloader: DocumentDownloader, url: str, expect_ok: bool, workspace) -> None:
    try:
        doc = await downloader.download(url, workspace, "doc")
        assert expect_ok, f"downloaded {doc.kind.value}, expected an error"
        assert doc.path.exists() and doc.size_bytes > 0
    except DownloadError:
        assert not expect_ok
        assert list(workspace.iterdir()) == []  # partial files deleted
    finally:
        await downloader.aclose()


@pytest.mark.parametrize("url, expect_ok, overrides", LIVE.values(), ids=LIVE.keys())
async def test_live(url, expect_ok, overrides, settings, tmp_path):
    await download(DocumentDownloader(dataclasses.replace(settings, **overrides)), url, expect_ok, tmp_path)


@pytest.mark.parametrize("content_type, body, expect_ok", MOCKED.values(), ids=MOCKED.keys())
async def test_content_checks(content_type, body, expect_ok, settings, tmp_path):
    transport = httpx.MockTransport(lambda r: httpx.Response(200, headers={"Content-Type": content_type}, content=body))
    await download(DocumentDownloader(settings, httpx.AsyncClient(transport=transport)),
                   "https://example.com/f", expect_ok, tmp_path)


async def test_connects_to_the_checked_ip_with_real_host_and_sni(settings, tmp_path):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(ip=request.url.host, host=request.headers["host"], sni=request.extensions.get("sni_hostname"))
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=b"%PDF-1.7")

    expected_ip = str(await resolve_public_ip(httpx.URL("https://example.com/a.pdf")))
    downloader = DocumentDownloader(settings, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    await download(downloader, "https://example.com/a.pdf", True, tmp_path)
    assert seen == {"ip": expected_ip, "host": "example.com", "sni": "example.com"}
