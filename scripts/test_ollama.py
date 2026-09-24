"""Manual check for app/services/ollama.py.

Usage:  python -m scripts.test_ollama documents/sample_passport.png
"""

import asyncio
import sys
import time
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.ollama import OllamaClient, OllamaError


class DocumentType(str, Enum):
    PASSPORT = "passport"
    AADHAAR = "idCard"
    TAX_RETURN = "taxReturn"
    UNKNOWN = "unknown"


class Classification(BaseModel):
    documentType: DocumentType
    documentName: str | None = Field(description="Short title of the document, e.g. 'Indian Passport'.")
    ownerName: str | None = Field(description="Full name of the document holder, and nothing else.")


SYSTEM_PROMPT = (
    "You classify identity and tax documents. Report only what is visible. "
    "Never guess. Use null when a field is not visible."
)
PROMPT = (
    "Classify this document.\n"
    "- documentType: passport, idCard (Aadhaar), taxReturn, or unknown.\n"
    "- documentName: a short title for the document.\n"
    "- ownerName: ONLY the holder's full name (given names then surname). No other fields."
)


async def main(image_path: Path) -> None:
    async with OllamaClient.from_settings(get_settings()) as client:
        print(f"model: {client.model}")
        print(f"model available: {await client.is_model_available()}")
        start = time.perf_counter()
        try:
            result = await client.generate_structured(
                Classification, PROMPT, [image_path], system_prompt=SYSTEM_PROMPT
            )
        except OllamaError as exc:
            print(f"OllamaError: {exc}")
            return
        print(f"result: {result.model_dump(mode='json')}")
        print(f"took: {time.perf_counter() - start:.1f}s")


if __name__ == "__main__":
    asyncio.run(main(Path(sys.argv[1])))
