"""End-to-end POST /document-check with the real model on the FAKE sample documents.

SSRF protection blocks localhost, so the samples can't be served by a local web server.
Instead, SampleDownloader (test-only, never in app/) serves documents/ for the fake host
"samples.test" and sends every other URL through the REAL DocumentDownloader and its SSRF checks.
"""

import dataclasses
import json
import shutil
import tempfile
from pathlib import Path

import httpx
import pytest

from app.api.document_check import get_processor
from app.config import get_settings
from app.main import app
from app.pipelines.base import BaseDocumentPipeline, ExtractionError
from app.pipelines.registry import PipelineRegistry
from app.services.classifier import DocumentClassifier
from app.services.document_processor import DocumentProcessor, ModelUnavailableError
from app.services.downloader import DocumentDownloader, DownloadedDocument, DownloadError, FileKind
from app.services.ollama import OllamaClient

pytestmark = pytest.mark.anyio

SAMPLES = Path("documents")
TEST_HOST = "samples.test"
W3_PDF = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
KINDS = {".pdf": FileKind.PDF, ".png": FileKind.PNG, ".jpg": FileKind.JPEG}


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


class CountingDownloader(SampleDownloader):
    calls = 0

    async def download(self, url, dest_dir, name):
        self.calls += 1
        return await super().download(url, dest_dir, name)


class FailingPassportPipeline(BaseDocumentPipeline):
    document_type = "passport"

    async def extract(self, page_images):
        raise ExtractionError("passport extraction failed: Ollama request timed out")


class BrokenDownloader(DocumentDownloader):
    async def download(self, url, dest_dir, name):
        raise RuntimeError("secret document text that must not leak")


URLS = [
    sample("sample_passport.png"),          # 0  John Doe
    sample("sample_aadhaar.png"),           # 1  MARIA DOE
    sample("sample_tax_return.pdf"),        # 2  JOHN DOE -> same group as 0
    sample("sample_receipt.png"),           # 3  unknown, no owner
    sample("sample_passport_scan.pdf"),     # 4  John Doe
    sample("sample_aadhaar_front.png"),     # 5  RAVI SHARMA, address null
    sample("sample_driving_licence.png"),   # 6  unknown, but has an owner
    sample("sample_pan_card.png"),          # 7  panCard (Stage 14)
    sample("sample_passport_no_name.png"),  # 8  passport, no owner
    "http://127.0.0.1:11434/api/tags",      # 9  real downloader: SSRF blocked
    sample("missing.pdf"),                  # 10 404
    sample("broken.pdf"),                   # 11 not a readable PDF
    W3_PDF,                                 # 12 real public download: a "Dummy PDF file" -> unknown
]
PASSPORT = {"passportNumber": "AB1234567", "dateOfBirth": "1985-05-15", "expiryDate": "2030-12-31"}
# sourceIndex -> (owner, documentType, data, start of the error or None)
EXPECTED = {
    0: ("John Doe", "passport", PASSPORT, None),
    1: ("MARIA DOE", "idCard", {"aadharNumber": "2345-6789-0123", "dateOfBirth": "1990-01-01",
                                "address": "123, Main Street, Testcity, Teststate 400001"}, None),
    2: ("John Doe", "taxReturn", {"assessmentYear": 2025, "taxPayerName": "JOHN DOE", "totalIncome": "500000",
                                  "taxPaid": "50000", "taxDue": "450000"}, None),
    3: (None, "unknown", None, None),
    4: ("John Doe", "passport", PASSPORT, None),
    5: ("RAVI SHARMA", "idCard", {"aadharNumber": "9876-5432-1098", "dateOfBirth": "1975-11-23", "address": None}, None),
    6: ("ALEX KUMAR", "unknown", None, None),
    7: ("Sara Lee", "panCard", {"panNumber": "FGHIJ5678K", "dateOfBirth": "1988-08-05", "fatherName": "PETER LEE"}, None),
    8: (None, "passport", {"passportNumber": "CD7654321", "dateOfBirth": "1979-02-02", "expiryDate": "2029-01-01"}, None),
    9: (None, "unknown", None, "download failed: blocked URL"),
    10: (None, "unknown", None, "download failed: host 'samples.test' returned HTTP 404"),
    11: (None, "unknown", None, "could not read document"),
    12: (None, "unknown", None, None),
}


def by_index(owners: list[dict]) -> dict[int, tuple[str | None, dict]]:
    return {d["sourceIndex"]: (g["ownerName"], d) for g in owners for d in g["documents"]}


def fold(name: str | None) -> str:
    return (name or "").casefold()  # the model may print "John Doe" or "JOHN DOE"; grouping ignores case


