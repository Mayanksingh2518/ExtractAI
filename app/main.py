import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.document_check import router as document_check_router
from app.api.security import RateLimiter
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
logger = logging.getLogger("app")


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
# The web page (plain HTML/CSS/JS, no build step) at /ui/.
app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="ui")
# Read by app/api/security.py. Set here, not in lifespan, so they also apply when tests call the app directly.
app.state.api_keys = settings.api_keys
app.state.rate_limiter = (
    RateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)
    if settings.rate_limit_requests > 0 else None
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 without `input` or `ctx`: FastAPI's default echoes the submitted values (URLs may hold tokens)."""
    errors = [{"type": e.get("type"), "loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": errors})


# The page only loads its own files and only talks to this server.
UI_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


@app.middleware("http")
async def ui_security_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/ui"):
        response.headers.update(UI_HEADERS)
    return response


@app.middleware("http")
async def internal_error_middleware(request: Request, call_next):
    """Any unexpected exception -> JSON 500. Only the exception type is logged: its message or
    traceback could contain document data. (An exception handler would still let uvicorn log it.)"""
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error("Unhandled %s on %s %s", type(exc).__name__, request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "internal error"})


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "document-intelligence-api"}
