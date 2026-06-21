from __future__ import annotations

import socket
from typing import Any
from urllib.parse import urlparse


def probe_host_port(host: str, port: int, timeout: float = 5.0) -> dict[str, Any]:
    result: dict[str, Any] = {
        "host": host,
        "port": port,
        "dns_ok": False,
        "tcp_ok": False,
    }
    try:
        addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        result["dns_ok"] = True
        result["resolved_addresses"] = sorted({item[4][0] for item in addresses})
    except socket.gaierror as exc:
        result["dns_error"] = str(exc)
        return result

    last_error: OSError | None = None
    for family, socktype, proto, _, sockaddr in addresses:
        try:
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(timeout)
                sock.connect(sockaddr)
            result["tcp_ok"] = True
            result["connected_address"] = sockaddr[0]
            return result
        except OSError as exc:
            last_error = exc

    if last_error is not None:
        result["tcp_error_type"] = last_error.__class__.__name__
        result["tcp_error"] = str(last_error)
    return result


def probe_url(url: str, timeout: float = 5.0) -> dict[str, Any]:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return {
            "url": url,
            "dns_ok": False,
            "tcp_ok": False,
            "parse_error": "URL does not contain a hostname.",
        }
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    result = probe_host_port(host, port, timeout=timeout)
    result["url"] = url
    result["scheme"] = parsed.scheme or "https"
    return result
