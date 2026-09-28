"""Shared fixtures. Every test uses FAKE documents only (generated into documents/, gitignored)."""

import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.config import Settings, get_settings
from app.main import app
from app.services.ollama import OllamaClient
from scripts import make_realistic_documents, make_sample_documents

SAMPLES = Path("documents")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(scope="session")
def samples() -> Path:
    """The fake sample documents; generated on first use if any are missing."""
    if not (SAMPLES / "sample_pan_card.png").exists():
        make_sample_documents.make_all(SAMPLES)
    if not (SAMPLES / "realistic_pan_card.png").exists():
        make_realistic_documents.make_all(SAMPLES)
    return SAMPLES


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
async def ollama(settings: Settings) -> AsyncIterator[OllamaClient]:
    """A real Ollama client; the test is skipped if the model isn't available."""
    async with OllamaClient.from_settings(settings) as client:
        if not await client.is_model_available():
            pytest.skip(f"Ollama with {settings.ollama_model} is not available")
        yield client


@pytest.fixture(autouse=True)
def clean_app_state():
    """Tests change dependency overrides, API keys and the rate limiter; put them back afterwards."""
    keys, limiter = app.state.api_keys, app.state.rate_limiter
    yield
    app.dependency_overrides.clear()
    app.state.api_keys, app.state.rate_limiter = keys, limiter


@pytest.fixture
def workspaces():
    """Call it to list the temporary request folders on disk (each must be deleted after its request)."""
    return lambda: {p.name for p in Path(tempfile.gettempdir()).glob("extractai-*")}
