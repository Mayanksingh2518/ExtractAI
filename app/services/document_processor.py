"""Runs the full flow for one request: download -> pages -> classify -> extract -> group by owner."""

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import Settings
from app.pipelines.base import ExtractionError
from app.pipelines.registry import PipelineRegistry
from app.schemas.classification import DocumentType
from app.schemas.response import DocumentResult, OwnerResult
from app.services.classifier import ClassificationError, DocumentClassifier
from app.services.downloader import DocumentDownloader, DownloadError
from app.services.grouping import group_by_owner
from app.utils.pdf import PdfConversionError, to_page_images
from app.utils.workspace import request_workspace

logger = logging.getLogger(__name__)


@dataclass
class ProcessedDocument:
    ownerName: str | None
    result: DocumentResult


class DocumentProcessor:
    def __init__(
        self,
        downloader: DocumentDownloader,
        classifier: DocumentClassifier,
        registry: PipelineRegistry,
        settings: Settings,
    ) -> None:
        self._downloader = downloader
        self._classifier = classifier
        self._registry = registry
        self._dpi = settings.pdf_render_dpi
        self._max_pages = settings.max_pdf_pages
        # Shared by every request, so N concurrent API calls still never put more than this many
        # documents in flight (and never flood Ollama). Covers the whole document, download to extract.
        self._slots = asyncio.Semaphore(settings.max_concurrent_documents)

    async def process(self, urls: list[str]) -> list[OwnerResult]:
        """Process every URL concurrently (one failure never stops the others), then group the results by owner."""
        with request_workspace() as workspace:
            # gather returns results in input order, whatever order the documents finish in.
            processed = await asyncio.gather(
                *(self._process_limited(index, url, workspace) for index, url in enumerate(urls))
            )
        groups = group_by_owner(processed, lambda doc: doc.ownerName)
        return [OwnerResult(ownerName=g.ownerName, documents=[doc.result for doc in g.documents]) for g in groups]

    async def _process_limited(self, index: int, url: str, workspace: Path) -> ProcessedDocument:
        # Never raises: an exception here would make gather() return early and delete the
        # workspace while other documents are still using it.
        async with self._slots:
            try:
                return await self._process_one(index, url, workspace)
            except Exception as exc:
                logger.error("Document %d: unexpected %s", index, type(exc).__name__)
                return self._failed(index, "internal error", log=False)

    async def _process_one(self, index: int, url: str, workspace: Path) -> ProcessedDocument:
        doc_dir = workspace / f"doc{index:02d}"  # one folder per document, so page file names never collide
        doc_dir.mkdir()
        try:
            downloaded = await self._downloader.download(url, doc_dir, "document")
            pages = await to_page_images(downloaded.path, doc_dir, self._dpi, self._max_pages)
            classification = await self._classifier.classify(pages)
        except DownloadError as exc:
            return self._failed(index, f"download failed: {exc}")
        except PdfConversionError as exc:
            return self._failed(index, f"could not read document: {exc}")
        except ClassificationError as exc:
            return self._failed(index, str(exc))
        except Exception as exc:  # a bug must not take down the whole batch
            logger.error("Document %d: unexpected %s", index, type(exc).__name__)
            return self._failed(index, "internal error", log=False)

        data, error = None, None
        try:
            extracted = await self._registry.extract(classification.documentType, pages)
            data = extracted.model_dump() if extracted is not None else None
        except ExtractionError as exc:
            error = str(exc)
        except Exception as exc:
            logger.error("Document %d: unexpected %s during extraction", index, type(exc).__name__)
            error = "internal error"
        if error:
            logger.warning("Document %d: %s", index, error)
        logger.info("Document %d: %s, data=%s", index, classification.documentType.value, data is not None)

        result = DocumentResult(
            documentType=classification.documentType,
            documentName=classification.documentName,
            data=data,
            sourceIndex=index,
            error=error,
        )
        return ProcessedDocument(classification.ownerName, result)

    @staticmethod
    def _failed(index: int, error: str, log: bool = True) -> ProcessedDocument:
        if log:
            logger.warning("Document %d: %s", index, error)
        result = DocumentResult(
            documentType=DocumentType.UNKNOWN, documentName=None, data=None, sourceIndex=index, error=error
        )
        return ProcessedDocument(None, result)
