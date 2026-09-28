"""Stage 15 checks: optional API-key authentication and rate limiting. No Ollama needed.

Usage:  python -m scripts.test_security
"""

import asyncio
import logging

import httpx

from app.api.document_check import get_processor
from app.api.security import RateLimiter
from app.config import parse_api_keys
from app.main import app
from app.schemas.response import OwnerResult

KEY_A = "test-key-aaaaaaaaaaaaaaaa"
KEY_B = "test-key-bbbbbbbbbbbbbbbb"
URLS = [f"https://docs.example/{i}.pdf" for i in range(10)]
results: list[bool] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {label}{'  ' + detail if detail else ''}")


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


class LogCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.text = ""

    def emit(self, record: logging.LogRecord) -> None:
        self.text += self.format(record) + "\n"


def limiter_checks() -> None:
    clock = FakeClock()
    limiter = RateLimiter(3, 10, clock=clock)
    allowed = [limiter.hit("a") for _ in range(3)]
    check("first 3 requests in the window are allowed", allowed == [None, None, None])
    clock.now += 4
    retry = limiter.hit("a")
    check("4th request is refused with retry-after = time until the oldest expires", retry == 6, str(retry))
    check("another client has its own budget", limiter.hit("b") is None)
    clock.now += 6
    check("after the window passes, requests are allowed again", limiter.hit("a") is None)

    clock, sliding = FakeClock(), None
    sliding = RateLimiter(2, 10, clock=clock)
    sliding.hit("a"); clock.now += 9; sliding.hit("a"); clock.now += 2  # t=0, t=9, now t=11
    check("sliding window: t=0 has expired at t=11, t=9 has not -> 1 more allowed",
          sliding.hit("a") is None and sliding.hit("a") is not None)

    clock = FakeClock()
    busy = RateLimiter(1, 10, clock=clock)
    for i in range(10_001):
        busy.hit(f"ip:{i}")
    clock.now += 11
    busy.hit("new")
    check("idle clients are forgotten once there are more than 10,000", len(busy._hits) == 1, str(len(busy._hits)))


def config_checks() -> None:
    check("API_KEYS empty -> auth off", parse_api_keys("") == () and parse_api_keys(" , ,") == ())
    check("API_KEYS comma-separated, spaces trimmed", parse_api_keys(f" {KEY_A} ,{KEY_B},") == (KEY_A, KEY_B))
    try:
        parse_api_keys(f"{KEY_A},short-secret")
        check("key under 16 characters is refused", False, "no error")
    except ValueError as exc:
        check("key under 16 characters is refused, message has no key", "short-secret" not in str(exc), str(exc))


