"""Tests for forensics.evm: the Alchemy and RPC clients.

These are offline: the HTTP layer is stubbed so no key and no network are
needed. Two of them are regressions for bugs found by live testing.
"""
import pytest

from forensics import http
from forensics.evm import (Alchemy, Rpc, RpcError, is_error, map_concurrent,
                           normalize_transfer)


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


# --- is_error / Rpc guards ------------------------------------------------

def test_is_error_detects_marker():
    assert is_error({"_rpc_error": {"code": -1}}) is True
    assert is_error({"result": "0x1"}) is False
    assert is_error(None) is False
    assert is_error("0x1") is False


def test_balance_returns_zero_on_rpc_error(monkeypatch):
    rpc = Rpc("eth", ["https://example.invalid"])
    monkeypatch.setattr(rpc, "call", lambda *a, **k: {"_rpc_error": {"code": -1}})
    assert rpc.balance("0xabc") == 0
    assert rpc.nonce("0xabc") == 0
    assert rpc.code("0xabc") == "0x"


def test_balance_scales_hex(monkeypatch):
    rpc = Rpc("eth", ["https://example.invalid"])
    monkeypatch.setattr(rpc, "call", lambda *a, **k: "0xde0b6b3a7640000")
    assert rpc.balance("0xabc") == 10 ** 18


def test_batch_surfaces_per_call_errors(monkeypatch):
    rpc = Rpc("eth", ["https://example.invalid"])
    payload = [
        {"jsonrpc": "2.0", "id": 0, "result": "0x1"},
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "boom"}},
    ]
    monkeypatch.setattr(http, "post", lambda *a, **k: FakeResponse(payload))
    results = rpc.batch([("eth_getBalance", ["0xa", "latest"]),
                         ("eth_getBalance", ["0xb", "latest"])])
    assert results[0] == "0x1"
    assert is_error(results[1])
    assert results[1]["_rpc_error"]["message"] == "boom"


def test_call_redacts_key_in_raised_error(monkeypatch):
    rpc = Rpc("eth", ["https://eth-mainnet.g.alchemy.com/v2/topsecretkey12345"])
    monkeypatch.setattr(http, "post",
                        lambda *a, **k: (_ for _ in ()).throw(
                            http.RequestError("boom")))
    with pytest.raises(RpcError) as exc:
        rpc.call("eth_blockNumber", [])
    assert "topsecretkey12345" not in str(exc.value)
    assert "***" in str(exc.value)


def test_map_concurrent_preserves_order():
    assert map_concurrent(lambda x: x * 2, [1, 2, 3, 4]) == [2, 4, 6, 8]
    assert map_concurrent(lambda x: x, []) == []
    assert map_concurrent(lambda x: x + 1, [5]) == [6]


# --- Alchemy ---------------------------------------------------------------

def test_alchemy_last_error_initialised():
    """Regression: `price` read last_error before _rpc ever ran and crashed."""
    client = Alchemy(key="test-key")
    assert client.last_error is None


def test_alchemy_requires_key(monkeypatch):
    monkeypatch.delenv("ALCHEMY_KEY", raising=False)
    with pytest.raises(RuntimeError):
        Alchemy()


def test_alchemy_rpc_captures_error(monkeypatch):
    client = Alchemy(key="test-key")
    monkeypatch.setattr(http, "post", lambda *a, **k: FakeResponse(
        {"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "nope"}}))
    assert client._rpc("eth", "alchemy_getAssetTransfers", [{}]) is None
    assert client.last_error == {"code": -32600, "message": "nope"}


def test_alchemy_rpc_clears_error_on_success(monkeypatch):
    client = Alchemy(key="test-key")
    client.last_error = {"code": -1}
    monkeypatch.setattr(http, "post", lambda *a, **k: FakeResponse(
        {"jsonrpc": "2.0", "id": 1, "result": {"transfers": []}}))
    assert client._rpc("eth", "alchemy_getAssetTransfers", [{}]) == {"transfers": []}
    assert client.last_error is None


def test_alchemy_rpc_handles_transport_failure(monkeypatch):
    client = Alchemy(key="test-key")
    monkeypatch.setattr(http, "post",
                        lambda *a, **k: (_ for _ in ()).throw(
                            http.RequestError("down")))
    assert client._rpc("eth", "eth_blockNumber", []) is None
    assert client.last_error == "down"


def test_price_by_symbol_parses_quotes(monkeypatch):
    client = Alchemy(key="test-key")
    monkeypatch.setattr(http, "get", lambda *a, **k: FakeResponse({"data": [
        {"symbol": "ETH", "prices": [{"value": "2600.00"}]},
        {"symbol": "BNB", "prices": []},
        {"symbol": "HYPE", "error": "no data", "prices": [{"value": "1"}]},
    ]}))
    prices = client.price_by_symbol(["ETH", "BNB", "HYPE"])
    assert prices == {"ETH": "2600.00"}
    assert client.last_error is None


def test_price_by_symbol_records_failure(monkeypatch):
    """Regression: price errors used to be reported as `error: null`."""
    client = Alchemy(key="test-key")
    monkeypatch.setattr(http, "get",
                        lambda *a, **k: (_ for _ in ()).throw(
                            http.RequestError("prices down")))
    assert client.price_by_symbol(["ETH"]) == {}
    assert client.last_error == "prices down"


def test_price_at_returns_series(monkeypatch):
    client = Alchemy(key="test-key")
    monkeypatch.setattr(http, "post", lambda *a, **k: FakeResponse(
        {"data": [{"value": "2622.42"}]}))
    assert client.price_at("ETH", "a", "b") == [{"value": "2622.42"}]
    assert client.last_error is None


# --- normalize_transfer (the one canonical row builder) --------------------

def _erc20(value="0x" + format(6877 * 10 ** 6, "x"), decimal="0x6"):
    return {"hash": "0xabc", "blockNum": "0x1", "category": "erc20",
            "asset": "USDC", "from": "0xAAA", "to": "0xBBB",
            "metadata": {"blockTimestamp": "2026-04-02T20:45:47.000Z"},
            "rawContract": {"address": "0xUSDC", "value": value, "decimal": decimal}}


def test_normalize_transfer_scales_with_decimal():
    row = normalize_transfer(_erc20())
    assert row["amount"] == 6877.0
    assert row["contract"] == "0xUSDC"
    assert row["time"] == "2026-04-02T20:45:47.000Z"
    assert "amount_note" not in row


def test_normalize_transfer_uses_decimals_map_when_decimal_null():
    """Regression: Arc native USDC had decimal:null and rendered amount:null."""
    row = normalize_transfer(_erc20(decimal=None), {"0xUSDC": 6})
    assert row["amount"] == 6877.0
    assert "amount_raw" not in row


def test_normalize_transfer_flags_unresolved_decimals():
    """No decimal and no map: hand back the raw integer, explicitly labelled."""
    row = normalize_transfer(_erc20(decimal=None))
    assert row["amount"] is None
    assert row["amount_raw"] == "0x" + format(6877 * 10 ** 6, "x")
    assert "decimals unknown" in row["amount_note"]


def test_normalize_transfer_native_passes_value_through():
    row = normalize_transfer({"hash": "0x1", "category": "external",
                              "value": 0.02, "from": "0xAAA", "to": "0xBBB"})
    assert row["amount"] == 0.02
    assert row["contract"] is None


def test_normalize_transfer_normalizes_address_case():
    row = normalize_transfer(_erc20())
    assert row["from"] == "0xaaa" and row["to"] == "0xbbb"
