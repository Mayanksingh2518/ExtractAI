"""Base class for type-specific extraction pipelines."""

from abc import ABC, abstractmethod
from inspect import isabstract
from pathlib import Path
from typing import ClassVar, TypeVar

from pydantic import BaseModel

from app.services.ollama import OllamaClient, OllamaError
from app.services.prompts import SYSTEM_PROMPT

M = TypeVar("M", bound=BaseModel)


class ExtractionError(Exception):
    """Data could not be extracted. Messages never include document content."""


class BaseDocumentPipeline(ABC):
    document_type: ClassVar[str]  # registry key, e.g. "passport"; must match the classifier's documentType
    # Most pages sent when page 1 leaves fields null. Each page costs ~1,000 tokens at 100 DPI
    # (up to ~2,000 at higher DPI): keep max_pages * that within OLLAMA_NUM_CTX.
    max_pages: ClassVar[int] = 1

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if not isabstract(cls) and not getattr(cls, "document_type", None):
            raise TypeError(f"{cls.__name__} must set document_type")

    def __init__(self, ollama: OllamaClient) -> None:
        self._ollama = ollama

    @abstractmethod
    async def extract(self, page_images: list[Path]) -> BaseModel:
        """Return the validated data for one document."""

    async def _generate(self, schema: type[M], prompt: str, page_images: list[Path]) -> M:
        """Read page 1; if fields are still null and the document has more pages, read again with
        up to max_pages pages and fill in only the missing fields.

        Most documents have everything on page 1, and each extra page costs ~10-15 s, so extra
        pages are only sent when they can help. Values found on page 1 are never replaced.
        """
        if not page_images:
            raise ExtractionError(f"{self.document_type}: no page images to extract from")
        result = await self._call(schema, prompt, page_images[:1])
        more_pages = page_images[: self.max_pages]
        missing = [name for name, value in result if value is None]
        if missing and len(more_pages) > 1:
            fuller = await self._call(schema, prompt, more_pages)
            result = result.model_copy(update={name: getattr(fuller, name) for name in missing})
        return result

    async def _call(self, schema: type[M], prompt: str, page_images: list[Path]) -> M:
        try:
            return await self._ollama.generate_structured(schema, prompt, page_images, system_prompt=SYSTEM_PROMPT)
        except OllamaError as exc:
            raise ExtractionError(f"{self.document_type} extraction failed: {exc}") from exc
