"""Benchmark MAX_CONCURRENT_DOCUMENTS against the real model.

Usage:  caffeinate -i python -u -m scripts.benchmark_concurrency 1 2 3
Each run uses 10 NEW random fake documents (5 passports, 5 Aadhaar cards), because Ollama
caches repeated images and would make the numbers look too fast. Also checks that every
document is still classified and extracted correctly at each concurrency level.
Remember that Ollama itself only runs OLLAMA_NUM_PARALLEL requests at a time.
"""

import asyncio
import dataclasses
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

from app.config import get_settings
from app.pipelines.registry import PipelineRegistry
from app.services.classifier import DocumentClassifier
from app.services.document_processor import DocumentProcessor
from app.services.downloader import DownloadedDocument, FileKind
from app.services.ollama import OllamaClient
from scripts.make_sample_documents import _card

FIRST = ["ARJUN", "PRIYA", "OMAR", "LENA", "KENJI", "SOFIA", "DAVID", "MEERA", "TOMAS", "AISHA", "NIKHIL", "ELENA"]
LAST = ["MEHTA", "SILVA", "KHAN", "BERG", "SATO", "ROSSI", "COHEN", "NAIR", "NOVAK", "OKAFOR", "IYER", "LANG"]
MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
DOCS_PER_RUN = 10


def make_documents(folder: Path, rng: random.Random) -> dict[str, dict]:
    """Write 10 random fake cards; return file name -> expected type, owner and one key field."""
    expected = {}
    for i in range(DOCS_PER_RUN):
        first, last = rng.choice(FIRST), rng.choice(LAST)
        if i % 2 == 0:
            number = f"{rng.choice('ABCDEFGHJK')}{rng.choice('LMNPRSTUVW')}{rng.randint(1000000, 9999999)}"
            _card(folder / f"doc{i}.png", "REPUBLIC OF TESTLAND", "PASSPORT", "darkblue", [
                ("Surname", last), ("Given names", first), ("Passport No.", number),
                ("Date of birth", f"{rng.randint(10, 28)} {rng.choice(MONTHS)} {rng.randint(1950, 2004)}"),
                ("Date of expiry", f"{rng.randint(10, 28)} {rng.choice(MONTHS)} {rng.randint(2027, 2035)}"),
            ])
            expected[f"doc{i}.png"] = {"type": "passport", "owner": f"{first} {last}", "passportNumber": number}
        else:
            digits = f"{rng.randint(2000, 9999)} {rng.randint(1000, 9999)} {rng.randint(1000, 9999)}"
            _card(folder / f"doc{i}.png", "GOVERNMENT OF INDIA  (SAMPLE - NOT A REAL DOCUMENT)", "AADHAAR", "darkred", [
                ("Name", f"{first} {last}"),
                ("DOB", f"{rng.randint(10, 28):02d}/{rng.randint(1, 12):02d}/{rng.randint(1950, 2004)}"),
                ("Gender", rng.choice(["MALE", "FEMALE"])), ("Aadhaar No.", digits),
                ("Address", f"{rng.randint(1, 999)}, Test Road, Testcity {rng.randint(100000, 999999)}"),
            ], size=(1100, 620))
            expected[f"doc{i}.png"] = {"type": "idCard", "owner": f"{first} {last}", "aadharNumber": digits.replace(" ", "-")}
    return expected


class FolderDownloader:
    """Serves https://bench.test/<file> from a local folder (benchmark only)."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    async def download(self, url, dest_dir, name):
        source = self.folder / httpx.URL(url).path.lstrip("/")
        dest = dest_dir / f"{name}.png"
        shutil.copyfile(source, dest)
        return DownloadedDocument(url, dest, FileKind.PNG, dest.stat().st_size)


def ollama_memory() -> str:
    lines = subprocess.run(["ollama", "ps"], capture_output=True, text=True).stdout.strip().splitlines()
    return " ".join(lines[1].split()[2:6]) if len(lines) > 1 else "not loaded"


async def run(limit: int, ollama: OllamaClient, seed: int) -> None:
    settings = dataclasses.replace(get_settings(), max_concurrent_documents=limit)
    folder = Path(tempfile.mkdtemp(prefix="bench-"))
    try:
        expected = make_documents(folder, random.Random(seed))
        processor = DocumentProcessor(FolderDownloader(folder), DocumentClassifier(ollama), PipelineRegistry.build(ollama), settings)
        names = list(expected)
        start = time.perf_counter()
        groups = await processor.process([f"https://bench.test/{n}" for n in names])
        elapsed = time.perf_counter() - start
    finally:
        shutil.rmtree(folder, ignore_errors=True)

    correct = 0
    for group in groups:
        for doc in group.documents:
            want = expected[names[doc.sourceIndex]]
            key = "passportNumber" if want["type"] == "passport" else "aadharNumber"
            correct += (
                doc.documentType.value == want["type"]
                and (group.ownerName or "").casefold() == want["owner"].casefold()
                and (doc.data or {}).get(key) == want[key]
            )
    print(f"limit {limit}: {elapsed:6.1f}s total, {elapsed / DOCS_PER_RUN:5.1f}s/doc, "
          f"{correct}/{DOCS_PER_RUN} correct, ollama ps: {ollama_memory()}")


async def main() -> None:
    limits = [int(a) for a in sys.argv[1:]] or [1, 2, 3]
    settings = get_settings()
    async with OllamaClient.from_settings(settings) as ollama:
        with tempfile.TemporaryDirectory() as tmp:  # warm-up: one call loads the model, not reported
            make_documents(Path(tmp), random.Random(0))
            await DocumentClassifier(ollama).classify([Path(tmp) / "doc0.png"])
        print(f"model warmed up ({settings.ollama_model}); {DOCS_PER_RUN} new documents per run")
        for limit in limits:
            await run(limit, ollama, seed=int(time.time() * 1000) + limit)


if __name__ == "__main__":
    asyncio.run(main())
