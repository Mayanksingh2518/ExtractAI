"""app/pipelines/base.py and registry.py, with fake pipelines and a fake Ollama client."""

from pathlib import Path

import pytest
from pydantic import BaseModel

from app.pipelines.base import BaseDocumentPipeline, ExtractionError
from app.pipelines.registry import PIPELINE_CLASSES, PipelineRegistry
from app.schemas.classification import DocumentType
from app.services.ollama import OllamaError

PAGES = [Path("p1.png"), Path("p2.png"), Path("p3.png"), Path("p4.png")]


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


def registry(ollama: FakeOllama) -> PipelineRegistry:
    return PipelineRegistry([FakePassportPipeline(ollama), FakeBankStatementPipeline(ollama)])


# --- lookup ---

def test_lookup():
    r = registry(FakeOllama())
    assert isinstance(r.get(DocumentType.PASSPORT), FakePassportPipeline)  # by enum
    assert isinstance(r.get("passport"), FakePassportPipeline)  # by string
    assert r.get(DocumentType.UNKNOWN) is None
    assert r.get(DocumentType.AADHAAR) is None  # not registered here
    assert r.types == ["passport", "bankStatement"]


# --- extraction ---

@pytest.mark.anyio
async def test_extract_sends_page_1_with_the_shared_system_prompt():
    ollama = FakeOllama()
    data = await registry(ollama).extract(DocumentType.PASSPORT, PAGES)
    assert isinstance(data, FakeData) and data.value == "42"
    assert [c["images"] for c in ollama.calls] == [PAGES[:1]]
    assert "Never guess" in ollama.calls[0]["system"]


@pytest.mark.anyio
async def test_unknown_gives_none_without_a_model_call():
    ollama = FakeOllama()
    assert await registry(ollama).extract(DocumentType.UNKNOWN, PAGES) is None
    assert ollama.calls == []


@pytest.mark.anyio
async def test_new_type_works_through_the_registry_one_call_when_page_1_has_everything():
    ollama = FakeOllama()
    assert isinstance(await registry(ollama).extract("bankStatement", PAGES), FakeData)
    assert [c["images"] for c in ollama.calls] == [PAGES[:1]]


# --- Stage 13: more pages only when page 1 leaves fields null ---

@pytest.mark.anyio
async def test_missing_field_triggers_second_call_with_up_to_max_pages():
    ollama = FakeOllama(answer=found_on(value=PAGES[0], other=PAGES[2]))
    data = await registry(ollama).extract("bankStatement", PAGES)
    assert [c["images"] for c in ollama.calls] == [PAGES[:1], PAGES[:3]]
    assert data.model_dump() == {"value": "from p1", "other": "from p3"}


@pytest.mark.anyio
async def test_page_1_values_are_never_replaced_and_null_everywhere_stays_null():
    ollama = FakeOllama(answer=lambda images: {"value": "page 1" if len(images) == 1 else "CHANGED", "other": None})
    data = await registry(ollama).extract("bankStatement", PAGES)
    assert data.value == "page 1" and data.other is None and len(ollama.calls) == 2


@pytest.mark.anyio
async def test_second_call_sends_only_the_pages_there_are():
    ollama = FakeOllama(answer=found_on(value=PAGES[0], other=PAGES[1]))
    await registry(ollama).extract("bankStatement", PAGES[:2])
    assert ollama.calls[-1]["images"] == PAGES[:2]


@pytest.mark.anyio
@pytest.mark.parametrize("doc_type, pages", [("bankStatement", PAGES[:1]), ("passport", PAGES)],
                         ids=["one-page document", "max_pages=1 pipeline"])
async def test_no_second_call_when_no_more_pages_can_be_sent(doc_type, pages):
    ollama = FakeOllama(answer=found_on(value=PAGES[0], other=PAGES[1]))
    data = await registry(ollama).extract(doc_type, pages)
    assert len(ollama.calls) == 1 and data.other is None


# --- errors ---

@pytest.mark.anyio
@pytest.mark.parametrize("doc_type, ollama, message", [
    ("passport", FakeOllama(fail=True), "passport extraction failed: Could not reach Ollama"),
    ("bankStatement", FakeOllama(answer=found_on(value=PAGES[0], other=PAGES[1]), fail_on_call=2),
     "bankStatement extraction failed"),
], ids=["first call fails", "second call fails"])
async def test_ollama_failure_raises_extraction_error(doc_type, ollama, message):
    with pytest.raises(ExtractionError, match=message):
        await registry(ollama).extract(doc_type, PAGES)


@pytest.mark.anyio
async def test_no_pages_raises_extraction_error():
    with pytest.raises(ExtractionError):
        await registry(FakeOllama()).extract("passport", [])


# --- rules enforced on pipeline classes ---

def test_base_class_cannot_be_instantiated():
    with pytest.raises(TypeError):
        BaseDocumentPipeline(FakeOllama())


def test_subclass_without_extract_is_rejected():
    class NoExtract(BaseDocumentPipeline):
        document_type = "x"

    with pytest.raises(TypeError):
        NoExtract(FakeOllama())


def test_subclass_without_document_type_is_rejected():
    with pytest.raises(TypeError, match="must set document_type"):
        class NoType(BaseDocumentPipeline):
            async def extract(self, page_images):
                return None


def test_duplicate_document_type_is_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        PipelineRegistry([FakePassportPipeline(FakeOllama()), FakePassportPipeline(FakeOllama())])


def test_real_registry_builds():
    assert PipelineRegistry.build(FakeOllama()).types == [c.document_type for c in PIPELINE_CLASSES]
