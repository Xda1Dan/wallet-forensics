"""Tests for forensics.bridges: Relay request resolution.

Offline: ``http.get`` is stubbed. The emphasis is on the failure paths, because
the dangerous bug here is mis-attributing a destination -- returning a
neighbouring request's recipient for a hash that does not match.
"""
import pytest

from forensics import bridges, http

SOL_TX = "3FamWzqjYzfrCjdugowbucFbXrSNjTP3EENQA1U9xpYQ7RpSms49WuTgmoPtwYJy8SdfAT9Jms6n9tTsYrrFWqsd"
VICTIM = "5gNXSccDf8M6PbqsFWagLAoJS6FMdZpGVkHpwsiF4Pfo"
ATTACKER = "0x243f8FbC2b6CB5924b37Afbebab0de95C9249E74"
EVM_TX = "0xcb25c02b73745fb892471dea35760244f01fad1039c8b30943c5a2407ee980bb"


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _relay_request(tx_hash=SOL_TX, out_hash=EVM_TX, out_chain=4663,
                   recipient=ATTACKER, status="success", out_ts=1789410269,
                   in_ts=1789410268):
    return {
        "id": "0xabc",
        "status": status,
        "user": VICTIM,
        "recipient": recipient,
        "data": {
            "feesUsd": {"gas": "0.006925"},
            "metadata": {
                "currencyIn": {"amountFormatted": "14.104650422",
                               "amountUsd": "1457.74",
                               "currency": {"symbol": "SOL"}},
                "currencyOut": {"amountFormatted": "0.570872108126369208",
                                "amountUsd": "1449.72",
                                "currency": {"symbol": "ETH"}},
                "route": {},
            },
            "inTxs": [{"hash": tx_hash, "chainId": 792703809,
                       "timestamp": in_ts}],
            "outTxs": ([{"hash": out_hash, "chainId": out_chain,
                         "timestamp": out_ts}] if out_hash else []),
        },
    }


def _stub(monkeypatch, response):
    monkeypatch.setattr(http, "get", lambda *a, **k: response)


# --------------------------------------------------------------------------
# happy path
# --------------------------------------------------------------------------
def test_resolves_origin_and_destination(monkeypatch):
    _stub(monkeypatch, FakeResponse(200, {"requests": [_relay_request()]}))
    result = bridges.resolve(SOL_TX)
    assert result["found"] is True
    assert result["origin"]["chain"] == "Solana"
    assert result["origin"]["sender"] == VICTIM
    assert result["destination"]["chain"] == "Robinhood Chain"
    assert result["destination"]["recipient"] == ATTACKER
    assert result["destination"]["tx"] == EVM_TX
    assert result["destination"]["symbol"] == "ETH"


def test_reports_settlement_delay(monkeypatch):
    _stub(monkeypatch, FakeResponse(
        200, {"requests": [_relay_request(in_ts=100, out_ts=103)]}))
    assert bridges.resolve(SOL_TX)["settled_in_seconds"] == 3


# --------------------------------------------------------------------------
# the dangerous paths: never attribute the wrong destination
# --------------------------------------------------------------------------
def test_hash_mismatch_is_not_found(monkeypatch):
    """Relay returning unrelated requests must NOT be read as a match."""
    other = _relay_request(tx_hash="SomeOtherTxHash", recipient="0xDEAD")
    _stub(monkeypatch, FakeResponse(200, {"requests": [other]}))
    result = bridges.resolve(SOL_TX)
    assert result["found"] is False
    assert "recipient" not in result


def test_empty_requests_is_not_found(monkeypatch):
    _stub(monkeypatch, FakeResponse(200, {"requests": []}))
    assert bridges.resolve(SOL_TX)["found"] is False


def test_missing_requests_key_is_not_found(monkeypatch):
    _stub(monkeypatch, FakeResponse(200, {}))
    assert bridges.resolve(SOL_TX)["found"] is False


def test_picks_the_matching_request_among_several(monkeypatch):
    good = _relay_request()
    bad = _relay_request(tx_hash="nope", recipient="0xBAD")
    _stub(monkeypatch, FakeResponse(200, {"requests": [bad, good]}))
    result = bridges.resolve(SOL_TX)
    assert result["destination"]["recipient"] == ATTACKER


# --------------------------------------------------------------------------
# hash comparison semantics
# --------------------------------------------------------------------------
def test_evm_hash_match_is_case_insensitive(monkeypatch):
    _stub(monkeypatch, FakeResponse(
        200, {"requests": [_relay_request(tx_hash=EVM_TX.upper())]}))
    assert bridges.resolve(EVM_TX)["found"] is True


