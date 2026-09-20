"""Tests for forensics.solana transfers: parsed-row extraction and pagination.

Offline: RPC responses are stubbed. Regression coverage for bugs found by live
testing — token balances keyed by accountIndex (not address), `transfer`
instructions that carry a `tokenAmount` object instead of a flat `amount`, and
Helius pagination via `before`.
"""
import pytest

from forensics.solana import (
    Helius, Solana, _transfers_from_parsed, _transfers_from_parsed_helius,
    normalize_transfer,
)

VICTIM = "5gNXSccDf8M6PbqsFWagLAoJS6FMdZpGVkHpwsiF4Pfo"
POOL = "CAsLLgWHkavHhD3EpNRHMPCWJwSgSJLwX7JxYJcb2bsz"
USDC = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDC_DECIMALS = 6


def _spl_transfer(source, destination, amount, mint=None, decimals=None,
                  token_amount=None):
    info = {"authority": source, "source": source, "destination": destination}
    if mint:
        info["mint"] = mint
    if amount is not None:
        info["amount"] = amount
    if decimals is not None:
        info["decimals"] = decimals
    if token_amount is not None:
        info["tokenAmount"] = token_amount
    return {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "parsed": {"type": "transfer", "info": info}}


def _tx(instructions, account_keys, token_balances):
    return {
        "slot": 1, "blockTime": 1789402442,
        "transaction": {"signatures": ["Sig1"],
                        "message": {"accountKeys": [{"pubkey": k} for k in account_keys],
                                    "instructions": instructions}},
        "meta": {"postTokenBalances": token_balances, "preTokenBalances": [],
                 "innerInstructions": []},
    }


def test_normalize_transfer_carries_raw_when_unscaled():
    row = normalize_transfer("sig", 1, 1789402442, "spl", USDC, USDC,
                             None, "a", "b", raw="123")
    assert row["amount"] is None
    assert row["amount_raw"] == "123"
    assert "amount_note" in row


def test_normalize_transfer_iso_time():
    row = normalize_transfer("sig", 1, 1789402442, "native", "SOL", None,
                             1.0, "a", "b")
    assert row["time"] == "2026-09-14T16:14:02.000Z"


def test_token_balance_index_resolves_owner_by_account_key():
    """accountIndex in tokenBalances maps to accountKeys, not to the address."""
    keys = ["Auth", POOL, "Other"]
    balances = [{"accountIndex": 1, "mint": USDC, "owner": VICTIM,
                 "uiTokenAmount": {"decimals": USDC_DECIMALS}}]
    tx = _tx([_spl_transfer(POOL, "Other", "1000", mint=USDC)], keys, balances)
    rows = _transfers_from_parsed(tx, "sig")
    assert rows[0]["from"] == VICTIM          # resolved via accountKeys[1]
    assert rows[0]["amount"] == 0.001         # scaled with decimals from balance


def test_transfer_with_token_amount_object():
    """Some `transfer` instructions nest amount+decimals in tokenAmount."""
    keys = ["Auth", POOL]
    balances = [{"accountIndex": 1, "mint": USDC, "owner": VICTIM,
                 "uiTokenAmount": {"decimals": USDC_DECIMALS}}]
    tx = _tx([_spl_transfer(POOL, "Other", None, mint=USDC,
                            token_amount={"amount": "603901249", "decimals": 6})],
             keys, balances)
    rows = _transfers_from_parsed(tx, "sig")
    assert rows[0]["amount"] == 603.901249
    assert rows[0]["from"] == VICTIM


def test_decimals_lookup_used_when_balances_lack_the_account():
    """Transient pool accounts are absent from token balances; fall back.

    The account resolves its owner from the balance list, but that entry
    carries no decimals, so the mint lookup supplies the scale.
    """
    keys = ["Auth", POOL]
    balances = [{"accountIndex": 1, "mint": None, "owner": VICTIM,
                 "uiTokenAmount": {}}]
    tx = _tx([_spl_transfer(POOL, "Other", "1491048352", mint=USDC)],
             keys, balances)
    rows = _transfers_from_parsed(tx, "sig", decimals_lookup=lambda m: 6)
    assert rows[0]["amount"] == 1491.048352


