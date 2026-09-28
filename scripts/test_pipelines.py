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

    def __init__(self, fail: bool = False, answer=None, fail_on_call: int | None = None) -> None:
        self.fail = fail
        self.fail_on_call = fail_on_call  # 1-based call number that fails
        self.answer = answer or (lambda images: {"value": "42", "other": "7"})  # fields found, given the pages sent
        self.calls: list[dict] = []

    async def generate_structured(self, response_model, prompt, image_paths, system_prompt=None):
        self.calls.append({"model": response_model, "images": list(image_paths), "system": system_prompt})
        if self.fail or len(self.calls) == self.fail_on_call:
            raise OllamaError("Could not reach Ollama: ConnectError")
        return response_model(**self.answer(list(image_paths)))


class FakeData(BaseModel):
    value: str | None
    other: str | None = None


def found_on(**pages_by_field: Path):
    """Fake answer: each field is found only if the page it is printed on was sent."""
    return lambda images: {f: (f"from {page.stem}" if page in images else None) for f, page in pages_by_field.items()}


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
    check("everything found on page 1 -> one call, page 1 only", ollama.calls[-1]["images"] == PAGES[:1]
          and len(ollama.calls) == calls_before + 1)

    # Stage 13: extra pages only when page 1 leaves fields null
    def bank(ollama_: FakeOllama) -> PipelineRegistry:
        return PipelineRegistry([FakeBankStatementPipeline(ollama_), FakePassportPipeline(ollama_)])

    fake = FakeOllama(answer=found_on(value=PAGES[0], other=PAGES[2]))
    data = await bank(fake).extract("bankStatement", PAGES)
    check("field missing on page 1 -> 2nd call with pages 1-3",
          [c["images"] for c in fake.calls] == [PAGES[:1], PAGES[:3]], str([len(c["images"]) for c in fake.calls]))
    check("...missing field filled from the 2nd call, page-1 value kept",
          data.model_dump() == {"value": "from p1", "other": "from p3"}, str(data.model_dump()))

    fake = FakeOllama(answer=lambda images: {"value": "page 1" if len(images) == 1 else "CHANGED", "other": None})
    data = await bank(fake).extract("bankStatement", PAGES)
    check("page-1 values are never replaced by the 2nd call", data.value == "page 1", str(data.model_dump()))
    check("field null on every page stays null (no guessing)", data.other is None and len(fake.calls) == 2)

    fake = FakeOllama(answer=found_on(value=PAGES[0], other=PAGES[1]))
    await bank(fake).extract("bankStatement", PAGES[:2])
    check("fewer pages than max_pages: 2nd call sends the 2 there are", fake.calls[-1]["images"] == PAGES[:2])

    fake = FakeOllama(answer=found_on(value=PAGES[0], other=PAGES[1]))
    data = await bank(fake).extract("bankStatement", PAGES[:1])
    check("one-page document with a null field -> no 2nd call", len(fake.calls) == 1 and data.other is None)

    fake = FakeOllama(answer=found_on(value=PAGES[0], other=PAGES[1]))
    data = await bank(fake).extract("passport", PAGES)
    check("max_pages=1 pipeline with a null field -> no 2nd call", len(fake.calls) == 1 and data.other is None)

    try:
        await bank(FakeOllama(answer=found_on(value=PAGES[0], other=PAGES[1]), fail_on_call=2)).extract("bankStatement", PAGES)
        check("2nd call fails -> ExtractionError", False, "no error raised")
    except ExtractionError as exc:
        check("2nd call fails -> ExtractionError", "bankStatement extraction failed" in str(exc), str(exc))

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
