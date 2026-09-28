"""The only module that knows how to talk to Ollama.

The rest of the app asks for "a Pydantic model filled in from these images"
and never sees Ollama's request/response format.
"""

import asyncio
import base64
import logging
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Ollama cut a 10,119-token prompt to 8,093 with num_ctx 8192, so a prompt this close to the
# limit is treated as cut off.
CONTEXT_MARGIN_TOKENS = 256


class OllamaError(Exception):
    """Raised when Ollama is unreachable or returns an unusable answer.

    Messages are safe to log: they never contain document contents or model output.
    """


class OllamaClient:
    def __init__(
        self,
        host: str,
        model: str,
        timeout_seconds: float = 180.0,
        num_ctx: int = 8192,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._num_ctx = num_ctx
        self._http = http_client or httpx.AsyncClient(
            base_url=host,
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> "OllamaClient":
        return cls(
            host=settings.ollama_host,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
            num_ctx=settings.ollama_num_ctx,
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "OllamaClient":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def is_model_available(self) -> bool:
        """True if Ollama is running and the configured model is pulled. Quick: 5 s timeout."""
        try:
            response = await self._http.get("/api/tags", timeout=5.0)
            response.raise_for_status()
            names = {m.get("name") for m in response.json().get("models", [])}
        except (httpx.HTTPError, ValueError):  # ValueError: not JSON
            return False
        return self.model in names or f"{self.model}:latest" in names

    async def generate_structured(
        self,
        response_model: type[T],
        prompt: str,
        image_paths: list[Path],
        system_prompt: str | None = None,
    ) -> T:
        """Send images + prompt, force JSON matching `response_model`, and validate it."""
        images = await asyncio.to_thread(_encode_images, image_paths)

        messages: list[dict] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt, "images": images})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "format": response_model.model_json_schema(),
            "options": {"temperature": 0, "num_ctx": self._num_ctx},
        }

        try:
            response = await self._http.post("/api/chat", json=payload)
        except httpx.TimeoutException as exc:
            raise OllamaError("Ollama request timed out") from exc
        except httpx.HTTPError as exc:
            raise OllamaError(f"Could not reach Ollama: {type(exc).__name__}") from exc

        if response.status_code != 200:
            raise OllamaError(f"Ollama returned HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError as exc:
            raise OllamaError("Ollama returned a non-JSON response") from exc

        # A prompt larger than num_ctx is cut down silently (still HTTP 200), and the answer is then
        # based on part of the input (Stage 13: 5 pages at 150 DPI -> '15.' instead of '15,570').
        if body.get("prompt_eval_count", 0) >= self._num_ctx - CONTEXT_MARGIN_TOKENS:
            raise OllamaError(f"input filled the model's context window (num_ctx={self._num_ctx}); "
                              "send fewer or smaller pages, or raise OLLAMA_NUM_CTX")

        # Only message.content is used; message.thinking (if any) is ignored and never logged.
        content = body.get("message", {}).get("content", "")
        try:
            result = response_model.model_validate_json(content)
        except ValidationError as exc:
            raise OllamaError(
                f"Model output failed {response_model.__name__} validation "
                f"({exc.error_count()} errors)"
            ) from None  # drop the ValidationError: its text includes the model output

        logger.info(
            "Ollama structured call ok: model=%s schema=%s images=%d duration=%.1fs",
            self.model,
            response_model.__name__,
            len(image_paths),
            body.get("total_duration", 0) / 1e9,
        )
        return result


def _encode_images(image_paths: list[Path]) -> list[str]:
    return [base64.b64encode(path.read_bytes()).decode("ascii") for path in image_paths]
