"""Tests for forensics.identify: address classification and labelling."""
import pytest

from forensics import identify
from forensics.solana import Solana


# --- chain detection ------------------------------------------------------
def test_detect_chain_base58_is_solana():
    assert identify.detect_chain("5gNXSccDf8M6PbqsFWagLAoJS6FMdZpGVkHpwsiF4Pfo") == "sol"
    assert identify.is_solana("7uTT8Xi5RWXzy7h9XL244GRgEycDYDhLjr3ZyNdXi8pZ") is True


def test_detect_chain_hex_is_evm():
    assert identify.detect_chain("0x243f8FbC2b6CB5924b37Afbebab0de95C9249E74") == "eth"
    assert identify.is_solana("0x243f8FbC2b6CB5924b37Afbebab0de95C9249E74") is False


def test_detect_chain_rejects_garbage():
    assert identify.is_solana("not_a_real_address_!!") is False


# --- missing input --------------------------------------------------------
def test_identify_requires_address():
    assert identify.identify("").get("_error")


# --- known labels resolve without a network call --------------------------
def test_identify_reports_known_label(monkeypatch):
    monkeypatch.setattr(identify, "_identify_solana", lambda a: {"type": "wallet"})
    monkeypatch.setattr(identify, "_external_labels", lambda c, a: {})
    out = identify.identify("7uTT8Xi5RWXzy7h9XL244GRgEycDYDhLjr3ZyNdXi8pZ")
    assert out["known_label"]["kind"] == "bridge"
    assert "Relay" in out["known_label"]["name"]


def test_identify_explorer_link(monkeypatch):
    monkeypatch.setattr(identify, "_identify_solana", lambda a: {})
    monkeypatch.setattr(identify, "_external_labels", lambda c, a: {})
    out = identify.identify("5gNXSccDf8M6PbqsFWagLAoJS6FMdZpGVkHpwsiF4Pfo")
    assert out["explorer"].startswith("https://solscan.io/account/")


# --- Solana classification ------------------------------------------------
def _account(value):
    return {"jsonrpc": "2.0", "id": 1, "result": {"value": value}}


def test_classify_wallet(monkeypatch):
    monkeypatch.setattr(Solana, "call", lambda self, m, p: {
        "value": {"executable": False, "owner": "11111111111111111111111111111111",
                  "space": 0, "lamports": 100, "data": ["", "base64"]}})
    out = identify._identify_solana("SomeWallet")
    assert out["type"] == "wallet"
    assert out["owner_program_name"] == "System Program"


def test_classify_program_by_builtin(monkeypatch):
    monkeypatch.setattr(Solana, "call", lambda self, m, p: {
        "value": {"executable": True, "owner": "BPFLoaderUpgradeab1e11111111111111111111111",
                  "space": 36, "lamports": 1, "data": ["", "base64"]}})
    monkeypatch.setattr(identify, "_external_labels", lambda c, a: {})
    out = identify.identify("99vQwtBwYtrqqD9YSXbdum3KBdxPAVxYTaQ3cfnJSrN2")
    assert out["type"] == "program"
    assert "Relay" in out["name"]


def test_classify_mint(monkeypatch):
    monkeypatch.setattr(Solana, "call", lambda self, m, p: {
        "value": {"executable": False, "owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                  "space": 82, "lamports": 1,
                  "data": {"parsed": {"type": "mint", "info": {"decimals": 6}}}}})
    out = identify._identify_solana("SomeMint")
    assert out["type"] == "spl_mint"


def test_classify_token_account(monkeypatch):
    monkeypatch.setattr(Solana, "call", lambda self, m, p: {
        "value": {"executable": False, "owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                  "space": 165, "lamports": 1,
                  "data": {"parsed": {"type": "account", "info": {}}}}})
    assert identify._identify_solana("SomeAta")["type"] == "spl_token_account"


def test_classify_uninitialized(monkeypatch):
    monkeypatch.setattr(Solana, "call", lambda self, m, p: {"value": None})
    out = identify._identify_solana("NothingHere")
    assert out["type"] == "uninitialized"


def test_classify_handles_rpc_error(monkeypatch):
    monkeypatch.setattr(Solana, "call",
                        lambda self, m, p: {"_rpc_error": {"code": -32602}})
    assert "_rpc_error" in identify._identify_solana("Bad")


# --- external labels must not silently claim "no label" -------------------
def test_external_labels_reports_unreachable(monkeypatch):
    from forensics import http
    monkeypatch.setattr(http, "get", lambda *a, **k: (_ for _ in ()).throw(
        http.RequestError("blocked")))
    out = identify._solscan_tag("SomeAddr")
    assert out["status"] == "unreachable"
