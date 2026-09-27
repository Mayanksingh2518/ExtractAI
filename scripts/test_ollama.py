"""Manual check for app/services/ollama.py.

Usage:  python -m scripts.test_ollama documents/sample_passport.png
"""

import asyncio
import sys
import time
from pathlib import Path

from app.config import get_settings
from app.schemas.classification import Classification
from app.services.classifier import CLASSIFY_PROMPT as PROMPT
from app.services.classifier import SYSTEM_PROMPT
from app.services.ollama import OllamaClient, OllamaError


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
