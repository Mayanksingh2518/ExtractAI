"""DocumentProcessor concurrency: the outer document limit and the inner model lock, using fakes."""

import asyncio
import dataclasses
import random
import time

import pytest

from app.config import get_settings
from app.schemas.classification import Classification, DocumentType
from app.services.document_processor import DocumentProcessor
from app.services.downloader import DownloadedDocument, DownloadError, FileKind

pytestmark = pytest.mark.anyio
OWNERS = ["Ann Lee", "Bob Roy", "Cat Diaz"]


class Tracker:
    """Counts documents between download start and extraction end, and model calls."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay, self.now, self.peak, self.started = delay, 0, 0, 0
        self.model_now, self.model_peak, self.downloading, self.downloading_peak = 0, 0, 0, 0
        self.events: list[tuple[str, int]] = []  # ("classify" | "extract", index) in the order the model got them

    def enter(self) -> None:
        self.now += 1
        self.started += 1
        self.peak = max(self.peak, self.now)

    def leave(self) -> None:
        self.now -= 1

    def model_enter(self, kind: str, index: int) -> None:
        self.model_now += 1
        self.model_peak = max(self.model_peak, self.model_now)
        self.events.append((kind, index))

    async def work(self) -> None:
        await asyncio.sleep(self.delay * random.uniform(0.5, 1.5))  # random, so documents finish out of order


class FakeDownloader:
    def __init__(self, tracker: Tracker, fail: frozenset[int]) -> None:
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
    def __init__(self, tracker: Tracker, crash: frozenset[int]) -> None:
        self.t, self.crash = tracker, crash

    async def is_ready(self) -> bool:
        return True

    async def classify(self, pages):
        index = int(pages[0].parent.name.removeprefix("doc"))
        self.t.model_enter("classify", index)
        await self.t.work()
        self.t.model_now -= 1
        if index in self.crash:
            self.t.leave()
            raise RuntimeError("bug")
        return Classification(documentName=f"Doc {index}", documentType=DocumentType.PASSPORT, ownerName=OWNERS[index % 3])


class FakeRegistry:
    def __init__(self, tracker: Tracker) -> None:
        self.t = tracker

    async def extract(self, document_type, pages):
        self.t.model_enter("extract", int(pages[0].parent.name.removeprefix("doc")))
        await self.t.work()
        self.t.model_now -= 1
        self.t.leave()
        return None


def make(limit: int, fail=frozenset(), crash=frozenset(), delay: float = 0.05, model: int | None = None):
    """model = MODEL_PARALLEL_REQUESTS; defaults to the outer limit so those tests check the outer limit alone."""
    t = Tracker(delay)
    settings = dataclasses.replace(get_settings(), max_concurrent_documents=limit, model_parallel_requests=model or limit)
    return DocumentProcessor(FakeDownloader(t, fail), FakeClassifier(t, crash), FakeRegistry(t), settings), t


def urls(n: int) -> list[str]:
    return [f"https://fake.test/{i}" for i in range(n)]


def flat(groups) -> dict[int, tuple]:
    return {d.sourceIndex: (g.ownerName, d.documentType.value, d.error) for g in groups for d in g.documents}


@pytest.mark.parametrize("limit", [1, 2, 3, 5])
async def test_at_most_limit_documents_in_flight_and_limit_reached(limit):
    processor, t = make(limit)
    await processor.process(urls(10))
    assert t.peak == limit


async def test_limit_is_shared_by_simultaneous_requests():
    processor, t = make(2)
    await asyncio.gather(processor.process(urls(10)), processor.process(urls(10)))
    assert t.peak == 2 and t.started == 20


async def test_same_result_at_any_limit_and_order_kept():
    a = await make(1)[0].process(urls(12))
    b = await make(3)[0].process(urls(12))
    assert [g.model_dump() for g in a] == [g.model_dump() for g in b]
    assert [g.ownerName for g in b] == OWNERS  # first-seen order
    assert all([d.sourceIndex for d in g.documents] == sorted(d.sourceIndex for d in g.documents) for g in b)


async def test_failures_are_isolated_and_slots_released():
    processor, t = make(3, fail=frozenset({2, 7}), crash=frozenset({4}))
    docs = flat(await processor.process(urls(10)))
    assert docs[2][2].startswith("download failed") and docs[7][2].startswith("download failed")
    assert docs[4][2] == "internal error"
    assert all(docs[i][2] is None for i in (0, 1, 3, 5, 6, 8, 9))
    assert t.now == 0


async def test_escaping_exception_becomes_internal_error_and_the_rest_complete():
    processor, _ = make(2)
    original = processor._process_one

    async def explode_on_3(index, url, workspace):
        if index == 3:
            raise OSError("disk full")
        return await original(index, url, workspace)

    processor._process_one = explode_on_3
    docs = flat(await processor.process(urls(10)))
    assert docs[3][2] == "internal error" and sum(d[2] is None for d in docs.values()) == 9


async def test_cancelled_request_stops_starting_documents_and_deletes_workspace(workspaces):
    before = workspaces()
    processor, t = make(2, delay=0.2)
    task = asyncio.create_task(processor.process(urls(10)))
    await asyncio.sleep(0.3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.5)
    assert t.started <= 4
    assert workspaces() == before


async def test_higher_limit_is_faster_on_waiting_work():
    timings = []
    for limit in (3, 1):
        processor, _ = make(limit, delay=0.1)
        start = time.perf_counter()
        await processor.process(urls(9))
        timings.append(time.perf_counter() - start)
    assert timings[0] < timings[1] / 2


async def test_model_lock_1_keeps_each_documents_calls_back_to_back():
    processor, t = make(3, model=1)
    await processor.process(urls(10))
    assert t.model_peak == 1
    pairs = [t.events[i:i + 2] for i in range(0, len(t.events), 2)]
    assert all(a == ("classify", b[1]) and b[0] == "extract" for a, b in pairs)
    assert t.downloading_peak >= 2  # downloads still overlap the model


async def test_model_lock_2_allows_two_model_calls():
    processor, t = make(4, model=2)
    await processor.process(urls(12))
    assert t.model_peak == 2


async def test_model_slot_released_after_a_classify_crash():
    processor, _ = make(3, model=1, crash=frozenset({4}))
    docs = flat(await processor.process(urls(10)))
    assert docs[4][2] == "internal error" and sum(d[2] is None for d in docs.values()) == 9


@pytest.mark.parametrize("raw, want", [("3", 3), ("0", 1), ("-4", 1)])
@pytest.mark.parametrize("variable, field", [("MAX_CONCURRENT_DOCUMENTS", "max_concurrent_documents"),
                                             ("MODEL_PARALLEL_REQUESTS", "model_parallel_requests")])
def test_limits_below_1_become_1(variable, field, raw, want, monkeypatch):
    monkeypatch.setenv(variable, raw)
    get_settings.cache_clear()
    try:
        assert getattr(get_settings(), field) == want
    finally:
        get_settings.cache_clear()
