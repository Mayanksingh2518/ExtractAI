"""Stage 15: optional API-key authentication and rate limiting."""

import httpx
import pytest

from app.api.document_check import get_processor
from app.api.security import RateLimiter
from app.config import parse_api_keys
from app.main import app
from app.schemas.response import OwnerResult

KEY_A = "test-key-aaaaaaaaaaaaaaaa"
KEY_B = "test-key-bbbbbbbbbbbbbbbb"
URLS = [f"https://docs.example/{i}.pdf" for i in range(10)]


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class CountingProcessor:
    def __init__(self) -> None:
        self.calls = 0

    async def process(self, urls):
        self.calls += 1
        return [OwnerResult(ownerName=None, documents=[])]


# --- RateLimiter ---

def test_limiter_allows_max_then_refuses_with_retry_after():
    clock = FakeClock()
    limiter = RateLimiter(3, 10, clock=clock)
    assert [limiter.hit("a") for _ in range(3)] == [None, None, None]
    clock.now += 4
    assert limiter.hit("a") == 6  # seconds until the oldest request leaves the window
    assert limiter.hit("b") is None  # another client has its own budget
    clock.now += 6
    assert limiter.hit("a") is None


def test_limiter_window_slides():
    clock = FakeClock()
    limiter = RateLimiter(2, 10, clock=clock)
    limiter.hit("a")
    clock.now += 9
    limiter.hit("a")
    clock.now += 2  # t=11: the t=0 request has left the window, the t=9 one has not
    assert limiter.hit("a") is None
    assert limiter.hit("a") is not None


def test_limiter_forgets_idle_clients():
    clock = FakeClock()
    limiter = RateLimiter(1, 10, clock=clock)
    for i in range(10_001):
        limiter.hit(f"ip:{i}")
    clock.now += 11
    limiter.hit("new")
    assert len(limiter._hits) == 1


# --- API_KEYS parsing ---

def test_api_keys_parsing():
    assert parse_api_keys("") == () and parse_api_keys(" , ,") == ()
    assert parse_api_keys(f" {KEY_A} ,{KEY_B},") == (KEY_A, KEY_B)


def test_short_key_is_refused_without_showing_it():
    with pytest.raises(ValueError) as exc:
        parse_api_keys(f"{KEY_A},short-secret")
    assert "short-secret" not in str(exc.value)


# --- through the app ---

@pytest.fixture
def processor() -> CountingProcessor:
    p = CountingProcessor()
    app.dependency_overrides[get_processor] = lambda: p
    return p


def client(ip: str = "203.0.113.5") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(ip, 1234)), base_url="http://test")


async def post(c: httpx.AsyncClient, key: str | None = None, **kwargs) -> httpx.Response:
    kwargs.setdefault("json", {"documentUrls": URLS})
    headers = kwargs.pop("headers", {}) | ({"X-API-Key": key} if key is not None else {})
    return await c.post("/document-check", headers=headers, **kwargs)


@pytest.fixture
def auth_on():
    app.state.api_keys, app.state.rate_limiter = (KEY_A, KEY_B), None  # restored by conftest


@pytest.mark.anyio
async def test_auth_off_needs_no_key(processor):
    app.state.api_keys, app.state.rate_limiter = (), None
    async with client() as c:
        assert (await post(c)).status_code == 200


@pytest.mark.anyio
@pytest.mark.parametrize("key", [None, "test-key-cccccccccccccccc", KEY_A.upper(), KEY_A[:-1], ""],
                         ids=["no key", "wrong key", "different case", "prefix of a valid key", "empty key"])
async def test_auth_on_rejects_bad_keys(key, processor, auth_on, caplog):
    async with client() as c:
        r = await post(c, key)
    assert r.status_code == 401 and r.json() == {"detail": "missing or invalid API key"}
    assert r.headers["www-authenticate"] == "APIKey"
    assert processor.calls == 0
    assert "Rejected request without a valid API key from 203.0.113.5" in caplog.text
    assert KEY_A not in caplog.text and "cccccccc" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("key", [KEY_A, KEY_B])
async def test_auth_on_accepts_each_key(key, processor, auth_on):
    async with client() as c:
        assert (await post(c, key)).status_code == 200
    assert processor.calls == 1


@pytest.mark.anyio
async def test_auth_runs_before_body_validation(processor, auth_on):
    async with client() as c:
        assert (await post(c, json={"documentUrls": URLS[:3]})).status_code == 401
        assert (await post(c, KEY_A, json={"documentUrls": URLS[:3]})).status_code == 422
        # FastAPI parses JSON before dependencies run, so broken JSON is a 422. Accepted: it echoes nothing.
        r = await post(c, json=None, content=b"{broken", headers={"content-type": "application/json"})
        assert r.status_code == 422 and r.json()["detail"][0]["type"] == "json_invalid" and "broken" not in r.text


@pytest.mark.anyio
async def test_health_needs_no_key_and_openapi_documents_auth(auth_on):
    async with client() as c:
        assert (await c.get("/")).status_code == 200
        spec = (await c.get("/openapi.json")).json()
    assert spec["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"
    assert {"401", "429"} <= set(spec["paths"]["/document-check"]["post"]["responses"])


@pytest.mark.anyio
async def test_rate_limit_per_key(processor, caplog):
    clock = FakeClock()
    app.state.api_keys, app.state.rate_limiter = (KEY_A, KEY_B), RateLimiter(2, 60, clock=clock)
    async with client() as c:
        assert [(await post(c, KEY_A)).status_code for _ in range(3)] == [200, 200, 429]
        clock.now += 20
        r = await post(c, KEY_A)
        assert r.status_code == 429 and r.headers["retry-after"] == "40"
        assert r.json() == {"detail": "too many requests, try again later"}
        assert (await post(c, KEY_B)).status_code == 200  # own budget
        assert [(await post(c)).status_code for _ in range(5)] == [401] * 5
        assert (await post(c, KEY_B)).status_code == 200  # the 401s used up nobody's budget
        clock.now += 41
        assert (await post(c, KEY_A)).status_code == 200
    assert "Rate limit reached for key:" in caplog.text
    assert KEY_A not in caplog.text and KEY_B not in caplog.text


@pytest.mark.anyio
async def test_rate_limit_per_ip_when_auth_is_off(processor):
    app.state.api_keys, app.state.rate_limiter = (), RateLimiter(1, 60, clock=FakeClock())
    async with client() as c:
        assert (await post(c)).status_code == 200
        r = await post(c, headers={"X-Forwarded-For": "198.51.100.9"})
        assert r.status_code == 429  # X-Forwarded-For can't dodge the limit
    async with client("198.51.100.7") as other:
        assert (await post(other)).status_code == 200  # a different IP has its own budget