def test_unresolved_decimals_are_flagged_not_mislabelled():
    keys = ["Auth", POOL]
    balances = [{"accountIndex": 1, "mint": None, "owner": VICTIM,
                 "uiTokenAmount": {}}]
    tx = _tx([_spl_transfer(POOL, "Other", "1491048352")], keys, balances)
    rows = _transfers_from_parsed(tx, "sig")
    assert rows[0]["amount"] is None
    assert rows[0]["amount_raw"] == "1491048352"


def test_rows_without_a_resolvable_owner_are_dropped():
    """A transfer no side of which maps to an owner cannot be attributed."""
    tx = _tx([_spl_transfer(POOL, "Other", "1000")], ["Auth"], [])
    assert _transfers_from_parsed(tx, "sig") == []


def test_helius_rows_flatten_native_and_spl():
    tx = {
        "signature": "Sig", "slot": 5, "timestamp": 1789402442,
        "nativeTransfers": [{"fromUserAccount": VICTIM, "toUserAccount": "X",
                             "amount": 500_000_000}],
        "tokenTransfers": [{"fromUserAccount": VICTIM, "toUserAccount": "Y",
                            "tokenAmount": 1503.526083, "mint": USDC}],
    }
    rows = _transfers_from_parsed_helius(tx, VICTIM)
    assert {r["category"] for r in rows} == {"native", "spl"}
    native = next(r for r in rows if r["category"] == "native")
    assert native["amount"] == 0.5


def test_helius_rows_exclude_transfers_not_touching_owner():
    tx = {"signature": "S", "slot": 1, "timestamp": 1,
          "nativeTransfers": [{"fromUserAccount": "A", "toUserAccount": "B",
                               "amount": 1}]}
    assert _transfers_from_parsed_helius(tx, VICTIM) == []


def test_helius_transfers_paginate_until_short_page(monkeypatch):
    """`before` paging: a full page triggers another call, a short one stops."""
    pages = [
        [{"signature": f"s{i}", "slot": i, "timestamp": 1,
          "nativeTransfers": [{"fromUserAccount": VICTIM, "toUserAccount": "X",
                               "amount": 1}]} for i in range(Helius.PAGE)],
        [{"signature": "last", "slot": 1, "timestamp": 1,
          "nativeTransfers": [{"fromUserAccount": VICTIM, "toUserAccount": "X",
                               "amount": 1}]}],
    ]
    calls = []

    def fake_page(self, address, limit, before):
        calls.append(before)
        return pages.pop(0)

    monkeypatch.setattr(Helius, "_parsed_page", fake_page)
    rows = Helius(key="k").transfers(VICTIM, cap=1000)
    assert len(calls) == 2
    assert calls[1] == f"s{Helius.PAGE - 1}"   # paged from the last signature
    assert len(rows) == Helius.PAGE + 1


def test_solana_transfers_derives_rows(monkeypatch):
    """Keyless path: signatures -> getTransaction -> rows."""
    def fake_call(self, method, params):
        if method == "getSignaturesForAddress":
            return [{"signature": "Sig1"}]
        if method == "getTransaction":
            return _tx([{"programId": "11111111111111111111111111111111",
                         "parsed": {"type": "transfer",
                                    "info": {"source": VICTIM, "destination": "X",
                                             "lamports": 500_000_000}}}],
                       ["Auth"], [])
        return None

    monkeypatch.setattr(Solana, "call", fake_call)
    rows = Solana(["https://example.invalid"]).transfers(VICTIM, direction="from")
    assert len(rows) == 1
    assert rows[0]["amount"] == 0.5
    assert rows[0]["to"] == "X"
