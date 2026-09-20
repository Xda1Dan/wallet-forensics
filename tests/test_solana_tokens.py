"""Tests for Solana SPL token accounts and the `sol tokens` command.

Offline: RPC and Jupiter are stubbed.
"""
import pytest

from forensics import http
from forensics.providers import Jupiter
from forensics.solana import Solana


def _token_account_response(accounts):
    return {"context": {}, "value": accounts}


def _account(pubkey, mint, amount, decimals, delegate=None, state="initialized"):
    return {
        "pubkey": pubkey,
        "account": {"data": {"parsed": {"info": {
            "mint": mint,
            "delegate": delegate,
            "state": state,
            "tokenAmount": {"uiAmount": amount, "amount": str(int(amount * 10 ** decimals)),
                            "decimals": decimals},
        }}}},
    }


def test_token_accounts_covers_both_token_programs(monkeypatch):
    """A wallet with a Token-2022 account must not lose it."""
    seen = []

    def fake_call(self, method, params):
        seen.append(params[1]["programId"])
        if params[1]["programId"].startswith("Tokenz"):
            return _token_account_response([_account("acct2", "MINT2022", 5.0, 6)])
        return _token_account_response([_account("acct1", "MINTSPL", 1.005427, 6)])

    monkeypatch.setattr(Solana, "call", fake_call)
    accounts = Solana(["https://example.invalid"]).token_accounts("owner")
    assert {a["mint"] for a in accounts} == {"MINTSPL", "MINT2022"}
    assert len(seen) == 2


def test_token_accounts_survives_one_program_failing(monkeypatch):
    def fake_call(self, method, params):
        if params[1]["programId"].startswith("Tokenz"):
            return {"_rpc_error": {"code": -32602}}
        return _token_account_response([_account("acct1", "MINTSPL", 1.0, 6)])

    monkeypatch.setattr(Solana, "call", fake_call)
    accounts = Solana(["https://example.invalid"]).token_accounts("owner")
    assert [a["mint"] for a in accounts] == ["MINTSPL"]


def test_token_accounts_surfaces_delegate(monkeypatch):
    """A non-null delegate is an approval-like grant; it must be visible."""
    monkeypatch.setattr(Solana, "call", lambda self, m, p: _token_account_response(
        [_account("acct", "MINT", 1.0, 6, delegate="SomeDelegate")]))
    accounts = Solana(["https://example.invalid"]).token_accounts("owner")
    assert accounts[0]["delegate"] == "SomeDelegate"


def test_token_accounts_empty_on_error(monkeypatch):
    monkeypatch.setattr(Solana, "call",
                        lambda self, m, p: {"_rpc_error": {"code": -32602}})
    assert Solana(["https://example.invalid"]).token_accounts("owner") == []


def test_token_accounts_none_delegate(monkeypatch):
    monkeypatch.setattr(Solana, "call", lambda self, m, p: _token_account_response(
        [_account("acct", "MINT", 1.0, 6)]))
    assert Solana(["https://example.invalid"]).token_accounts("owner")[0]["delegate"] is None


# --- CLI: sol tokens -------------------------------------------------------
def test_sol_tokens_joins_metadata(monkeypatch):
    from forensics import cli

    class Args:
        addr = "Owner"
        cap = 100

    def fake_call(self, method, params):
        if params[1]["programId"].startswith("Tokenz"):
            return _token_account_response([])
        return _token_account_response([_account("acct", "MINTSPL", 1.005427, 6)])

    monkeypatch.setattr(Solana, "call", fake_call)
    monkeypatch.setattr(Jupiter, "tokens", staticmethod(
        lambda mints: {"MINTSPL": {"symbol": "USDC", "name": "USDC", "decimals": 6}}))

    out = cli._sol_tokens(Args(), Solana(["https://example.invalid"]))
    assert out["count"] == 1
    assert out["tokens"][0]["symbol"] == "USDC"
    assert out["tokens"][0]["amount"] == 1.005427


def test_sol_tokens_without_metadata_still_returns_mint(monkeypatch):
    from forensics import cli

    class Args:
        addr = "Owner"
        cap = 100

    def fake_call(self, method, params):
        if params[1]["programId"].startswith("Tokenz"):
            return _token_account_response([])
        return _token_account_response([_account("acct", "MYSTERY", 1.0, 9)])

    monkeypatch.setattr(Solana, "call", fake_call)
    monkeypatch.setattr(Jupiter, "tokens", staticmethod(lambda mints: {}))
    out = cli._sol_tokens(Args(), Solana(["https://example.invalid"]))
    assert out["tokens"][0]["mint"] == "MYSTERY"
    assert out["tokens"][0]["symbol"] is None
