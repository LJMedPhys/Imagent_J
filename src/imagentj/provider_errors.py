"""Classification helpers for transient provider transport failures."""

from __future__ import annotations


_TRANSIENT_PROVIDER_MARKERS = (
    "request timed out",
    "read timed out",
    "connection timed out",
    "connection reset",
    "connection refused",
    "server disconnected",
    "service unavailable",
    "bad gateway",
)


def is_transient_provider_error(exc: BaseException) -> bool:
    """Recognize exhausted LLM transport failures without an SDK dependency."""
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_PROVIDER_MARKERS)
