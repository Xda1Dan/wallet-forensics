"""Tests for forensics.units."""
import pytest

from forensics.units import to_decimal, to_int, to_units


@pytest.mark.parametrize("value,expected", [
    (None, 0),
    (0, 0),
    ("", 0),
    ("0x", 0),
    ("0X", 0),
    (123, 123),
    ("123", 123),
    ("0xff", 255),
    ("0xFF", 255),
    (True, 1),
    (False, 0),
    (1.0, 1),
    ("1e3", 1000),
])
def test_to_int_accepts_scalars(value, expected):
    assert to_int(value) == expected


def test_to_int_rejects_error_objects():
    """An RPC error marker must not silently become 0."""
    with pytest.raises(ValueError):
        to_int({"_rpc_error": {"code": -32000, "message": "boom"}})
    with pytest.raises(ValueError):
        to_int(["0x1"])
    with pytest.raises(ValueError):
        to_int("not-a-number")


def test_to_units_scales_by_decimals():
    assert to_units("0xde0b6b3a7640000", 18) == 1.0
    assert to_units("1000000", "0x6") == 1.0  # hex decimals, as Alchemy returns
    assert to_units(1_000_000, 6) == 1.0


def test_to_units_returns_none_on_missing_inputs():
    assert to_units(None, 18) is None
    assert to_units("1000", None) is None


def test_to_units_returns_none_on_bad_input():
    assert to_units({"_rpc_error": {}}, 18) is None
    assert to_units("zzz", 18) is None


def test_to_decimal_is_exact_for_18_decimals():
    """18-decimal scaling must not pick up binary-float error."""
    value = to_decimal("123456789012345678901", 18)
    assert str(value) == "123.456789012345678901"
    assert to_decimal("1", 18) + to_decimal("2", 18) == to_decimal("3", 18)
