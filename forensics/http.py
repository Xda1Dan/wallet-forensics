"""Shared HTTP transport.

One pooled requests.Session for the whole process; retry and backoff live here
so no other module deals with them. Provider keys travel inside URLs (Alchemy
``/v2/<key>``, Etherscan ``?apikey=``, Helius ``?api-key=``), so anything that
formats a URL into an error message runs it through redact first.
"""
from __future__ import annotations

import re
import time

import requests
from requests.adapters import HTTPAdapter

# Statuses worth retrying: rate limits and transient server errors.
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 4
BACKOFF = 0.6
MAX_RETRY_AFTER = 30

_session = requests.Session()
_session.mount("https://", HTTPAdapter(pool_connections=32, pool_maxsize=64))
_session.mount("http://", HTTPAdapter(pool_connections=32, pool_maxsize=64))

# Key-bearing URL / header shapes. The key is replaced with ``***`` while the
# surrounding shape is kept, so an error still shows *which* provider failed.
_REDACTIONS = (
    re.compile(r"(/v2/)[A-Za-z0-9_\-]{8,}"),                        # Alchemy path key
    re.compile(r"([?&](?:api-?key|key)=)[A-Za-z0-9_\-]{8,}", re.I),  # query keys
    re.compile(r"(Bearer\s+)[A-Za-z0-9_\-.]{8,}", re.I),             # auth headers
)


class RequestError(RuntimeError):
    """A request failed after exhausting retries."""


def redact(text) -> str:
    """Replace provider keys in ``text`` with ``***``, keeping the URL shape."""
    out = str(text)
    for pattern in _REDACTIONS:
        out = pattern.sub(r"\1***", out)
    return out


def _retry_delay(response, attempt: int) -> float:
    """Seconds to wait before the next attempt, honouring ``Retry-After``."""
    header = response.headers.get("Retry-After")
    if header:
        try:
            return min(float(header), MAX_RETRY_AFTER)
        except (TypeError, ValueError):
            pass
    return BACKOFF * (attempt + 1)


def request(method: str, url: str, *, retries: int = DEFAULT_RETRIES, **kwargs):
    """Perform an HTTP request, retrying transient failures.

    Raises RequestError if every attempt fails. A non-retryable
    response (e.g. 404) is returned to the caller as-is.
    """
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            response = _session.request(method, url, **kwargs)
        except requests.RequestException as exc:
            last = exc
            delay = BACKOFF * (attempt + 1)
        else:
            if response.status_code not in RETRY_STATUS:
                return response
            last = RequestError(f"HTTP {response.status_code}")
            delay = _retry_delay(response, attempt)
        if attempt < retries - 1:
            time.sleep(delay)
    raise RequestError(redact(f"{method} {url} failed after {retries} tries: {last}"))


def get(url: str, **kwargs):
    return request("GET", url, **kwargs)


def post(url: str, **kwargs):
    return request("POST", url, **kwargs)
