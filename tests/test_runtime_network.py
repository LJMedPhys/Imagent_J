from imagentj.runtime_network import rewrite_benchmark_loopback_url


def test_rewrites_ipv4_loopback_with_port_and_path():
    assert rewrite_benchmark_loopback_url("http://127.0.0.1:18000/v1") == (
        "http://host.docker.internal:18000/v1"
    )


def test_rewrites_localhost_case_insensitively():
    assert rewrite_benchmark_loopback_url("http://LOCALHOST:8000/v1") == (
        "http://host.docker.internal:8000/v1"
    )


def test_rewrites_ipv6_loopback_and_preserves_url_components():
    assert rewrite_benchmark_loopback_url(
        "https://user:pass@[::1]:9443/v1/models?ready=1#status"
    ) == "https://user:pass@host.docker.internal:9443/v1/models?ready=1#status"


def test_leaves_non_loopback_host_unchanged():
    url = "http://192.168.50.12:18000/v1"
    assert rewrite_benchmark_loopback_url(url) == url


def test_leaves_existing_docker_gateway_unchanged():
    url = "http://host.docker.internal:18000/v1"
    assert rewrite_benchmark_loopback_url(url) == url


def test_leaves_malformed_or_relative_values_unchanged():
    assert rewrite_benchmark_loopback_url("localhost:18000/v1") == "localhost:18000/v1"
