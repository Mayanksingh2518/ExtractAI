"""app/utils/url_safety.py: SSRF protection (the Stage 4 cases, now kept as tests)."""

import httpx
import pytest

from app.utils.url_safety import UnsafeURLError, resolve_public_ip

pytestmark = pytest.mark.anyio

# Blocked without any DNS lookup on the internet (IP literals, localhost, bad schemes, credentials).
BLOCKED_OFFLINE = [
    "http://127.0.0.1/", "http://localhost/", "http://10.1.2.3/", "http://192.168.1.1/", "http://172.16.0.1/",
    "http://169.254.169.254/latest/meta-data/", "http://0.0.0.0/", "http://100.64.0.1/", "http://224.0.0.1/",
    "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://[fe80::1]/", "http://[fd00::1]/",
    "http://2130706433/",  # 127.0.0.1 written as a decimal number
    "ftp://example.com/a.pdf", "file:///etc/passwd", "https://user:pass@example.com/a.pdf",
]

# Names that need public DNS to resolve.
BLOCKED_ONLINE = [
    "http://127.0.0.1.nip.io/", "http://10.0.0.1.nip.io/",  # public names that resolve to private IPs
    "https://does-not-exist.invalid/",  # unresolvable
]
ALLOWED_ONLINE = ["https://example.com/a.pdf", "https://www.w3.org/"]


@pytest.mark.parametrize("url", BLOCKED_OFFLINE)
async def test_blocked(url):
    with pytest.raises(UnsafeURLError) as exc:
        await resolve_public_ip(httpx.URL(url))
    assert "pass" not in str(exc.value)  # messages never repeat credentials or the full URL


@pytest.mark.network
@pytest.mark.parametrize("url", BLOCKED_ONLINE)
async def test_blocked_after_dns(url):
    with pytest.raises(UnsafeURLError):
        await resolve_public_ip(httpx.URL(url))


@pytest.mark.network
@pytest.mark.parametrize("url", ALLOWED_ONLINE)
async def test_allowed(url):
    ip = await resolve_public_ip(httpx.URL(url))
    assert ip.is_global
