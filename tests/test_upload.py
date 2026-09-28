"""Stage 18: POST /document-check/upload and app/services/uploads.py."""

import dataclasses
import io

import httpx
import pymupdf
import pytest
from PIL import Image

from app.api import document_check
from app.api.document_check import get_processor
from app.main import app
from app.pipelines.registry import PipelineRegistry
from app.schemas.classification import Classification, DocumentType
from app.services.classifier import DocumentClassifier
from app.services.document_processor import DocumentProcessor
from app.services.downloader import FileKind
from app.services.uploads import UploadError, save_upload

pytestmark = pytest.mark.anyio


def _real_files() -> tuple[bytes, bytes, bytes]:
    """Tiny but real PDF, PNG and JPEG files (they must survive page rendering)."""
    document = pymupdf.open()
    document.new_page(width=200, height=200).insert_text((20, 40), "Fake page")
    pdf = document.tobytes()
    images = []
    for fmt in ("PNG", "JPEG"):
        buffer = io.BytesIO()
        Image.new("RGB", (60, 40), "white").save(buffer, fmt)
        images.append(buffer.getvalue())
    return pdf, *images


PDF, PNG, JPEG = _real_files()


# --- save_upload ---

@pytest.mark.parametrize("data, kind", [(PDF, FileKind.PDF), (PNG, FileKind.PNG), (JPEG, FileKind.JPEG)])
async def test_save_upload_names_file_by_its_content(data, kind, tmp_path):
    path, got = save_upload(io.BytesIO(data), tmp_path, "document", 1000)
    assert got is kind and path == tmp_path / f"document.{kind.value}" and path.read_bytes() == data


@pytest.mark.parametrize("data, max_bytes, message", [
    (b"hello, not a document", 1000, "not a PDF, PNG or JPEG"),
    (b"", 1000, "empty"),
    (PDF + b"x" * 5000, len(PDF) + 100, "larger than"),
], ids=["text file", "empty file", "too large"])
async def test_save_upload_rejects(data, max_bytes, message, tmp_path):
    with pytest.raises(UploadError, match=message):
        save_upload(io.BytesIO(data), tmp_path, "document", max_bytes)
    assert list(tmp_path.iterdir()) == []  # no partial file left


# --- the endpoint, with a fake model ---

class FakeClassifier:
    def __init__(self, ready: bool = True) -> None:
        self.ready = ready

    async def is_ready(self) -> bool:
        return self.ready

    async def classify(self, pages):
        return Classification(documentName="Receipt", documentType=DocumentType.UNKNOWN, ownerName=None)


class FakeRegistry:
    async def extract(self, document_type, pages):
        return None


@pytest.fixture
def use_processor(settings):
    def use(ready: bool = True, **overrides) -> None:
        processor = DocumentProcessor(None, FakeClassifier(ready), FakeRegistry(), dataclasses.replace(settings, **overrides))
        app.dependency_overrides[get_processor] = lambda: processor
    use()
    return use


@pytest.fixture
async def client():
    app.state.rate_limiter, app.state.api_keys = None, ()  # restored by conftest
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def files(*contents: bytes, name: str = "doc.bin") -> list:
    return [("files", (name, data, "application/octet-stream")) for data in contents]


def docs(response: httpx.Response) -> dict[int, dict]:
    return {d["sourceIndex"]: d for g in response.json() for d in g["documents"]}


class TrackedBody:
    """A request body that records whether the server read any of it."""

    def __init__(self, data: bytes) -> None:
        self.data, self.read = data, False

    async def __aiter__(self):
        self.read = True
        yield self.data


def multipart(*contents: bytes) -> tuple[bytes, str]:
    request = httpx.Request("POST", "http://test", files=files(*contents))
    return request.read(), request.headers["content-type"]


async def test_valid_uploads_are_processed_in_order(client, use_processor, workspaces):
    before = workspaces()
    r = await client.post("/document-check/upload", files=files(PDF, PNG, JPEG))
    assert r.status_code == 200
    assert sorted(docs(r)) == [0, 1, 2] and all(d["error"] is None for d in docs(r).values())
    assert workspaces() == before


async def test_bad_file_fails_alone(client, use_processor):
    r = await client.post("/document-check/upload", files=files(PDF, b"just text", PNG))
    d = docs(r)
    assert r.status_code == 200
    assert d[1]["error"] == "upload rejected: file content is not a PDF, PNG or JPEG"
    assert d[0]["error"] is None and d[2]["error"] is None


