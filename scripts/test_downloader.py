"""Manual checks for app/services/downloader.py against real public test servers.

Usage:  python -m scripts.test_downloader
Needs internet access (httpbin.org, w3.org, badssl.com, nip.io). Downloads only public test files.
"""

import asyncio
import dataclasses
import time

import httpx

from app.config import get_settings
from app.services.downloader import DocumentDownloader, DownloadError
from app.utils.url_safety import resolve_public_ip
from app.utils.workspace import request_workspace

HB = "https://httpbin.org"
PDF_URL = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"

# (label, url, expect_success, settings overrides)
LIVE_CASES = [
    ("PDF over https", PDF_URL, True, {}),
    ("PNG over https", f"{HB}/image/png", True, {}),
    ("JPEG over https", f"{HB}/image/jpeg", True, {}),
    ("redirect to public PNG", f"{HB}/redirect-to?url={HB}/image/png", True, {}),
    ("HTTP 404", f"{HB}/status/404", False, {}),
    ("HTTP 500", f"{HB}/status/500", False, {}),
    ("HTML content type", f"{HB}/html", False, {}),
    ("JSON content type", f"{HB}/json", False, {}),
    ("claims image/png, body is JSON", f"{HB}/response-headers?Content-Type=image/png", False, {}),
    ("redirect to 127.0.0.1", f"{HB}/redirect-to?url=http://127.0.0.1:11434/api/tags", False, {}),
    ("redirect to cloud metadata", f"{HB}/redirect-to?url=http://169.254.169.254/latest/meta-data/", False, {}),
    ("redirect to name -> 10.0.0.1", f"{HB}/redirect-to?url=http://10.0.0.1.nip.io/", False, {}),
    ("too many redirects (5 > 3)", f"{HB}/redirect/5", False, {}),
    ("direct localhost (Ollama)", "http://localhost:11434/api/tags", False, {}),
    ("size limit via Content-Length", PDF_URL, False, {"max_download_bytes": 1000}),
    ("size limit while streaming (chunked)", f"{HB}/stream-bytes/50000?chunk_size=1000", False, {"max_download_bytes": 10000}),
    ("slow server, total timeout", f"{HB}/drip?duration=8&numbytes=8&delay=0", False, {"download_timeout_seconds": 3}),
    ("expired TLS certificate", "https://expired.badssl.com/", False, {}),
    ("TLS cert for wrong host", "https://wrong.host.badssl.com/", False, {}),
]


def _mock_downloader(content_type: str, body: bytes) -> DocumentDownloader:
    """Downloader whose HTTP layer returns a fixed response (DNS check still runs for example.com)."""
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, headers={"Content-Type": content_type}, content=body)
    )
    return DocumentDownloader(get_settings(), httpx.AsyncClient(transport=transport))


# (label, content type, body, expect_success)
MOCK_CASES = [
    ("octet-stream with PDF bytes", "application/octet-stream", b"%PDF-1.7 fake", True),
    ("octet-stream with random bytes", "application/octet-stream", b"MZ\x90\x00 exe", False),
    ("says PDF, body is PNG", "application/pdf", b"\x89PNG\r\n\x1a\n rest", False),
    ("missing content type", "", b"%PDF-1.7", False),
]


async def run_case(downloader: DocumentDownloader, label: str, url: str, expect_ok: bool, i: int) -> bool:
    with request_workspace() as ws:
        start = time.perf_counter()
        try:
            doc = await downloader.download(url, ws, f"doc{i}")
            outcome = f"OK   {doc.kind.value} {doc.size_bytes}B -> {doc.path.name}"
            ok = expect_ok
        except DownloadError as exc:
            outcome = f"ERR  {exc}"
            ok = not expect_ok
        leftovers = [p.name for p in ws.iterdir()] if not ok or not expect_ok else []
    status = "PASS" if ok and not leftovers else "FAIL"
    extra = f" leftover files: {leftovers}" if leftovers else ""
    print(f"{status}  {label:38} {outcome} ({time.perf_counter() - start:.1f}s){extra}")
    return status == "PASS"


async def check_ip_pinning() -> bool:
    """The request must go to the IP that passed the SSRF check, with the real Host/SNI."""
    seen: dict[str, str | None] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(ip=request.url.host, host=request.headers["host"], sni=request.extensions.get("sni_hostname"))
        return httpx.Response(200, headers={"Content-Type": "application/pdf"}, content=b"%PDF-1.7")

    expected_ip = str(await resolve_public_ip(httpx.URL("https://example.com/a.pdf")))
    downloader = DocumentDownloader(get_settings(), httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with request_workspace() as ws:
        await downloader.download("https://example.com/a.pdf", ws, "pin")
    await downloader.aclose()
    ok = seen == {"ip": expected_ip, "host": "example.com", "sni": "example.com"}
    print(f"{'PASS' if ok else 'FAIL'}  {'[mock] connects to validated IP':38} {seen}")
    return ok


async def main() -> None:
    base = get_settings()
    results = [await check_ip_pinning()]
    for i, (label, url, expect_ok, overrides) in enumerate(LIVE_CASES):
        downloader = DocumentDownloader(dataclasses.replace(base, **overrides))
        results.append(await run_case(downloader, label, url, expect_ok, i))
        await downloader.aclose()
    for i, (label, content_type, body, expect_ok) in enumerate(MOCK_CASES):
        downloader = _mock_downloader(content_type, body)
        results.append(await run_case(downloader, f"[mock] {label}", "https://example.com/f", expect_ok, i))
        await downloader.aclose()
    print(f"\n{sum(results)}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
