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
    max_pages: ClassVar[int] = 1  # pages sent to the model; each costs up to ~2,000 tokens

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
        """Send the first max_pages pages to the model and validate the answer against schema."""
        if not page_images:
            raise ExtractionError(f"{self.document_type}: no page images to extract from")
        try:
            return await self._ollama.generate_structured(
                schema, prompt, page_images[: self.max_pages], system_prompt=SYSTEM_PROMPT
            )
        except OllamaError as exc:
            raise ExtractionError(f"{self.document_type} extraction failed: {exc}") from exc