async def test_file_over_the_per_file_limit_fails_alone(client, use_processor):
    use_processor(max_download_bytes=len(PDF) + 100)
    r = await client.post("/document-check/upload", files=files(PDF, PDF + b"x" * 500))
    assert docs(r)[1]["error"] == f"upload rejected: file is larger than {len(PDF) + 100} bytes"
    assert docs(r)[0]["error"] is None


async def test_file_names_are_never_echoed_or_logged(client, use_processor, caplog):
    r = await client.post("/document-check/upload", files=files(PDF, b"text", name="SECRET-passport.pdf"))
    assert r.status_code == 200 and "SECRET" not in r.text and "SECRET" not in caplog.text


@pytest.mark.parametrize("count, status", [(0, 422), (50, 200), (51, 422), (52, 400)])
async def test_file_count_limits(count, status, client, use_processor):
    body, content_type = multipart(*[PNG] * count) if count else (b"--x--\r\n", "multipart/form-data; boundary=x")
    r = await client.post("/document-check/upload", content=body, headers={"content-type": content_type})
    assert r.status_code == status, r.text


async def test_text_field_is_rejected(client, use_processor):
    r = await client.post("/document-check/upload", files=files(PNG), data={"note": "hi"})
    assert r.status_code == 400


async def test_json_body_is_415(client, use_processor):
    r = await client.post("/document-check/upload", json={"documentUrls": []})
    assert r.status_code == 415


async def test_missing_content_length_is_411_and_body_not_read(client, use_processor):
    body = TrackedBody(multipart(PNG)[0])
    r = await client.post("/document-check/upload", content=body,
                          headers={"content-type": "multipart/form-data; boundary=x"})
    assert r.status_code == 411 and not body.read


async def test_too_large_request_is_413_before_reading(client, use_processor, settings, monkeypatch):
    monkeypatch.setattr(document_check, "get_settings", lambda: dataclasses.replace(settings, max_upload_request_bytes=100))
    data, content_type = multipart(PNG + b"x" * 500)
    body = TrackedBody(data)
    r = await client.post("/document-check/upload", content=body,
                          headers={"content-type": content_type, "content-length": str(len(data))})
    assert r.status_code == 413 and not body.read


async def test_model_unavailable_is_503_before_reading(client, use_processor):
    use_processor(ready=False)
    data, content_type = multipart(PNG)
    body = TrackedBody(data)
    r = await client.post("/document-check/upload", content=body,
                          headers={"content-type": content_type, "content-length": str(len(data))})
    assert r.status_code == 503 and not body.read


async def test_auth_and_rate_limit_apply_before_reading(client, use_processor):
    app.state.api_keys = ("test-key-aaaaaaaaaaaaaaaa",)
    data, content_type = multipart(PNG)
    body = TrackedBody(data)
    r = await client.post("/document-check/upload", content=body,
                          headers={"content-type": content_type, "content-length": str(len(data))})
    assert r.status_code == 401 and not body.read


async def test_openapi_documents_the_upload(client):
    spec = (await client.get("/openapi.json")).json()["paths"]["/document-check/upload"]["post"]
    assert "multipart/form-data" in spec["requestBody"]["content"]
    assert {"401", "411", "413", "415", "429", "503"} <= set(spec["responses"])


# --- with the real model ---

@pytest.mark.model
async def test_real_uploads_are_classified_and_grouped(client, ollama, samples, settings):
    processor = DocumentProcessor(None, DocumentClassifier(ollama), PipelineRegistry.build(ollama), settings)
    app.dependency_overrides[get_processor] = lambda: processor
    names = ["sample_passport.png", "sample_aadhaar.png", "sample_tax_return.pdf"]
    upload = [("files", (n, (samples / n).read_bytes(), "application/octet-stream")) for n in names]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test", timeout=None) as c:
        r = await c.post("/document-check/upload", files=upload)
    assert r.status_code == 200
    groups = {(g["ownerName"] or "").casefold(): [(d["sourceIndex"], d["documentType"]) for d in g["documents"]]
              for g in r.json()}
    assert groups == {"john doe": [(0, "passport"), (2, "taxReturn")], "maria doe": [(1, "idCard")]}
