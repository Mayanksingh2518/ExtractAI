import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.document_check import router as document_check_router
from app.config import get_settings
from app.pipelines.registry import PipelineRegistry
from app.services.classifier import DocumentClassifier
from app.services.document_processor import DocumentProcessor
from app.services.downloader import DocumentDownloader
from app.services.ollama import OllamaClient

settings = get_settings()
logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx logs every request's full URL at INFO; document URLs can carry access tokens. Our own logs record the host only.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create the shared clients once at startup (reusing connections) and close them at shutdown."""
    ollama = OllamaClient.from_settings(settings)
    downloader = DocumentDownloader(settings)
    app.state.processor = DocumentProcessor(
        downloader, DocumentClassifier(ollama), PipelineRegistry.build(ollama), settings
    )
    try:
        yield
    finally:
        await downloader.aclose()
        await ollama.aclose()


app = FastAPI(
    title="Document Intelligence API",
    description="Classifies documents and extracts structured data using a local Ollama vision model.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(document_check_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "document-intelligence-api"}
