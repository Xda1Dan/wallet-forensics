"""Address helpers: normalising, log topics, EIP-7702, lookalike detection."""
from __future__ import annotations

ZERO = "0x" + "0" * 40


def normalize(address: str) -> str:
    return (address or "").lower()


def topic(address: str) -> str:
    """Left-pad an address into a 32-byte log topic."""
    return "0x" + normalize(address)[2:].zfill(64)


def from_topic(value: str) -> str:
    """Extract the address from a 32-byte log topic."""
    return "0x" + value[-40:].lower()


def is_7702(code: str | None) -> bool:
    """True when ``eth_getCode`` shows an EIP-7702 delegation."""
    return bool(code and code.startswith("0xef0100") and len(code) >= 46)


def delegate(code: str | None) -> str | None:
    """The delegate address behind an EIP-7702 delegation, if any."""
    return "0x" + code[8:48].lower() if is_7702(code) else None


def similarity(a: str, b: str) -> tuple[int, int]:
    """Shared leading and trailing hex nibbles between two addresses.

    The ``0x`` prefix is stripped first, so the counts compare directly against
    the thresholds in forensics.spam: a suffix of 4 means the last four hex
    characters match (e.g. ``…42ee``).
    """
    a, b = _hex_body(a), _hex_body(b)
    prefix = 0
    for x, y in zip(a, b):
        if x != y:
            break
        prefix += 1
    suffix = 0
    for x, y in zip(reversed(a), reversed(b)):
        if x != y:
            break
        suffix += 1
    return prefix, suffix


def _hex_body(address: str) -> str:
    """Lower-cased address without a leading ``0x``."""
    value = normalize(address)
    return value[2:] if value.startswith("0x") else value
