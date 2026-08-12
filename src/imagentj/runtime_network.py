"""Runtime URL normalization for containerized Agentic-J sessions."""

from __future__ import annotations

import ipaddress
import sys
from urllib.parse import SplitResult, urlsplit, urlunsplit


_DOCKER_HOST_GATEWAY = "host.docker.internal"


def rewrite_benchmark_loopback_url(url: str) -> str:
    """Route a host-loopback LLM URL through Docker's host gateway.

    The benchmark adapter starts an isolated bridge-network container.  A URL
    such as ``http://127.0.0.1:18000/v1`` works for host-network Compose runs,
    but refers to the benchmark container itself under the adapter.  Compose
    already defines ``host.docker.internal:host-gateway``; rewrite only literal
    loopback hosts and preserve credentials, ports, paths, queries, and
    fragments.  Non-loopback and malformed URLs are returned unchanged.
    """
    if not url:
        return url
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
        if not hostname:
            return url
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = hostname.rstrip(".").lower() == "localhost"
        if not is_loopback:
            return url

        userinfo = ""
        if parsed.username is not None:
            userinfo = parsed.username
            if parsed.password is not None:
                userinfo += f":{parsed.password}"
            userinfo += "@"
        port = f":{parsed.port}" if parsed.port is not None else ""
        replaced = SplitResult(
            parsed.scheme,
            f"{userinfo}{_DOCKER_HOST_GATEWAY}{port}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
        return urlunsplit(replaced)
    except (ValueError, TypeError):
        return url


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: runtime_network.py LOCAL_LLM_BASE_URL")
    print(rewrite_benchmark_loopback_url(sys.argv[1]))