def test_base58_hash_match_is_case_sensitive(monkeypatch):
    """Base58 is case-sensitive: a differing case must not be treated as equal."""
    swapped = SOL_TX.swapcase()
    _stub(monkeypatch, FakeResponse(
        200, {"requests": [_relay_request(tx_hash=swapped)]}))
    assert bridges.resolve(SOL_TX)["found"] is False


# --------------------------------------------------------------------------
# transport and provider failures
# --------------------------------------------------------------------------
def test_transport_error_is_verbose_not_raised(monkeypatch):
    def boom(*a, **k):
        raise http.RequestError("relay down")
    monkeypatch.setattr(http, "get", boom)
    result = bridges.resolve(SOL_TX)
    assert result["found"] is False
    assert "relay down" in result["attempts"][0]["reason"]


def test_non_200_is_not_found(monkeypatch):
    _stub(monkeypatch, FakeResponse(500, None))
    assert bridges.resolve(SOL_TX)["found"] is False


def test_non_json_body_is_not_found(monkeypatch):
    _stub(monkeypatch, FakeResponse(200, None, text="<html>"))
    assert bridges.resolve(SOL_TX)["found"] is False


# --------------------------------------------------------------------------
# incomplete / pending requests
# --------------------------------------------------------------------------
def test_pending_request_has_no_destination_tx_but_no_crash(monkeypatch):
    _stub(monkeypatch, FakeResponse(
        200, {"requests": [_relay_request(out_hash=None, status="pending")]}))
    result = bridges.resolve(SOL_TX)
    assert result["found"] is True
    assert result["status"] == "pending"
    assert result["destination"]["tx"] is None
    assert "note" in result


def test_recipient_is_always_surfaced(monkeypatch):
    """Even with no payout yet, the named recipient is the actionable value."""
    _stub(monkeypatch, FakeResponse(
        200, {"requests": [_relay_request(out_hash=None)]}))
    assert bridges.resolve(SOL_TX)["destination"]["recipient"] == ATTACKER


# --------------------------------------------------------------------------
# chain naming
# --------------------------------------------------------------------------
def test_chain_name_known_and_unknown():
    assert bridges.chain_name(4663) == "Robinhood Chain"
    assert bridges.chain_name(792703809) == "Solana"
    assert bridges.chain_name(999999) == "chain 999999"
    assert bridges.chain_name(None) == "unknown"


def test_chain_names_falls_back_when_api_unreachable(monkeypatch):
    monkeypatch.setattr(bridges, "_chain_cache", None)
    monkeypatch.setattr(http, "get", lambda *a, **k: (_ for _ in ()).throw(
        http.RequestError("no network")))
    # Builtin map still names the common chains.
    assert bridges.chain_name(1) == "Ethereum"
    monkeypatch.setattr(bridges, "_chain_cache", None)


# --------------------------------------------------------------------------
# malformed payloads must not crash
# --------------------------------------------------------------------------
def test_minimal_payload_does_not_crash(monkeypatch):
    """Only the fields needed to match; everything else absent."""
    minimal = {"data": {"inTxs": [{"hash": SOL_TX}]}, "user": VICTIM,
               "recipient": ATTACKER}
    _stub(monkeypatch, FakeResponse(200, {"requests": [minimal]}))
    result = bridges.resolve(SOL_TX)
    assert result["found"] is True
    assert result["destination"]["recipient"] == ATTACKER
    assert result["destination"]["tx"] is None
    assert result["destination"]["chain"] == "unknown"


def test_route_chain_id_used_when_out_tx_absent(monkeypatch):
    """No outTxs: fall back to the route's destination chain for naming."""
    request = _relay_request(out_hash=None)
    request["data"]["metadata"]["route"] = {
        "destination": {"inputCurrency": {"currency": {"chainId": 8453}}}}
    _stub(monkeypatch, FakeResponse(200, {"requests": [request]}))
    assert bridges.resolve(SOL_TX)["destination"]["chain"] == "Base"


def test_request_without_data_key(monkeypatch):
    _stub(monkeypatch, FakeResponse(200, {"requests": [{"id": "x"}]}))
    assert bridges.resolve(SOL_TX)["found"] is False


def test_null_requests_value(monkeypatch):
    _stub(monkeypatch, FakeResponse(200, {"requests": None}))
    assert bridges.resolve(SOL_TX)["found"] is False


def test_fuzz_never_raises(monkeypatch):
    """A resolver must return an envelope for any input, never raise."""
    _stub(monkeypatch, FakeResponse(200, {"requests": []}))
    for value in ["", " ", "0x", "x" * 300, "héllo", "\n\t", "🎉", None]:
        result = bridges.resolve(value)
        assert "found" in result
