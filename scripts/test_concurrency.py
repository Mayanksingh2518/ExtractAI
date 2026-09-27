"""Checks for the concurrency limit in DocumentProcessor, using fakes. No Ollama needed.

Usage:  python -m scripts.test_concurrency
"""

import asyncio
import dataclasses
import os
import random
import tempfile
import time
from pathlib import Path

from app.config import get_settings
from app.schemas.classification import Classification, DocumentType
from app.services.document_processor import DocumentProcessor
from app.services.downloader import DownloadedDocument, DownloadError, FileKind

results: list[bool] = []
OWNERS = ["Ann Lee", "Bob Roy", "Cat Diaz"]


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")


class Tracker:
    """Counts documents between download start and extraction end."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay, self.now, self.peak, self.started = delay, 0, 0, 0
        self.model_now, self.model_peak, self.downloading_peak = 0, 0, 0
        self.downloading, self.events = 0, []  # events: ("classify"|"extract", index) in the order the model got them

    def enter(self) -> None:
        self.now += 1
        self.started += 1
        self.peak = max(self.peak, self.now)

    def leave(self) -> None:
        self.now -= 1

    async def work(self) -> None:
        await asyncio.sleep(self.delay * random.uniform(0.5, 1.5))  # random, so documents finish out of order


class FakeDownloader:
    def __init__(self, tracker: Tracker, fail: set[int] = frozenset()) -> None:
        self.t, self.fail = tracker, fail

    async def download(self, url, dest_dir, name):
        index = int(url.rsplit("/", 1)[1])
        self.t.enter()
        self.t.downloading += 1
        self.t.downloading_peak = max(self.t.downloading_peak, self.t.downloading)
        await self.t.work()
        self.t.downloading -= 1
        if index in self.fail:
            self.t.leave()
            raise DownloadError("host 'fake.test' returned HTTP 404")
        path = dest_dir / f"{name}.png"
        path.write_bytes(b"not really a png")  # to_page_images passes PNGs through without reading them
        return DownloadedDocument(url, path, FileKind.PNG, 16)


class FakeClassifier:
    def __init__(self, tracker: Tracker, crash: set[int] = frozenset()) -> None:
        self.t, self.crash = tracker, crash

    async def is_ready(self) -> bool:
        return True

    async def classify(self, pages):
        index = int(pages[0].parent.name.removeprefix("doc"))
        self.t.model_now += 1
        self.t.model_peak = max(self.t.model_peak, self.t.model_now)
        self.t.events.append(("classify", index))
        await self.t.work()
        if index in self.crash:
            self.t.model_now -= 1
            self.t.leave()
            raise RuntimeError("bug")
        self.t.model_now -= 1
        return Classification(documentName=f"Doc {index}", documentType=DocumentType.PASSPORT, ownerName=OWNERS[index % 3])


class FakeRegistry:
    def __init__(self, tracker: Tracker) -> None:
        self.t = tracker

    async def extract(self, document_type, pages):
        self.t.model_now += 1
        self.t.model_peak = max(self.t.model_peak, self.t.model_now)
        self.t.events.append(("extract", int(pages[0].parent.name.removeprefix("doc"))))
        await self.t.work()
        self.t.model_now -= 1
        self.t.leave()
        return None


def make(limit: int, fail=frozenset(), crash=frozenset(), delay: float = 0.05, model: int | None = None) -> tuple[DocumentProcessor, Tracker]:
    """model = MODEL_PARALLEL_REQUESTS; defaults to the outer limit so older checks test the outer limit alone."""
    t = Tracker(delay)
    settings = dataclasses.replace(get_settings(), max_concurrent_documents=limit, model_parallel_requests=model or limit)
    return DocumentProcessor(FakeDownloader(t, fail), FakeClassifier(t, crash), FakeRegistry(t), settings), t


def urls(n: int) -> list[str]:
    return [f"https://fake.test/{i}" for i in range(n)]


def flat(groups) -> dict[int, tuple]:
    return {d.sourceIndex: (g.ownerName, d.documentType.value, d.error) for g in groups for d in g.documents}


def workspaces() -> set[str]:
    return {p.name for p in Path(tempfile.gettempdir()).glob("extractai-*")}


async def main() -> None:
    before = workspaces()

    for limit in (1, 2, 3, 5):
        processor, t = make(limit)
        start = time.perf_counter()
        await processor.process(urls(10))
        check(f"limit {limit}: at most {limit} in flight, and {limit} reached", t.peak == limit,
              f"peak={t.peak}, {time.perf_counter() - start:.2f}s")

    processor, t = make(2)
    await asyncio.gather(processor.process(urls(10)), processor.process(urls(10)))
    check("limit is shared: 2 simultaneous requests, still at most 2", t.peak == 2 and t.started == 20, f"peak={t.peak}")

    sequential, _ = make(1)
    parallel, _ = make(3)
    a, b = await sequential.process(urls(12)), await parallel.process(urls(12))
    check("same result at limit 1 and limit 3 (order kept)", [g.model_dump() for g in a] == [g.model_dump() for g in b])
    check("groups in first-seen order", [g.ownerName for g in b] == OWNERS)
    check("documents in each group in input order", all([d.sourceIndex for d in g.documents] == sorted(d.sourceIndex for d in g.documents) for g in b))

    processor, t = make(3, fail={2, 7}, crash={4})
    docs = flat(await processor.process(urls(10)))
    check("failures isolated: 2 download errors + 1 crash, 7 fine",
          docs[2][2].startswith("download failed") and docs[7][2].startswith("download failed") and docs[4][2] == "internal error"
          and all(docs[i][2] is None for i in (0, 1, 3, 5, 6, 8, 9)), str({i: d[2] for i, d in docs.items() if d[2]}))
    check("slots released after failures (tracker back to 0)", t.now == 0, f"now={t.now}")

    # An exception that escapes _process_one must not end gather early or free the workspace too soon.
    processor, t = make(2)
    original = processor._process_one

    async def explode_on_3(index, url, workspace):
        if index == 3:
            raise OSError("disk full")
        return await original(index, url, workspace)

    processor._process_one = explode_on_3
    docs = flat(await processor.process(urls(10)))
    check("escaping exception -> 'internal error', the other 9 complete",
          docs[3][2] == "internal error" and sum(d[2] is None for d in docs.values()) == 9)

    # Client disconnects mid-request: tasks are cancelled and the workspace is still deleted.
    processor, t = make(2, delay=0.2)
    task = asyncio.create_task(processor.process(urls(10)))
    await asyncio.sleep(0.3)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    await asyncio.sleep(0.5)
    check("cancelled request: no documents started after cancel", t.started <= 4, f"started={t.started} of 10")
    check("no temp workspaces left", workspaces() == before, str(workspaces() - before))

    processor, _ = make(3, delay=0.1)
    start = time.perf_counter()
    await processor.process(urls(9))
    fast = time.perf_counter() - start
    processor, _ = make(1, delay=0.1)
    start = time.perf_counter()
    await processor.process(urls(9))
    slow = time.perf_counter() - start
    check("limit 3 is faster than limit 1 on waiting work", fast < slow / 2, f"{fast:.2f}s vs {slow:.2f}s")

    # Inner model limit: classify + extract of one document reach the model back to back.
    processor, t = make(3, model=1)
    await processor.process(urls(10))
    pairs = [t.events[i:i + 2] for i in range(0, len(t.events), 2)]
    check("model limit 1: never 2 model calls at once", t.model_peak == 1, f"model_peak={t.model_peak}")
    check("each classify is immediately followed by its own extract",
          all(a == ("classify", b[1]) and b[0] == "extract" for a, b in pairs), str(t.events[:6]))
    check("downloads still overlap the model (outer limit 3)", t.downloading_peak >= 2, f"downloading_peak={t.downloading_peak}")
    processor, t = make(4, model=2)
    await processor.process(urls(12))
    check("model limit 2: at most 2 in the model, 2 reached", t.model_peak == 2, f"model_peak={t.model_peak}")
    processor, t = make(3, model=1, crash={4})
    docs = flat(await processor.process(urls(10)))
    check("model slot released after a classify crash", docs[4][2] == "internal error" and sum(d[2] is None for d in docs.values()) == 9)

    for raw, want in [("3", 3), ("0", 1), ("-4", 1)]:
        os.environ["MAX_CONCURRENT_DOCUMENTS"] = raw
        get_settings.cache_clear()
        check(f"MAX_CONCURRENT_DOCUMENTS={raw} -> {want}", get_settings().max_concurrent_documents == want)
        os.environ["MODEL_PARALLEL_REQUESTS"] = raw
        get_settings.cache_clear()
        check(f"MODEL_PARALLEL_REQUESTS={raw} -> {want}", get_settings().model_parallel_requests == want)
    get_settings.cache_clear()

    print(f"\n{sum(results)}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