@pytest.fixture(scope="module")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="module")
async def main_request(anyio_backend) -> dict:
    """The 13-URL request, run once for every test in this module."""
    settings = get_settings()
    workspaces = lambda: {p.name for p in Path(tempfile.gettempdir()).glob("extractai-*")}  # noqa: E731
    async with OllamaClient.from_settings(settings) as ollama:
        if not await ollama.is_model_available():
            pytest.skip("Ollama model not available")
        downloader = SampleDownloader(settings)
        processor = DocumentProcessor(downloader, DocumentClassifier(ollama), PipelineRegistry.build(ollama), settings)
        before = workspaces()
        app.dependency_overrides[get_processor] = lambda: processor
        # ASGITransport calls the app in-process on this event loop (no server, no lifespan: the processor is injected).
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=None) as c:
            response = await c.post("/document-check", json={"documentUrls": URLS})
            too_few = await c.post("/document-check", json={"documentUrls": URLS[:9]})
        app.dependency_overrides.clear()
        await downloader.aclose()
    return {"status": response.status_code, "body": response.json(), "text": response.text,
            "too_few": too_few.status_code, "workspaces_left": workspaces() - before}


@pytest.mark.model
@pytest.mark.network
class TestMainRequest:
    async def test_status_and_validation(self, main_request):
        assert main_request["status"] == 200
        assert main_request["too_few"] == 422

    async def test_groups_in_first_seen_order_null_last(self, main_request):
        owners = [fold(g["ownerName"]) or None for g in main_request["body"]]
        assert owners == ["john doe", "maria doe", "ravi sharma", "alex kumar", "sara lee", None]

    async def test_every_document_once_and_john_doe_grouped(self, main_request):
        body = main_request["body"]
        assert sorted(by_index(body)) == list(range(len(URLS)))
        john = next(g for g in body if fold(g["ownerName"]) == "john doe")
        assert [d["sourceIndex"] for d in john["documents"]] == [0, 2, 4]

    @pytest.mark.parametrize("index", EXPECTED)
    async def test_document(self, index, main_request):
        owner, doc_type, data, error = EXPECTED[index]
        got_owner, d = by_index(main_request["body"])[index]
        assert fold(got_owner) == fold(owner)
        assert (d["documentType"], d["data"]) == (doc_type, data)
        assert d["error"] is None if error is None else d["error"].startswith(error)

    async def test_no_urls_echoed_and_brief_field_names(self, main_request):
        text = main_request["text"]
        assert not any(u in text for u in URLS) and "/api/tags" not in text
        assert all(k in text for k in ('"ownerName"', '"documents"', '"documentType"', '"documentName"', '"data"'))

    async def test_workspace_deleted(self, main_request):
        assert main_request["workspaces_left"] == set()


# --- failure modes (fast) ---

@pytest.mark.model
async def test_extraction_failure_keeps_type_and_owner(ollama, samples, settings):
    downloader = SampleDownloader(settings)
    processor = DocumentProcessor(downloader, DocumentClassifier(ollama),
                                  PipelineRegistry([FailingPassportPipeline(ollama)]), settings)
    docs = by_index([g.model_dump(mode="json") for g in
                     await processor.process([sample("sample_passport.png"), sample("sample_aadhaar.png")])])
    await downloader.aclose()
    owner, d = docs[0]
    assert (d["documentType"], fold(owner), d["data"]) == ("passport", "john doe", None)
    assert d["error"] == "passport extraction failed: Ollama request timed out"
    owner, d = docs[1]  # a type with no pipeline here -> data null, no error
    assert (d["documentType"], d["data"], d["error"]) == ("idCard", None, None)


async def test_ollama_down_raises_before_any_download(settings):
    down = OllamaClient.from_settings(dataclasses.replace(settings, ollama_host="http://localhost:1"))
    counting = CountingDownloader(settings)
    processor = DocumentProcessor(counting, DocumentClassifier(down), PipelineRegistry.build(down), settings)
    try:
        with pytest.raises(ModelUnavailableError):
            await processor.process(URLS[:2])
        assert counting.calls == 0
    finally:
        await down.aclose()
        await counting.aclose()


@pytest.mark.model
async def test_unexpected_exception_is_internal_error_and_leaks_nothing(ollama, settings):
    downloader = BrokenDownloader(settings)
    processor = DocumentProcessor(downloader, DocumentClassifier(ollama), PipelineRegistry.build(ollama), settings)
    groups = [g.model_dump(mode="json") for g in await processor.process(URLS[:2])]
    await downloader.aclose()
    assert [d["error"] for d in groups[0]["documents"]] == ["internal error", "internal error"]
    assert "secret" not in json.dumps(groups)
