import os
from dataclasses import dataclass
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str
    log_level: str
    ollama_host: str
    ollama_model: str
    ollama_timeout_seconds: float
    ollama_num_ctx: int
    download_timeout_seconds: float
    max_download_bytes: int
    max_redirects: int
    max_upload_request_bytes: int
    pdf_render_dpi: int
    max_pdf_pages: int
    max_concurrent_documents: int
    model_parallel_requests: int
    api_keys: tuple[str, ...]
    rate_limit_requests: int
    rate_limit_window_seconds: float


MIN_API_KEY_LENGTH = 16


def parse_api_keys(raw: str) -> tuple[str, ...]:
    """Comma-separated keys; empty means authentication is off. Short keys are refused
    (the message never includes the key)."""
    keys = tuple(key.strip() for key in raw.split(",") if key.strip())
    if any(len(key) < MIN_API_KEY_LENGTH for key in keys):
        raise ValueError(f"API_KEYS: every key must be at least {MIN_API_KEY_LENGTH} characters")
    return keys


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Document Intelligence API"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3-vl:8b-instruct"),
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")),
        ollama_num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "8192")),
        download_timeout_seconds=float(os.getenv("DOWNLOAD_TIMEOUT_SECONDS", "30")),
        max_download_bytes=int(os.getenv("MAX_DOWNLOAD_BYTES", str(20 * 1024 * 1024))),
        max_redirects=int(os.getenv("MAX_REDIRECTS", "3")),
        max_upload_request_bytes=int(os.getenv("MAX_UPLOAD_REQUEST_BYTES", str(100 * 1024 * 1024))),
        pdf_render_dpi=int(os.getenv("PDF_RENDER_DPI", "100")),
        max_pdf_pages=int(os.getenv("MAX_PDF_PAGES", "10")),
        max_concurrent_documents=max(1, int(os.getenv("MAX_CONCURRENT_DOCUMENTS", "2"))),
        model_parallel_requests=max(1, int(os.getenv("MODEL_PARALLEL_REQUESTS", "1"))),
        api_keys=parse_api_keys(os.getenv("API_KEYS", "")),
        rate_limit_requests=max(0, int(os.getenv("RATE_LIMIT_REQUESTS", "10"))),
        rate_limit_window_seconds=float(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
    )
