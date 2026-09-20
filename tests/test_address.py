"""Tests for forensics.address."""
from forensics.address import (
    ZERO, delegate, from_topic, is_7702, normalize, similarity, topic,
)


def test_normalize_lowercases_and_tolerates_none():
    assert normalize("0xABCDEF") == "0xabcdef"
    assert normalize(None) == ""
    assert normalize("") == ""


def test_topic_roundtrip():
    address = "0x758874a6ef5a40c495b0f8bf2c1c076fcb5f42ee"
    padded = topic(address)
    assert padded.startswith("0x") and len(padded) == 66
    assert from_topic(padded) == address


def test_topic_pads_short_values():
    assert topic("0x1") == "0x" + "0" * 63 + "1"


def test_is_7702_and_delegate():
    code = "0xef0100" + "2c6f01799fa9db1e7f2797e5ba892b72b865571d"
    assert is_7702(code) is True
    assert delegate(code) == "0x2c6f01799fa9db1e7f2797e5ba892b72b865571d"
    assert is_7702("0x") is False
    assert is_7702(None) is False
    assert delegate("0x60806040") is None


def test_similarity_counts_hex_nibbles_not_the_0x_prefix():
    """The `0x` marker must not inflate the shared-run counts."""
    # Identical addresses: 40 shared hex nibbles, both ends.
    a = "0x758874a6ef5a40c495b0f8bf2c1c076fcb5f42ee"
    assert similarity(a, a) == (40, 40)
    # Same suffix `42ee`, unrelated prefix: shares only 7,5,8 before diverging.
    prefix, suffix = similarity(a, "0x758207f2ba7b42ee")
    assert suffix == 4
    assert prefix == 3


def test_similarity_ignores_case_and_prefix_absence():
    assert similarity("0xABCD", "abcd") == (4, 4)


def test_zero_constant():
    assert ZERO == "0x" + "0" * 40
