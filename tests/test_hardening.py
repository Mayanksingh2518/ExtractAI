"""Stage 12/13 hardening: 422 without echoed input, 503, safe 500s, model readiness, context-window guard."""

import httpx
import pytest

from app.api.document_check import get_processor
from app.main import app
from app.schemas.classification import Classification, DocumentType
from app.services.document_processor import DocumentProcessor
from app.services.downloader import DownloadedDocument, FileKind
from app.services.ollama import OllamaClient, OllamaError

pytestmark = pytest.mark.anyio
SECRET = "SECRET123"


def urls(n: int) -> list[str]:
    return [f"https://docs.example/{i}.pdf?token={SECRET}" for i in range(n)]


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


class CountingDownloader:
    def __init__(self) -> None:
        self.calls = 0

    async def download(self, url, dest_dir, name):
        self.calls += 1
        path = dest_dir / f"{name}.png"
        path.write_bytes(b"x")
        return DownloadedDocument(url, path, FileKind.PNG, 1)


class ExplodingProcessor:
    async def process(self, urls):
        raise RuntimeError(f"document text {SECRET} leaked into an exception")


@pytest.fixture
async def client():
    app.state.rate_limiter, app.state.api_keys = None, ()  # restored by conftest's clean_app_state
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


def use(processor) -> None:
    app.dependency_overrides[get_processor] = lambda: processor


@pytest.fixture
def downloader(settings) -> CountingDownloader:
    d = CountingDownloader()
    use(DocumentProcessor(d, FakeClassifier(), FakeRegistry(), settings))
    return d


# --- 422: validation errors never echo what was sent ---

@pytest.mark.parametrize("body, want_type", [
    ({"documentUrls": urls(9)}, "too_short"),
    ({"documentUrls": urls(51)}, "too_long"),
    ({"documentUrls": urls(9) + [f"not-a-url?token={SECRET}"]}, "url_parsing"),
    ({"documentUrls": urls(9) + [f"ftp://docs.example/a.pdf?token={SECRET}"]}, "url_scheme"),
    ({}, "missing"),
    ({"documentUrls": urls(10), "note": SECRET}, "extra_forbidden"),
    ({"documentUrls": SECRET}, "list_type"),
], ids=["9 URLs", "51 URLs", "bad URL", "ftp URL", "missing field", "extra field", "wrong type"])
async def test_422_has_only_type_loc_msg_and_echoes_nothing(body, want_type, client, downloader):
    r = await client.post("/document-check", json=body)
    detail = r.json()["detail"]
    assert r.status_code == 422 and SECRET not in r.text
    assert any(e["type"] == want_type for e in detail)
    assert all(set(e) == {"type", "loc", "msg"} for e in detail)
    assert downloader.calls == 0


async def test_422_invalid_json_echoes_nothing(client, downloader):
    r = await client.post("/document-check", content=f'{{"documentUrls": ["{SECRET}"',
                          headers={"content-type": "application/json"})
    assert r.status_code == 422 and SECRET not in r.text and r.json()["detail"][0]["type"] == "json_invalid"


# --- 200, 503, 500 ---

async def test_valid_request_200_without_urls_in_response(client, downloader):
    r = await client.post("/document-check", json={"documentUrls": urls(10)})
    assert r.status_code == 200 and len(r.json()[0]["documents"]) == 10 and downloader.calls == 10
    assert SECRET not in r.text


async def test_model_unavailable_503_before_any_download(client, settings):
    counting = CountingDownloader()
    use(DocumentProcessor(counting, FakeClassifier(ready=False), FakeRegistry(), settings))
    r = await client.post("/document-check", json={"documentUrls": urls(10)})
    assert r.status_code == 503 and r.json() == {"detail": "document model is not available, try again later"}
    assert counting.calls == 0


async def test_unexpected_exception_500_leaks_nothing(client, caplog):
    use(ExplodingProcessor())
    r = await client.post("/document-check", json={"documentUrls": urls(10)})
    assert r.status_code == 500 and r.json() == {"detail": "internal error"}
    assert SECRET not in r.text and SECRET not in caplog.text
    assert "Unhandled RuntimeError on POST /document-check" in caplog.text


async def test_other_routes_and_openapi(client):
    r = await client.get("/")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    assert "503" in (await client.get("/openapi.json")).json()["paths"]["/document-check"]["post"]["responses"]


# --- OllamaClient.is_model_available ---

def client_with(settings, handler, model="qwen3-vl:8b-instruct") -> OllamaClient:
    return OllamaClient(settings.ollama_host, model, settings.ollama_timeout_seconds, settings.ollama_num_ctx,
                        http_client=httpx.AsyncClient(base_url=settings.ollama_host, transport=httpx.MockTransport(handler)))


def tags(*names):
    return lambda req: httpx.Response(200, json={"models": [{"name": n} for n in names]})


def raise_(exc):
    def handler(req):
        raise exc
    return handler


@pytest.mark.parametrize("handler, model, want", [
    (tags("qwen3-vl:8b-instruct"), "qwen3-vl:8b-instruct", True),
    (tags("mistral:latest"), "qwen3-vl:8b-instruct", False),
    (tags("mistral:latest"), "mistral", True),
    (lambda req: httpx.Response(200, text="<html>"), "mistral", False),
    (lambda req: httpx.Response(500), "mistral", False),
    (raise_(httpx.ReadTimeout("slow")), "mistral", False),
    (raise_(httpx.ConnectError("down")), "mistral", False),
], ids=["pulled", "not pulled", "name without tag matches :latest", "non-JSON", "HTTP 500", "timeout", "unreachable"])
async def test_is_model_available(handler, model, want, settings):
    ollama = client_with(settings, handler, model)
    assert await ollama.is_model_available() is want
    await ollama.aclose()


async def test_readiness_check_uses_a_5_second_timeout(settings):
    seen = {}

    def record(req):
        seen["timeout"] = req.extensions.get("timeout", {}).get("read")
        return httpx.Response(200, json={"models": []})

    ollama = client_with(settings, record)
    await ollama.is_model_available()
    await ollama.aclose()
    assert seen["timeout"] == 5.0


# --- Stage 13: a prompt that filled the context window is an error, not an answer ---

@pytest.mark.parametrize("tokens_below_num_ctx, want_error", [
    (4096, False), (257, False), (99, True), (0, True), (None, False),
], ids=["half", "just under the margin", "cut to num_ctx - 99 (as observed)", "at num_ctx", "no count reported"])
async def test_context_window_guard(tokens_below_num_ctx, want_error, settings):
    body = {"message": {"content": '{"documentName": "Receipt", "documentType": "unknown", "ownerName": null}'}}
    if tokens_below_num_ctx is not None:
        body["prompt_eval_count"] = settings.ollama_num_ctx - tokens_below_num_ctx
    ollama = client_with(settings, lambda req: httpx.Response(200, json=body))
    try:
        if want_error:
            with pytest.raises(OllamaError, match="context window"):
                await ollama.generate_structured(Classification, "classify", [])
        else:
            await ollama.generate_structured(Classification, "classify", [])
    finally:
        await ollama.aclose()
