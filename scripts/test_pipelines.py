"""Checks for app/pipelines/base.py and registry.py, using fake pipelines. No Ollama needed.

Usage:  python -m scripts.test_pipelines
"""

import asyncio
from pathlib import Path

from pydantic import BaseModel

from app.pipelines.base import BaseDocumentPipeline, ExtractionError
from app.pipelines.registry import PIPELINE_CLASSES, PipelineRegistry
from app.schemas.classification import DocumentType
from app.services.ollama import OllamaError

results: list[bool] = []
PAGES = [Path("p1.png"), Path("p2.png"), Path("p3.png"), Path("p4.png")]


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")


class FakeOllama:
    """Stands in for OllamaClient: records each call and returns a canned answer or raises."""

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict] = []

    async def generate_structured(self, response_model, prompt, image_paths, system_prompt=None):
        self.calls.append({"model": response_model, "images": list(image_paths), "system": system_prompt})
        if self.fail:
            raise OllamaError("Could not reach Ollama: ConnectError")
        return response_model(value="42")


class FakeData(BaseModel):
    value: str | None


class FakePassportPipeline(BaseDocumentPipeline):
    document_type = "passport"

    async def extract(self, page_images):
        return await self._generate(FakeData, "extract passport", page_images)


class FakeBankStatementPipeline(BaseDocumentPipeline):  # a type the classifier doesn't know yet
    document_type = "bankStatement"
    max_pages = 3

    async def extract(self, page_images):
        return await self._generate(FakeData, "extract bank statement", page_images)


async def main() -> None:
    ollama = FakeOllama()
    registry = PipelineRegistry([FakePassportPipeline(ollama), FakeBankStatementPipeline(ollama)])

    # Lookup
    check("lookup by enum", isinstance(registry.get(DocumentType.PASSPORT), FakePassportPipeline))
    check("lookup by string", isinstance(registry.get("passport"), FakePassportPipeline))
    check("'unknown' has no pipeline -> None", registry.get(DocumentType.UNKNOWN) is None)
    check("unregistered type (idCard) -> None", registry.get(DocumentType.AADHAAR) is None)
    check("registry lists its types", registry.types == ["passport", "bankStatement"], str(registry.types))

    # Extraction through the registry
    data = await registry.extract(DocumentType.PASSPORT, PAGES)
    check("extract returns the validated model", isinstance(data, FakeData) and data.value == "42")
    check("max_pages=1 sends only page 1", ollama.calls[-1]["images"] == PAGES[:1])
    check("shared system prompt is sent", "Never guess" in (ollama.calls[-1]["system"] or ""))
    calls_before = len(ollama.calls)
    check("extract for 'unknown' -> None (data: null)", await registry.extract(DocumentType.UNKNOWN, PAGES) is None)
    check("...and no model call was made", len(ollama.calls) == calls_before)

    # New type added with no change to other code
    data = await registry.extract("bankStatement", PAGES)
    check("new type 'bankStatement' works via registry", isinstance(data, FakeData))
    check("its max_pages=3 sends pages 1-3", ollama.calls[-1]["images"] == PAGES[:3])
    await registry.extract("bankStatement", PAGES[:2])
    check("fewer pages than max_pages is fine", ollama.calls[-1]["images"] == PAGES[:2])

    # Errors
    try:
        await PipelineRegistry([FakePassportPipeline(FakeOllama(fail=True))]).extract("passport", PAGES)
        check("Ollama failure -> ExtractionError", False, "no error raised")
    except ExtractionError as exc:
        check("Ollama failure -> ExtractionError", "passport extraction failed" in str(exc), str(exc))
    try:
        await registry.extract("passport", [])
        check("no pages -> ExtractionError", False, "no error raised")
    except ExtractionError as exc:
        check("no pages -> ExtractionError", True, str(exc))

    # Rules enforced on pipeline classes
    try:
        BaseDocumentPipeline(ollama)
        check("base class can't be instantiated", False)
    except TypeError:
        check("base class can't be instantiated", True)
    try:
        class NoExtract(BaseDocumentPipeline):
            document_type = "x"
        NoExtract(ollama)
        check("subclass without extract() is rejected", False)
    except TypeError:
        check("subclass without extract() is rejected", True)
    try:
        class NoType(BaseDocumentPipeline):
            async def extract(self, page_images):
                return None
        check("subclass without document_type is rejected", False)
    except TypeError as exc:
        check("subclass without document_type is rejected", True, str(exc))
    try:
        PipelineRegistry([FakePassportPipeline(ollama), FakePassportPipeline(ollama)])
        check("duplicate document_type is rejected", False)
    except ValueError as exc:
        check("duplicate document_type is rejected", True, str(exc))

    # Real registry (empty until Stage 9) still builds and returns None safely
    real = PipelineRegistry.build(ollama)
    check("PipelineRegistry.build works", real.types == [c.document_type for c in PIPELINE_CLASSES], str(real.types))

    print(f"\n{sum(results)}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
