"""Tests for forensics.http key redaction and retry behaviour."""
import pytest

from forensics import http


@pytest.mark.parametrize("text,secret", [
    ("https://eth-mainnet.g.alchemy.com/v2/abcDEF123456xyz", "abcDEF123456xyz"),
    ("https://api.etherscan.io/v2/api?apikey=K1K2K3K4K5K6K7K8", "K1K2K3K4K5K6K7K8"),
    ("https://mainnet.helius-rpc.com/?api-key=aaaa-bbbb-cccc-dddd", "aaaa-bbbb-cccc-dddd"),
    ("Authorization: Bearer sk_live_1234567890abcdef", "sk_live_1234567890abcdef"),
])
def test_redact_removes_keys(text, secret):
    out = http.redact(text)
    assert secret not in out
    assert "***" in out


def test_redact_keeps_url_shape():
    out = http.redact("https://eth-mainnet.g.alchemy.com/v2/supersecretkey123")
    assert out == "https://eth-mainnet.g.alchemy.com/v2/***"


def test_redact_is_safe_on_plain_text():
    assert http.redact("all endpoints failed") == "all endpoints failed"
    assert http.redact(None) == "None"


def test_request_error_message_is_redacted(monkeypatch):
    """A failing request must not leak the key through its exception text."""
    class Boom:
        status_code = 503
        headers = {}

    monkeypatch.setattr(http._session, "request", lambda *a, **k: Boom())
    monkeypatch.setattr(http.time, "sleep", lambda *_: None)
    url = "https://eth-mainnet.g.alchemy.com/v2/topsecretkey12345"
    with pytest.raises(http.RequestError) as exc:
        http.request("POST", url, retries=2)
    assert "topsecretkey12345" not in str(exc.value)
    assert "***" in str(exc.value)


def test_retry_after_is_honoured(monkeypatch):
    sleeps = []

    class TooMany:
        status_code = 429
        headers = {"Retry-After": "2"}

    monkeypatch.setattr(http._session, "request", lambda *a, **k: TooMany())
    monkeypatch.setattr(http.time, "sleep", lambda s: sleeps.append(s))
    with pytest.raises(http.RequestError):
        http.request("GET", "https://example.com", retries=3)
    assert sleeps == [2.0, 2.0]


def test_retry_after_is_capped(monkeypatch):
    sleeps = []

    class TooMany:
        status_code = 429
        headers = {"Retry-After": "9999"}

    monkeypatch.setattr(http._session, "request", lambda *a, **k: TooMany())
    monkeypatch.setattr(http.time, "sleep", lambda s: sleeps.append(s))
    with pytest.raises(http.RequestError):
        http.request("GET", "https://example.com", retries=2)
    assert sleeps == [float(http.MAX_RETRY_AFTER)]


def test_non_retryable_status_is_returned(monkeypatch):
    class NotFound:
        status_code = 404
        headers = {}

    monkeypatch.setattr(http._session, "request", lambda *a, **k: NotFound())
    response = http.get("https://example.com/missing")
    assert response.status_code == 404
