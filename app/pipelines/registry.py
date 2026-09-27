"""Maps a documentType to its extraction pipeline.

To add a document type: write a BaseDocumentPipeline subclass and add its class to
PIPELINE_CLASSES. Nothing in the API needs to change.
"""

from collections.abc import Iterable
from enum import Enum
from pathlib import Path

from pydantic import BaseModel

from app.pipelines.base import BaseDocumentPipeline
from app.services.ollama import OllamaClient

# Filled in by Stage 9 (PassportPipeline, AadhaarPipeline, TaxReturnPipeline).
PIPELINE_CLASSES: list[type[BaseDocumentPipeline]] = []


class PipelineRegistry:
    def __init__(self, pipelines: Iterable[BaseDocumentPipeline]) -> None:
        self._pipelines: dict[str, BaseDocumentPipeline] = {}
        for pipeline in pipelines:
            if pipeline.document_type in self._pipelines:
                raise ValueError(f"duplicate pipeline for {pipeline.document_type!r}")
            self._pipelines[pipeline.document_type] = pipeline

    @classmethod
    def build(cls, ollama: OllamaClient) -> "PipelineRegistry":
        return cls(pipeline_class(ollama) for pipeline_class in PIPELINE_CLASSES)

    @property
    def types(self) -> list[str]:
        return list(self._pipelines)

    def get(self, document_type: str | Enum) -> BaseDocumentPipeline | None:
        key = document_type.value if isinstance(document_type, Enum) else document_type
        return self._pipelines.get(key)

    async def extract(self, document_type: str | Enum, page_images: list[Path]) -> BaseModel | None:
        """Run the matching pipeline; None (-> "data": null) when the type has no pipeline."""
        pipeline = self.get(document_type)
        if pipeline is None:
            return None
        return await pipeline.extract(page_images)
