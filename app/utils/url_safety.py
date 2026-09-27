"""SSRF protection: decide whether a URL is safe for the server to fetch.

A URL is only allowed if it is http(s), has no embedded credentials, and its
host resolves exclusively to public (globally routable) IP addresses.
"""

import asyncio
import ipaddress
import socket

import httpx

ALLOWED_SCHEMES = {"http", "https"}

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


class UnsafeURLError(Exception):
    """The URL must not be fetched. Messages contain the host only, never the full URL."""


def is_public_ip(ip: IPAddress) -> bool:
    # Unwrap IPv4-mapped IPv6 (e.g. ::ffff:127.0.0.1) so it can't sneak past the checks.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    # is_global is False for private, loopback, link-local, reserved, shared (CGNAT)
    # and unspecified ranges; multicast is checked separately.
    return ip.is_global and not ip.is_multicast


async def resolve_public_ip(url: httpx.URL) -> IPAddress:
    """Validate the URL and return a public IP to connect to.

    Every address the host resolves to must be public; otherwise the URL is rejected.
    Connecting to the returned IP (instead of resolving again) prevents DNS rebinding.
    """
    if url.scheme not in ALLOWED_SCHEMES:
        raise UnsafeURLError(f"scheme '{url.scheme}' is not allowed")
    if url.userinfo:
        raise UnsafeURLError("URLs with embedded credentials are not allowed")
    host = url.host
    if not host:
        raise UnsafeURLError("URL has no host")

    port = url.port or (443 if url.scheme == "https" else 80)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
    except socket.gaierror as exc:
        raise UnsafeURLError(f"could not resolve host '{host}'") from exc

    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    if not addresses:
        raise UnsafeURLError(f"could not resolve host '{host}'")
    if not all(is_public_ip(ip) for ip in addresses):
        raise UnsafeURLError(f"host '{host}' resolves to a non-public address")

    return sorted(addresses, key=lambda ip: ip.version)[0]  # prefer IPv4
