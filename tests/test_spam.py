"""Tests for forensics.spam."""
from forensics import spam


def test_symbol_flags_accepts_plain_ascii():
    assert spam.symbol_flags("ETH") == []
    assert spam.symbol_flags("USDC") == []


def test_symbol_flags_missing_symbol():
    assert spam.symbol_flags(None) == ["no_symbol"]
    assert spam.symbol_flags("") == ["no_symbol"]


def test_symbol_flags_flags_homoglyphs():
    flags = spam.symbol_flags("E឴឴ꓔH")
    assert "non_ascii_symbol" in flags
    assert any(f.startswith("homoglyphs:") for f in flags)


def test_lookalike_flags_detects_vanity_suffix():
    real = "0x758874a6ef5a40c495b0f8bf2c1c076fcb5f42ee"
    fake = "0x758207f2ba7b42ee"
    flags = spam.lookalike_flags(fake, {"collector": real})
    assert any(f.startswith("vanity_suffix:collector") for f in flags)


def test_lookalike_flags_ignores_exact_match():
    real = "0x758874a6ef5a40c495b0f8bf2c1c076fcb5f42ee"
    assert spam.lookalike_flags(real, {"collector": real}) == []


def test_lookalike_flags_ignores_unrelated_address():
    flags = spam.lookalike_flags("0x1111111111111111111111111111111111111111",
                                 {"collector": "0x758874a6ef5a40c495b0f8bf2c1c076fcb5f42ee"})
    assert flags == []


def test_screen_annotates_and_summarises(monkeypatch):
    monkeypatch.setattr(spam.DexScreener, "has_pair", staticmethod(lambda *a, **k: True))
    transfers = [
        {"hash": "0x1", "category": "external", "value": 0.9, "asset": "ETH",
         "from": "0xaaa", "to": "0xbbb", "blockNum": "0x1"},
        {"hash": "0x2", "category": "erc20", "value": 0.9, "asset": "E឴឴ꓔH",
         "from": "0xaaa", "to": "0x758207f2ba7b42ee", "blockNum": "0x2",
         "rawContract": {"address": "0xdead"}},
    ]
    rows, summary = spam.screen(transfers, {"collector": "0x758874a6ef5a40c495b0f8bf2c1c076fcb5f42ee"},
                                "eth", check_dex=True)
    assert summary["total"] == 2
    assert summary["suspected_spam"] == 1
    assert summary["clean"] == 1
    assert summary["by_flag"]["non_ascii_symbol"] == 1
    assert summary["by_flag"]["mirror_amount"] == 1
    assert rows[0]["suspected_spam"] is False
    assert rows[1]["suspected_spam"] is True
