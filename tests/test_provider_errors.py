import pytest

from imagentj.provider_errors import (
    is_transient_provider_error,
)


@pytest.mark.parametrize(
    "exc",
    [
        TimeoutError("socket stalled"),
        ConnectionError("connection reset by peer"),
        RuntimeError("Request timed out."),
        RuntimeError("upstream server disconnected without sending a response"),
        RuntimeError("502 Bad Gateway"),
    ],
)
def test_transient_provider_error_markers(exc):
    assert is_transient_provider_error(exc)


@pytest.mark.parametrize(
    "exc",
    [ValueError("bad schema"), RuntimeError("script failed"), KeyError("missing")],
)
def test_non_transport_errors_are_not_hidden(exc):
    assert not is_transient_provider_error(exc)
