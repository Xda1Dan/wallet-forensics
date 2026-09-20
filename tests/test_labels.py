"""Tests for forensics.labels: address lookup across EVM and Solana.

Regression: ``normalize`` lower-cases, which is right for hex EVM addresses but
corrupts base58 Solana addresses (case-sensitive). Solana labels must resolve.
"""
from forensics import labels


def test_evm_lookup_is_case_insensitive():
    a = "0xf70da97812cb96acdf810712aa562db8dfa3dbef"
    assert labels.lookup(a) is not None
    assert labels.lookup(a.upper().replace("0X", "0x")) is not None


def test_solana_lookup_preserves_case():
    """A base58 Solana label resolves, and the lower-cased form does not."""
    real = "7uTT8Xi5RWXzy7h9XL244GRgEycDYDhLjr3ZyNdXi8pZ"
    assert labels.lookup(real) is not None
    assert labels.lookup(real.lower()) is None


def test_unknown_address_is_none():
    assert labels.lookup("So11111111111111111111111111111111111111112") is None
    assert labels.annotate("") is None