async def api_checks() -> None:
    processor = CountingProcessor()
    app.dependency_overrides[get_processor] = lambda: processor
    capture = LogCapture()
    logging.getLogger().addHandler(capture)

    def client(ip: str = "203.0.113.5") -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(ip, 1234)), base_url="http://test")

    async with client() as c:
        # --- auth off (API_KEYS empty) ---
        app.state.api_keys, app.state.rate_limiter = (), None
        r = await c.post("/document-check", json={"documentUrls": URLS})
        check("auth off: no key needed -> 200", r.status_code == 200, str(r.status_code))

        # --- auth on ---
        app.state.api_keys = (KEY_A, KEY_B)
        before = processor.calls
        for label, headers, want in [
            ("no key -> 401", {}, 401),
            ("wrong key -> 401", {"X-API-Key": "test-key-cccccccccccccccc"}, 401),
            ("key with different case -> 401", {"X-API-Key": KEY_A.upper()}, 401),
            ("prefix of a valid key -> 401", {"X-API-Key": KEY_A[:-1]}, 401),
            ("empty key -> 401", {"X-API-Key": ""}, 401),
            ("key A -> 200", {"X-API-Key": KEY_A}, 200),
            ("key B -> 200", {"X-API-Key": KEY_B}, 200),
        ]:
            r = await c.post("/document-check", json={"documentUrls": URLS}, headers=headers)
            ok = r.status_code == want and (want != 401 or (r.json() == {"detail": "missing or invalid API key"}
                                                              and r.headers.get("www-authenticate") == "APIKey"))
            check(f"auth on: {label}", ok, f"{r.status_code} {r.text[:80]}")
        check("rejected requests never reached the processor", processor.calls == before + 2, str(processor.calls - before))

        r = await c.post("/document-check", json={"documentUrls": URLS[:3]})
        check("no key + invalid body -> 401, not 422 (auth runs before validation)", r.status_code == 401, str(r.status_code))
        r = await c.post("/document-check", content=b"{broken", headers={"content-type": "application/json"})
        # FastAPI parses JSON before any dependency runs, so this is a 422. Accepted: it echoes nothing
        # and costs no download or model call.
        check("no key + broken JSON -> 422 json_invalid (parsed before auth), nothing echoed",
              r.status_code == 422 and r.json()["detail"][0]["type"] == "json_invalid" and "broken" not in r.text, r.text[:80])
        r = await c.post("/document-check", json={"documentUrls": URLS[:3]}, headers={"X-API-Key": KEY_A})
        check("valid key + invalid body -> 422", r.status_code == 422, str(r.status_code))
        r = await c.get("/")
        check("GET / (health) needs no key", r.status_code == 200)
        spec = (await c.get("/openapi.json")).json()
        post_spec = spec["paths"]["/document-check"]["post"]
        check("OpenAPI: X-API-Key scheme, 401 and 429 documented",
              spec["components"]["securitySchemes"]["APIKeyHeader"]["name"] == "X-API-Key"
              and {"401", "429"} <= set(post_spec["responses"]), str(list(post_spec["responses"])))
        check("keys never appear in the logs", KEY_A not in capture.text and "cccccccc" not in capture.text)
        check("401 is logged with the client IP", "Rejected request without a valid API key from 203.0.113.5" in capture.text)

        # --- rate limit, per key ---
        clock = FakeClock()
        app.state.rate_limiter = RateLimiter(2, 60, clock=clock)
        codes = [(await c.post("/document-check", json={"documentUrls": URLS}, headers={"X-API-Key": KEY_A})).status_code
                 for _ in range(3)]
        check("rate limit 2/min: key A gets 200, 200, 429", codes == [200, 200, 429], str(codes))
        clock.now += 20
        r = await c.post("/document-check", json={"documentUrls": URLS}, headers={"X-API-Key": KEY_A})
        check("429 has detail and Retry-After (40 s left)", r.status_code == 429 and r.headers.get("retry-after") == "40"
              and r.json() == {"detail": "too many requests, try again later"}, f"{r.status_code} {r.headers.get('retry-after')}")
        r = await c.post("/document-check", json={"documentUrls": URLS}, headers={"X-API-Key": KEY_B})
        check("key B has its own budget -> 200", r.status_code == 200)
        codes = [(await c.post("/document-check", json={"documentUrls": URLS})).status_code for _ in range(5)]
        check("401s do not use up the budget of a valid key", codes == [401] * 5
              and (await c.post("/document-check", json={"documentUrls": URLS}, headers={"X-API-Key": KEY_B})).status_code == 200)
        clock.now += 41
        r = await c.post("/document-check", json={"documentUrls": URLS}, headers={"X-API-Key": KEY_A})
        check("after the window, key A is allowed again", r.status_code == 200, str(r.status_code))
        check("keys never appear in the logs (rate-limit lines use a hash)", KEY_A not in capture.text and KEY_B not in capture.text
              and "Rate limit reached for key:" in capture.text)

        # --- rate limit, per IP when auth is off ---
        app.state.api_keys = ()
        app.state.rate_limiter = RateLimiter(1, 60, clock=FakeClock())
        first = await c.post("/document-check", json={"documentUrls": URLS})
        spoofed = await c.post("/document-check", json={"documentUrls": URLS}, headers={"X-Forwarded-For": "198.51.100.9"})
        check("auth off: limited per client IP; X-Forwarded-For can't dodge it", (first.status_code, spoofed.status_code) == (200, 429))
    async with client("198.51.100.7") as other:
        r = await other.post("/document-check", json={"documentUrls": URLS})
        check("a different IP has its own budget", r.status_code == 200, str(r.status_code))

    logging.getLogger().removeHandler(capture)
    app.dependency_overrides.clear()


async def main() -> None:
    limiter_checks()
    config_checks()
    await api_checks()
    print(f"\n{sum(results)}/{len(results)} passed")


if __name__ == "__main__":
    asyncio.run(main())
