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


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "Document Intelligence API"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        ollama_host=os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3-vl:8b-instruct"),
        ollama_timeout_seconds=float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")),
        ollama_num_ctx=int(os.getenv("OLLAMA_NUM_CTX", "8192")),
    )
