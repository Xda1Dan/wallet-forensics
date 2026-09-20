"""Spam and address-poisoning detection, across EVM and Solana.

Drainers flood a victim's history with fake lookalike tokens and vanity
addresses mimicking the real collector; counting those inflates the haul. This
module annotates each transfer with flags and never decides.

It works on the *canonical* transfer rows produced by ``evm.normalize_transfer``
and ``solana.normalize_transfer``, so one implementation covers both chains.

DEX-pair lookups are memoised in DexScreener, so screening a history costs one
request per token, not one per transfer.
"""
from __future__ import annotations

import string

from .providers import DexScreener

_ASCII_OK = set(string.ascii_letters + string.digits + " .-_$/")

# Categories that denote a token movement, versus a native-coin movement.
NATIVE_CATEGORIES = frozenset({"external", "native"})
TOKEN_CATEGORIES = frozenset({"erc20", "erc721", "erc1155", "spl"})

# Shared-run thresholds, per address alphabet. A hex nibble carries 4 bits; a
# base58 character carries ~5.86, so a shorter base58 run is equally unlikely
# and the thresholds are not the same. Tuned to flag vanity poisoning without
# firing on the short runs that random addresses share by chance.
THRESHOLDS = {
    "hex": {"prefix": 8, "suffix": 6, "vanity": 4},
    "base58": {"prefix": 6, "suffix": 5, "vanity": 4},
}


def symbol_flags(symbol: str | None) -> list[str]:
    """Flag token symbols that are not plain ASCII (homoglyph spoofing)."""
    if not symbol:
        return ["no_symbol"]
    unusual = sorted({ch for ch in symbol if ch not in _ASCII_OK})
    if unusual:
        return ["non_ascii_symbol", "homoglyphs:" + "".join(unusual)]
    return []


def _alphabet(address: str) -> str:
    return "hex" if (address or "").lower().startswith("0x") else "base58"


def _shared_runs(a: str, b: str) -> tuple[int, int]:
    """Shared leading/trailing characters.

    Hex (EVM) is case-insensitive and drops the ``0x`` marker, so the counts
    compare directly against the thresholds. Base58 (Solana) is case-sensitive:
    lower-casing it would merge distinct addresses.
    """
    if _alphabet(a) == "hex" or _alphabet(b) == "hex":
        a, b = a.lower(), b.lower()
        a = a[2:] if a.startswith("0x") else a
        b = b[2:] if b.startswith("0x") else b
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


def _same(a: str, b: str) -> bool:
    return (a or "").lower() == (b or "").lower() if _alphabet(a) == "hex" \
        else a == b


def lookalike_flags(candidate: str, references: dict[str, str]) -> list[str]:
    """Flag an address that mimics any known one (vanity poisoning)."""
    if not candidate:
        return []
    thresholds = THRESHOLDS[_alphabet(candidate)]
    flags = []
    for name, reference in references.items():
        if not reference or _same(candidate, reference):
            continue
        prefix, suffix = _shared_runs(candidate, reference)
        if prefix >= thresholds["prefix"] or suffix >= thresholds["suffix"]:
            flags.append(f"lookalike_of:{name}(pre={prefix},suf={suffix})")
        elif suffix >= thresholds["vanity"]:
            flags.append(f"vanity_suffix:{name}(suf={suffix})")
    return flags


def is_token(row: dict) -> bool:
    """True when a canonical row is a token movement, not native coin."""
    return row.get("category") in TOKEN_CATEGORIES or bool(row.get("contract"))


def screen(rows: list[dict], references: dict[str, str], chain: str,
           check_dex: bool = True) -> tuple[list[dict], dict]:
    """Annotate canonical transfer rows with spam flags.

    Returns ``(rows, summary)``. ``references`` maps a label to a known real
    address (e.g. ``{"collector": "0x..."}`` or a base58 Solana address).
    Rows must already be canonical (see the module docstring); the caller
    normalizes so this stays chain-agnostic.
    """
    native_amounts = {
        round(float(r["amount"]), 8)
        for r in rows
        if r.get("category") in NATIVE_CATEGORIES and r.get("amount")
    }

    annotated = []
    for row in rows:
        flags = _flags_for(row, native_amounts, references, chain, check_dex)
        annotated.append({**row, "flags": flags,
                          "suspected_spam": bool(flags)})

    summary = {"total": len(annotated),
               "suspected_spam": sum(r["suspected_spam"] for r in annotated),
               "by_flag": _tally(annotated)}
    summary["clean"] = summary["total"] - summary["suspected_spam"]
    return annotated, summary


def _flags_for(row, native_amounts, references, chain, check_dex) -> list[str]:
    flags: list[str] = []
    if is_token(row):
        # `symbol` is set when metadata was resolved (Solana); `asset` already
        # carries the symbol on EVM. Fall back to the mint/contract address,
        # which will not trip the homoglyph check but is never mislabelled.
        flags += symbol_flags(row.get("symbol") or row.get("asset"))
        contract = row.get("contract")
        if contract and check_dex and DexScreener.has_pair(chain, contract) is False:
            flags.append("no_dex_pair")
        amount = row.get("amount")
        if amount:
            try:
                if round(float(amount), 8) in native_amounts:
                    flags.append("mirror_amount")
            except (TypeError, ValueError):
                pass
    flags += lookalike_flags(row.get("to") or "", references)
    flags += lookalike_flags(row.get("from") or "", references)
    return flags


def _tally(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for flag in row["flags"]:
            key = flag.split(":")[0].split("(")[0]
            counts[key] = counts.get(key, 0) + 1
    return counts
