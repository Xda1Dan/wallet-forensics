"""Tests for forensics.providers: DexScreener caching and Etherscan."""
import pytest

from forensics import http
from forensics.providers import DexScreener, Etherscan, Jupiter


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.fixture(autouse=True)
def _clear_cache():
    DexScreener._cache.clear()
    Jupiter._cache.clear()
    yield
    DexScreener._cache.clear()
    Jupiter._cache.clear()


def test_has_pair_true_when_pairs_exist(monkeypatch):
    monkeypatch.setattr(http, "get", lambda *a, **k: FakeResponse(
        [{"priceUsd": "1.0", "dexId": "uniswap", "pairAddress": "0xpair",
          "liquidity": {"usd": 5000}}]))
    assert DexScreener.has_pair("eth", "0xtoken") is True


def test_has_pair_false_for_empty_market(monkeypatch):
    monkeypatch.setattr(http, "get", lambda *a, **k: FakeResponse([]))
    assert DexScreener.has_pair("eth", "0xtoken") is False


def test_has_pair_none_on_transport_failure(monkeypatch):
    monkeypatch.setattr(http, "get",
                        lambda *a, **k: (_ for _ in ()).throw(
                            http.RequestError("down")))
    assert DexScreener.has_pair("eth", "0xtoken") is None


def test_failed_lookup_is_not_cached(monkeypatch):
    """Regression: a transient error must not mark a token pair-less forever."""
    calls = {"n": 0}

    def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise http.RequestError("transient")
        return FakeResponse([{"priceUsd": "1.0", "dexId": "uniswap",
                              "pairAddress": "0xpair", "liquidity": {"usd": 1}}])

    monkeypatch.setattr(http, "get", flaky)
    assert DexScreener.has_pair("eth", "0xtoken") is None   # first: failure
    assert DexScreener.has_pair("eth", "0xtoken") is True   # retried, not cached
    assert calls["n"] == 2


def test_successful_lookup_is_cached(monkeypatch):
    calls = {"n": 0}

    def counted(*_a, **_k):
        calls["n"] += 1
        return FakeResponse([{"priceUsd": "1.0", "dexId": "uniswap",
                              "pairAddress": "0xpair", "liquidity": {"usd": 1}}])

    monkeypatch.setattr(http, "get", counted)
    DexScreener.has_pair("eth", "0xtoken")
    DexScreener.has_pair("eth", "0xtoken")
    DexScreener.token("eth", "0xtoken")
    assert calls["n"] == 1  # one request for three lookups


def test_token_returns_price_fields(monkeypatch):
    monkeypatch.setattr(http, "get", lambda *a, **k: FakeResponse(
        [{"priceUsd": "0.0000059", "dexId": "uniswap", "pairAddress": "0xpair",
          "liquidity": {"usd": 1169.25}}]))
    out = DexScreener.token("eth", "0xtoken")
    assert out["price_usd"] == "0.0000059"
    assert out["liquidity_usd"] == 1169.25
    assert out["dex"] == "uniswap"


def test_token_empty_when_no_market(monkeypatch):
    monkeypatch.setattr(http, "get", lambda *a, **k: FakeResponse([]))
    assert DexScreener.token("eth", "0xtoken") == {}


def test_etherscan_requires_key(monkeypatch):
    monkeypatch.delenv("ETHERSCAN_KEY", raising=False)
    with pytest.raises(RuntimeError):
        Etherscan()


def test_etherscan_call_wraps_transport_error(monkeypatch):
    monkeypatch.setattr(http, "get",
                        lambda *a, **k: (_ for _ in ()).throw(
                            http.RequestError("boom")))
    out = Etherscan(key="k").call(1, "account", "txlist", address="0xabc")
    assert "_rpc_error" in out
    assert out["module"] == "account"


# --- Jupiter: Solana token metadata ---------------------------------------
def test_jupiter_resolves_symbols(monkeypatch):
    monkeypatch.setattr(http, "get", lambda *a, **k: FakeResponse([
        {"id": "MINT1", "symbol": "USDC", "name": "USD Coin", "decimals": 6},
    ]))
    out = Jupiter.tokens(["MINT1"])
    assert out["MINT1"]["symbol"] == "USDC"
    assert out["MINT1"]["decimals"] == 6


def test_jupiter_unknown_mint_is_absent(monkeypatch):
    monkeypatch.setattr(http, "get", lambda *a, **k: FakeResponse([]))
    assert Jupiter.tokens(["MISSING"]) == {}


def test_jupiter_failure_is_not_cached(monkeypatch):
    """A transient error must not blank the symbol for the whole run."""
    calls = {"n": 0}

    def flaky(*_a, **_k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise http.RequestError("transient")
        return FakeResponse([{"id": "MINT1", "symbol": "USDC", "decimals": 6}])

    monkeypatch.setattr(http, "get", flaky)
    assert Jupiter.tokens(["MINT1"]) == {}          # failure: nothing cached
    assert Jupiter.tokens(["MINT1"])["MINT1"]["symbol"] == "USDC"
    assert calls["n"] == 2


def test_jupiter_result_is_cached(monkeypatch):
    calls = {"n": 0}

    def counted(*_a, **_k):
        calls["n"] += 1
        return FakeResponse([{"id": "MINT1", "symbol": "USDC", "decimals": 6}])

    monkeypatch.setattr(http, "get", counted)
    Jupiter.tokens(["MINT1"])
    Jupiter.tokens(["MINT1"])
    assert calls["n"] == 1


def test_jupiter_non_list_body_is_ignored(monkeypatch):
    monkeypatch.setattr(http, "get", lambda *a, **k: FakeResponse({"error": "x"}))
    assert Jupiter.tokens(["MINT1"]) == {}
