"""Stage 12 hardening checks: error responses, no echoed input, safe 500s, model readiness. No Ollama needed.

Usage:  python -m scripts.test_hardening
"""

import asyncio
import dataclasses
import logging

import httpx

from app.api.document_check import get_processor
from app.config import get_settings
from app.main import app
from app.schemas.classification import Classification, DocumentType
from app.services.document_processor import DocumentProcessor
from app.services.downloader import DownloadedDocument, FileKind
from app.services.ollama import OllamaClient

SECRET = "SECRET123"
results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")


def urls(n: int) -> list[str]:
    return [f"https://docs.example/{i}.pdf?token={SECRET}" for i in range(n)]


class LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.text = ""

    def emit(self, record: logging.LogRecord) -> None:
        self.text += self.format(record) + "\n"


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


def use(processor) -> None:
    app.dependency_overrides[get_processor] = lambda: processor


async def main() -> None:
    settings = get_settings()
    capture = LogCapture()
    logging.getLogger().addHandler(capture)
    transport = httpx.ASGITransport(app=app)  # no lifespan: every processor is injected
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        post = lambda body, **kw: client.post("/document-check", **({"json": body} if body is not None else kw))

        # --- 422: validation errors never echo what was sent ---
        downloader = CountingDownloader()
        use(DocumentProcessor(downloader, FakeClassifier(), FakeRegistry(), settings))
        cases = [
            ("9 URLs", {"documentUrls": urls(9)}, "too_short"),
            ("51 URLs", {"documentUrls": urls(51)}, "too_long"),
            ("bad URL", {"documentUrls": urls(9) + [f"not-a-url?token={SECRET}"]}, "url_parsing"),
            ("ftp URL", {"documentUrls": urls(9) + [f"ftp://docs.example/a.pdf?token={SECRET}"]}, "url_scheme"),
            ("missing field", {}, "missing"),
            ("extra field", {"documentUrls": urls(10), "note": SECRET}, "extra_forbidden"),
            ("wrong type", {"documentUrls": SECRET}, "list_type"),
        ]
        for label, body, want_type in cases:
            r = await post(body)
            detail = r.json().get("detail", [])
            ok = (r.status_code == 422 and SECRET not in r.text and any(e["type"] == want_type for e in detail)
                  and all(set(e) == {"type", "loc", "msg"} for e in detail))
            check(f"422 {label}: type {want_type}, only type/loc/msg, no input echoed", ok, "" if ok else r.text[:200])
        r = await post(None, content=f'{{"documentUrls": ["{SECRET}"', headers={"content-type": "application/json"})
        check("422 invalid JSON: json_invalid, nothing echoed", r.status_code == 422 and SECRET not in r.text
              and r.json()["detail"][0]["type"] == "json_invalid", r.text[:200])
        check("no document was downloaded for any invalid request", downloader.calls == 0)

        # --- 200: a valid request still works ---
        r = await post({"documentUrls": urls(10)})
        body = r.json()
        check("valid request -> 200 with grouped documents", r.status_code == 200 and len(body[0]["documents"]) == 10
              and downloader.calls == 10, f"{r.status_code}")
        check("response never echoes URLs or tokens", SECRET not in r.text)

        # --- 503: model not available -> fail fast, nothing downloaded ---
        downloader = CountingDownloader()
        use(DocumentProcessor(downloader, FakeClassifier(ready=False), FakeRegistry(), settings))
        r = await post({"documentUrls": urls(10)})
        check("model unavailable -> 503 with a clear detail", r.status_code == 503
              and r.json() == {"detail": "document model is not available, try again later"}, r.text)
        check("...and nothing was downloaded", downloader.calls == 0, f"downloads={downloader.calls}")

        # --- 500: unexpected exception -> safe JSON, nothing leaked ---
        capture.text = ""
        use(ExplodingProcessor())
        r = await post({"documentUrls": urls(10)})
        check("unexpected exception -> 500 {'detail': 'internal error'}", r.status_code == 500 and r.json() == {"detail": "internal error"}, r.text)
        check("exception message not in the response", SECRET not in r.text)
        check("exception message not in the logs, type is", SECRET not in capture.text and "RuntimeError" in capture.text, capture.text.strip())
        app.dependency_overrides.clear()

        # --- other routes unaffected ---
        r = await client.get("/")
        check("GET / still 200", r.status_code == 200 and r.json()["status"] == "ok")
        r = await client.get("/openapi.json")
        check("OpenAPI documents the 503", "503" in r.json()["paths"]["/document-check"]["post"]["responses"])
        check("tokens never reached the logs", SECRET not in capture.text)

    # --- OllamaClient.is_model_available ---
    def client_with(handler, model="qwen3-vl:8b-instruct") -> OllamaClient:
        s = dataclasses.replace(settings, ollama_model=model)
        return OllamaClient.from_settings(s) if handler is None else OllamaClient(
            s.ollama_host, model, s.ollama_timeout_seconds, s.ollama_num_ctx,
            http_client=httpx.AsyncClient(base_url=s.ollama_host, transport=httpx.MockTransport(handler)))

    tags = lambda *names: (lambda req: httpx.Response(200, json={"models": [{"name": n} for n in names]}))

    def raise_(exc):
        def handler(req):
            raise exc
        return handler

    for label, handler, model, want in [
        ("model pulled -> True", tags("qwen3-vl:8b-instruct"), "qwen3-vl:8b-instruct", True),
        ("model not pulled -> False", tags("mistral:latest"), "qwen3-vl:8b-instruct", False),
        ("name without tag matches ':latest'", tags("mistral:latest"), "mistral", True),
        ("Ollama returns non-JSON -> False", lambda req: httpx.Response(200, text="<html>"), "mistral", False),
        ("Ollama HTTP 500 -> False", lambda req: httpx.Response(500), "mistral", False),
        ("Ollama times out -> False", raise_(httpx.ReadTimeout("slow")), "mistral", False),
        ("Ollama unreachable -> False", raise_(httpx.ConnectError("down")), "mistral", False),
    ]:
        ollama = client_with(handler, model)
        got = await ollama.is_model_available()
        await ollama.aclose()
        check(f"is_model_available: {label}", got is want, str(got))

    seen = {}
    def record_timeout(req):
        seen["timeout"] = req.extensions.get("timeout", {}).get("read")
        return httpx.Response(200, json={"models": []})
    ollama = client_with(record_timeout)
    await ollama.is_model_available()
    await ollama.aclose()
    check("readiness check uses a 5 s timeout (not the 180 s model timeout)", seen.get("timeout") == 5.0, str(seen))

    print(f"\n{sum(results)}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
