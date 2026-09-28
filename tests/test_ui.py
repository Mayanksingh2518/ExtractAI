"""Stage 19: the web page at /ui/ (served files, security headers, no HTML injection in app.js)."""

import re
from pathlib import Path

import httpx
import pytest

from app.main import app

pytestmark = pytest.mark.anyio
STATIC = Path("app/static")


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_ui_redirects_to_trailing_slash(client):
    r = await client.get("/ui")
    assert r.status_code == 307 and r.headers["location"].endswith("/ui/")


@pytest.mark.parametrize("path, content_type", [
    ("/ui/", "text/html"), ("/ui/app.js", "javascript"), ("/ui/style.css", "text/css"), ("/ui/favicon.svg", "image/svg+xml"),
])
async def test_files_are_served_with_security_headers(path, content_type, client):
    r = await client.get(path)
    assert r.status_code == 200 and content_type in r.headers["content-type"]
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"


@pytest.mark.parametrize("path", ["/ui/../config.py", "/ui/%2e%2e/config.py", "/ui/missing.js"])
async def test_nothing_outside_static_is_served(path, client):
    assert (await client.get(path)).status_code == 404


async def test_api_routes_have_no_ui_headers(client):
    assert "content-security-policy" not in (await client.get("/")).headers


def test_page_never_injects_html():
    """Server data (including model output) must be shown with textContent only."""
    js = (STATIC / "app.js").read_text()
    for risky in (".innerHTML", ".outerHTML", ".insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert risky not in js, risky


def test_page_has_no_inline_code_or_external_resources():
    """The CSP only allows the page's own files, so inline scripts, styles or CDNs would silently break."""
    html = (STATIC / "index.html").read_text()
    assert "<script>" not in html and "style=" not in html
    assert not re.search(r"\son[a-z]+\s*=", html)  # inline event handlers like onclick=
    assert not re.search(r"(src|href)\s*=\s*\"(https?:)?//", html)  # no CDN or other external files
