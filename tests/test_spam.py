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
    rows = [
        {"hash": "0x1", "category": "external", "amount": 0.9, "asset": "ETH",
         "from": "0xaaa", "to": "0xbbb", "block": "0x1", "contract": None},
        {"hash": "0x2", "category": "erc20", "amount": 0.9, "asset": "E឴឴ꓔH",
         "from": "0xaaa", "to": "0x758207f2ba7b42ee", "block": "0x2",
         "contract": "0xdead"},
    ]
    screened, summary = spam.screen(
        rows, {"collector": "0x758874a6ef5a40c495b0f8bf2c1c076fcb5f42ee"},
        "eth", check_dex=True)
    assert summary["total"] == 2
    assert summary["suspected_spam"] == 1
    assert summary["clean"] == 1
    assert summary["by_flag"]["non_ascii_symbol"] == 1
    assert summary["by_flag"]["mirror_amount"] == 1
    assert screened[0]["suspected_spam"] is False
    assert screened[1]["suspected_spam"] is True


# --- Solana: canonical rows, base58 references ----------------------------
SOL_REF = "FncazAs6omJJjtLVzquzT9KoyXn6tFixr9kGjr42ktLj"


def test_screen_solana_spam_mint(monkeypatch):
    """An SPL row with no DEX pair and a spoofed symbol is flagged."""
    monkeypatch.setattr(spam.DexScreener, "has_pair", staticmethod(lambda *a, **k: False))
    rows = [{"hash": "s1", "category": "spl", "contract": "SPAMMINT",
             "symbol": "USDC", "amount": 1.005427,
             "from": "attacker", "to": "victim"}]
    screened, summary = spam.screen(rows, {}, "sol", check_dex=True)
    assert screened[0]["suspected_spam"] is True
    assert "no_dex_pair" in screened[0]["flags"]


def test_screen_solana_real_token_is_clean(monkeypatch):
    monkeypatch.setattr(spam.DexScreener, "has_pair", staticmethod(lambda *a, **k: True))
    rows = [{"hash": "s1", "category": "spl", "contract": "USDC",
             "symbol": "USDC", "amount": 100.0, "from": "a", "to": "b"}]
    screened, _ = spam.screen(rows, {}, "sol", check_dex=True)
    assert screened[0]["suspected_spam"] is False


def test_solana_lookalike_is_case_sensitive():
    """Base58 differs by case: a one-character case change is a lookalike,
    not the same address (which would be skipped)."""
    from forensics.spam import _same
    assert _same(SOL_REF, SOL_REF.upper()) is False          # not the same
    one_case = SOL_REF[:-1] + SOL_REF[-1].upper()           # shares 43 chars
    assert spam.lookalike_flags(one_case, {"gas": SOL_REF}) != []


def test_solana_exact_match_is_skipped():
    assert spam.lookalike_flags(SOL_REF, {"gas": SOL_REF}) == []


def test_solana_vanity_suffix_flagged():
    fake = "FncazAs6omJJjtLVzquzT9KoyXn6tFixr9kGjr42ktLJ"  # shares ...2ktLJ? no
    flags = spam.lookalike_flags(SOL_REF[:-3] + "xyz", {"gas": SOL_REF})
    assert any(f.startswith(("lookalike_of:", "vanity_suffix:")) for f in flags)


def test_solana_native_row_is_not_a_token():
    assert spam.is_token({"category": "native", "contract": None}) is False
    assert spam.is_token({"category": "spl", "contract": "MINT"}) is True
    assert spam.is_token({"category": "external", "contract": None}) is False
