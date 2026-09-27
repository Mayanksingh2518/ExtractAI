"""End-to-end checks for POST /document-check on the FAKE sample documents.

Usage:  python -m scripts.make_sample_documents && caffeinate -i python -u -m scripts.test_document_check
Needs Ollama with OLLAMA_MODEL pulled, and internet for the w3.org PDF.

SSRF protection blocks localhost, so the samples can't be served by a local web server.
Instead, SampleDownloader (test-only, never in app/) serves documents/ for the fake host
"samples.test" and sends every other URL through the REAL DocumentDownloader and its SSRF checks.
"""

import asyncio
import dataclasses
import json
import shutil
import tempfile
import time
from pathlib import Path

import httpx

from app.api.document_check import get_processor
from app.config import get_settings
from app.main import app
from app.pipelines.base import BaseDocumentPipeline, ExtractionError
from app.pipelines.registry import PipelineRegistry
from app.services.classifier import DocumentClassifier
from app.services.document_processor import DocumentProcessor
from app.services.downloader import DocumentDownloader, DownloadedDocument, DownloadError, FileKind
from app.services.ollama import OllamaClient

SAMPLES = Path("documents")
TEST_HOST = "samples.test"
W3_PDF = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
KINDS = {".pdf": FileKind.PDF, ".png": FileKind.PNG, ".jpg": FileKind.JPEG}
results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")


def sample(name: str) -> str:
    return f"https://{TEST_HOST}/{name}"


class SampleDownloader(DocumentDownloader):
    """Serves documents/ for https://samples.test/<file>; everything else uses the real downloader."""

    async def download(self, url: str, dest_dir: Path, name: str) -> DownloadedDocument:
        parsed = httpx.URL(url)
        if parsed.host != TEST_HOST:
            return await super().download(url, dest_dir, name)
        file_name = parsed.path.lstrip("/")
        dest = dest_dir / f"{name}{Path(file_name).suffix}"
        if file_name == "broken.pdf":  # passes the downloader's %PDF- check but isn't a real PDF
            dest.write_bytes(b"%PDF-1.4\nthis is not really a pdf")
        elif (SAMPLES / file_name).is_file():
            shutil.copyfile(SAMPLES / file_name, dest)
        else:
            raise DownloadError(f"host '{TEST_HOST}' returned HTTP 404")
        return DownloadedDocument(url, dest, KINDS[dest.suffix], dest.stat().st_size)


class FailingPassportPipeline(BaseDocumentPipeline):
    document_type = "passport"

    async def extract(self, page_images):
        raise ExtractionError("passport extraction failed: Ollama request timed out")


class BrokenDownloader(DocumentDownloader):
    async def download(self, url, dest_dir, name):
        raise RuntimeError("secret document text that must not leak")


def leftover_workspaces() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("extractai-*")}


def by_index(owners: list[dict]) -> dict[int, tuple[str | None, dict]]:
    return {d["sourceIndex"]: (g["ownerName"], d) for g in owners for d in g["documents"]}


