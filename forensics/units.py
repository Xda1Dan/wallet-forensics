"""Numeric parsing and unit scaling.

Amounts are scaled in Decimal so 18-decimal values do not pick up float error
before a caller sums them. to_units drops to float only for display.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation


def to_int(value) -> int:
    """Coerce an int, hex string, decimal string or None to an int.

    Raises ValueError for non-scalars, so an ``{"_rpc_error": ...}`` marker from
    Rpc.call is treated as an error instead of silently becoming 0.
    """
    if value is None:
        return 0
    if isinstance(value, bool):  # bool is an int subclass
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (bytes, bytearray)):
        value = value.decode()
    if not isinstance(value, (str, float, Decimal)):
        raise ValueError(
            f"cannot parse an integer from {type(value).__name__}: {value!r}")
    text = str(value).strip()
    if text in ("", "0x", "0X"):
        return 0
    try:
        return int(text, 16) if text.lower().startswith("0x") else int(text)
    except ValueError:
        try:
            return int(Decimal(text))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"cannot parse an integer from {value!r}") from exc


def to_decimal(raw, decimals) -> Decimal | None:
    """Scale a base-unit amount to human units, exactly.

    ``decimals`` may be an int, a decimal string or a hex string (Alchemy returns
    the latter). Returns None when it cannot be interpreted. Prefer this over
    to_units when amounts will be summed or reconciled.
    """
    if raw is None or decimals is None:
        return None
    try:
        return Decimal(to_int(raw)) / (Decimal(10) ** to_int(decimals))
    except (ValueError, TypeError, InvalidOperation):
        return None


def to_units(raw, decimals) -> float | None:
    """Scale an integer base-unit amount down to human units as a float."""
    value = to_decimal(raw, decimals)
    return None if value is None else float(value)
