"""Tests for forensics.solana: keyless RPC client and Helius fallback.

Offline: the JSON-RPC call is stubbed, so no key and no network are needed.
The accountKeys test is a regression for a bug found by live testing: with
encoding=json the RPC returns bare base58 strings, not {"pubkey": ...} dicts.
"""
import pytest

from forensics.solana import Helius, Solana, is_error


def test_is_error_detects_marker():
    assert is_error({"_rpc_error": {"code": -1}}) is True
    assert is_error({"result": 1}) is False
    assert is_error(None) is False
    assert is_error("x") is False


def test_balance_zero_on_rpc_error(monkeypatch):
    s = Solana(["https://example.invalid"])
    monkeypatch.setattr(s, "call", lambda *a, **k: {"_rpc_error": {"code": -1}})
    assert s.balance_sol("abc") == 0.0


def test_signatures_empty_on_rpc_error(monkeypatch):
    s = Solana(["https://example.invalid"])
    monkeypatch.setattr(s, "call", lambda *a, **k: {"_rpc_error": {"code": -1}})
    assert s.signatures("abc") == []


def test_transaction_handles_plain_string_account_keys(monkeypatch):
    s = Solana(["https://example.invalid"])
    payload = {
        "slot": 1, "blockTime": 2,
        "transaction": {"message": {
            "header": {"numRequiredSignatures": 2},
            "accountKeys": ["SignerA", "SignerB", "Other"],
        }},
        "meta": {"err": None, "fee": 5000, "preBalances": [1, 2, 3],
                 "postBalances": [1, 2, 3]},
    }
    monkeypatch.setattr(s, "call", lambda *a, **k: payload)
    tx = s.transaction("sig")
    assert tx["signers"] == ["SignerA", "SignerB"]
    assert tx["account_keys"] == ["SignerA", "SignerB", "Other"]


def test_transaction_handles_dict_account_keys(monkeypatch):
    s = Solana(["https://example.invalid"])
    payload = {
        "slot": 1, "blockTime": 2,
        "transaction": {"message": {
            "header": {"numRequiredSignatures": 1},
            "accountKeys": [{"pubkey": "SignerA", "signer": True}],
        }},
        "meta": {"err": None, "fee": 5000},
    }
    monkeypatch.setattr(s, "call", lambda *a, **k: payload)
    assert s.transaction("sig")["signers"] == ["SignerA"]


def test_transaction_uses_signer_flag_when_header_missing(monkeypatch):
    """Helius jsonParsed omits `header`; the signer flags must win.

    Regression: without this, a co-signed drain tx (attacker + victim) would
    report only the first account as a signer, hiding the key-compromise proof.
    """
    s = Solana(["https://example.invalid"])
    payload = {
        "slot": 1, "blockTime": 2,
        "transaction": {"message": {
            "accountKeys": [
                {"pubkey": "Attacker", "signer": True},
                {"pubkey": "Victim", "signer": True},
                {"pubkey": "Other", "signer": False},
            ],
        }},
        "meta": {"err": None, "fee": 5000},
    }
    monkeypatch.setattr(s, "call", lambda *a, **k: payload)
    assert s.transaction("sig")["signers"] == ["Attacker", "Victim"]


def test_transaction_none_when_missing(monkeypatch):
    s = Solana(["https://example.invalid"])
    monkeypatch.setattr(s, "call", lambda *a, **k: None)
    assert s.transaction("sig") is None


def test_helius_requires_key(monkeypatch):
    monkeypatch.delenv("HELIUS_KEY", raising=False)
    with pytest.raises(RuntimeError):
        Helius()