async def main_request(processor: DocumentProcessor) -> None:
    urls = [
        sample("sample_passport.png"),          # 0  John Doe
        sample("sample_aadhaar.png"),           # 1  MARIA DOE
        sample("sample_tax_return.pdf"),        # 2  JOHN DOE -> same group as 0
        sample("sample_receipt.png"),           # 3  unknown, no owner
        sample("sample_passport_scan.pdf"),     # 4  John Doe
        sample("sample_aadhaar_front.png"),     # 5  RAVI SHARMA, address null
        sample("sample_driving_licence.png"),   # 6  unknown, but has an owner
        sample("sample_pan_card.png"),          # 7  unknown, but has an owner
        sample("sample_passport_no_name.png"),  # 8  passport, no owner
        "http://127.0.0.1:11434/api/tags",      # 9  real downloader: SSRF blocked
        sample("missing.pdf"),                  # 10 404
        sample("broken.pdf"),                   # 11 not a readable PDF
        W3_PDF,                                 # 12 real public download: a "Dummy PDF file" -> unknown
    ]
    before = leftover_workspaces()
    app.dependency_overrides[get_processor] = lambda: processor
    # ASGITransport calls the app in-process on this event loop (no server, no lifespan: the processor is injected).
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=None) as client:
        start = time.perf_counter()
        response = await client.post("/document-check", json={"documentUrls": urls})
        elapsed = time.perf_counter() - start
        check("13 URLs -> HTTP 200", response.status_code == 200, f"{response.status_code} in {elapsed:.0f}s")
        body = response.json()
        print(json.dumps(body, indent=2))

        owners = [g["ownerName"] for g in body]
        check("groups in first-seen order, null last",
              owners == ["John Doe", "MARIA DOE", "RAVI SHARMA", "ALEX KUMAR", "Sara Lee", None], str(owners))
        docs = by_index(body)
        check("every document appears once, sourceIndex 0-12", sorted(docs) == list(range(len(urls))), str(sorted(docs)))
        john = next(g for g in body if g["ownerName"] == "John Doe")
        check("John Doe: passport PNG + tax return + passport PDF",
              [d["sourceIndex"] for d in john["documents"]] == [0, 2, 4])

        def expect(i: int, owner, doc_type: str, data, error_start: str | None = None) -> None:
            got_owner, d = docs[i]
            same_owner = (got_owner or "").casefold() == (owner or "").casefold()
            error_ok = d["error"] is None if error_start is None else (d["error"] or "").startswith(error_start)
            ok = same_owner and d["documentType"] == doc_type and d["data"] == data and error_ok
            check(f"[{i:2}] {doc_type:9} owner={owner!r}", ok, "" if ok else f"got owner={got_owner!r} {d}")

        passport = {"passportNumber": "AB1234567", "dateOfBirth": "1985-05-15", "expiryDate": "2030-12-31"}
        expect(0, "John Doe", "passport", passport)
        expect(1, "MARIA DOE", "idCard", {"aadharNumber": "2345-6789-0123", "dateOfBirth": "1990-01-01",
                                          "address": "123, Main Street, Testcity, Teststate 400001"})
        expect(2, "John Doe", "taxReturn", {"assessmentYear": 2025, "taxPayerName": "JOHN DOE", "totalIncome": "500000",
                                            "taxPaid": "50000", "taxDue": "450000"})
        expect(3, None, "unknown", None)
        expect(4, "John Doe", "passport", passport)
        expect(5, "RAVI SHARMA", "idCard", {"aadharNumber": "9876-5432-1098", "dateOfBirth": "1975-11-23", "address": None})
        expect(6, "ALEX KUMAR", "unknown", None)
        expect(7, "Sara Lee", "unknown", None)
        expect(8, None, "passport", {"passportNumber": "CD7654321", "dateOfBirth": "1979-02-02", "expiryDate": "2029-01-01"})
        expect(9, None, "unknown", None, "download failed: blocked URL")
        expect(10, None, "unknown", None, "download failed: host 'samples.test' returned HTTP 404")
        expect(11, None, "unknown", None, "could not read document")
        expect(12, None, "unknown", None)

        text = response.text
        check("no full URL echoed in the response", not any(u in text for u in urls) and "/api/tags" not in text)
        check("brief's field names present", all(k in text for k in ('"ownerName"', '"documents"', '"documentType"', '"documentName"', '"data"')))

        too_few = await client.post("/document-check", json={"documentUrls": urls[:9]})
        check("9 URLs still -> 422", too_few.status_code == 422, str(too_few.status_code))
    app.dependency_overrides.clear()
    check("temp workspace deleted", leftover_workspaces() == before, str(leftover_workspaces() - before))


async def failure_modes(settings, ollama: OllamaClient, downloader: DocumentDownloader) -> None:
    urls = [sample("sample_passport.png"), sample("sample_aadhaar.png")]

    # Extraction fails after classification succeeded: keep type/owner, data null, error set.
    processor = DocumentProcessor(downloader, DocumentClassifier(ollama), PipelineRegistry([FailingPassportPipeline(ollama)]), settings)
    docs = by_index([g.model_dump(mode="json") for g in await processor.process(urls)])
    owner, d = docs[0]
    check("extraction failure keeps type + owner, data null, error set",
          d["documentType"] == "passport" and (owner or "").casefold() == "john doe" and d["data"] is None
          and d["error"] == "passport extraction failed: Ollama request timed out", str(d))
    owner, d = docs[1]
    check("type without a pipeline -> data null, no error", d["documentType"] == "idCard" and d["data"] is None and d["error"] is None, str(d))

    # Ollama down: every document fails at classification, the request still returns.
    down = OllamaClient.from_settings(dataclasses.replace(settings, ollama_host="http://localhost:1"))
    processor = DocumentProcessor(downloader, DocumentClassifier(down), PipelineRegistry.build(down), settings)
    groups = [g.model_dump(mode="json") for g in await processor.process(urls)]
    check("Ollama down -> all in null group with a classification error",
          len(groups) == 1 and groups[0]["ownerName"] is None
          and all(d["error"].startswith("classification failed: Could not reach Ollama") for d in groups[0]["documents"]), str(groups))
    await down.aclose()

    # A bug (unexpected exception) -> "internal error", no exception text leaked, batch continues.
    processor = DocumentProcessor(BrokenDownloader(settings), DocumentClassifier(ollama), PipelineRegistry.build(ollama), settings)
    groups = [g.model_dump(mode="json") for g in await processor.process(urls)]
    check("unexpected exception -> 'internal error' for each document",
          [d["error"] for d in groups[0]["documents"]] == ["internal error", "internal error"]
          and "secret" not in json.dumps(groups), str(groups))


async def main() -> None:
    settings = get_settings()
    async with OllamaClient.from_settings(settings) as ollama:
        downloader = SampleDownloader(settings)
        processor = DocumentProcessor(downloader, DocumentClassifier(ollama), PipelineRegistry.build(ollama), settings)
        await main_request(processor)
        print()
        await failure_modes(settings, ollama, downloader)
        await downloader.aclose()
    print(f"\n{sum(results)}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
