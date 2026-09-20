"""Spam and address-poisoning detection.

Drainers flood a victim's history with fake lookalike tokens and vanity
addresses mimicking the real collector; counting those inflates the haul. This
module annotates each transfer with flags and never decides.

DEX-pair lookups are memoised in DexScreener, so screening a history costs one
request per token, not one per transfer.
"""
from __future__ import annotations

import string

from . import address as addr
from .evm import normalize_transfer
from .providers import DexScreener

_ASCII_OK = set(string.ascii_letters + string.digits + " .-_$/")

# A shared run this long is past coincidence for random hex. Counts are hex
# nibbles (the ``0x`` marker is stripped by ``addr.similarity``).
PREFIX_THRESHOLD = 8
SUFFIX_THRESHOLD = 6
VANITY_SUFFIX_THRESHOLD = 4


def symbol_flags(symbol: str | None) -> list[str]:
    """Flag token symbols that are not plain ASCII (homoglyph spoofing)."""
    if not symbol:
        return ["no_symbol"]
    unusual = sorted({ch for ch in symbol if ch not in _ASCII_OK})
    if unusual:
        return ["non_ascii_symbol", "homoglyphs:" + "".join(unusual)]
    return []


def lookalike_flags(candidate: str, references: dict[str, str]) -> list[str]:
    """Flag an address that mimics any known one (vanity poisoning)."""
    flags = []
    for name, reference in references.items():
        if not reference or addr.normalize(candidate) == addr.normalize(reference):
            continue
        prefix, suffix = addr.similarity(candidate, reference)
        if prefix >= PREFIX_THRESHOLD or suffix >= SUFFIX_THRESHOLD:
            flags.append(f"lookalike_of:{name}(pre={prefix},suf={suffix})")
        elif suffix >= VANITY_SUFFIX_THRESHOLD:
            flags.append(f"vanity_suffix:{name}(suf={suffix})")
    return flags


def screen(transfers: list[dict], references: dict[str, str], chain: str,
           check_dex: bool = True, decimals_map: dict | None = None) -> tuple[list[dict], dict]:
    """Annotate transfers with spam flags.

    Returns ``(rows, summary)``. ``references`` maps a label to a known real
    address (e.g. ``{"collector": "0x..."}``). ``decimals_map`` is forwarded to
    evm.normalize_transfer so the rows carry correctly scaled amounts.
    """
    native_amounts = {
        round(float(t["value"]), 8)
        for t in transfers
        if t.get("category") == "external" and t.get("value")
    }

    rows = []
    for transfer in transfers:
        flags = _flags_for(transfer, native_amounts, references, chain, check_dex)
        # Same canonical row as `transfers`/`flow`; only the spam flags differ.
        rows.append({**normalize_transfer(transfer, decimals_map),
                     "flags": flags,
                     "suspected_spam": bool(flags)})

    summary = {"total": len(rows),
               "suspected_spam": sum(r["suspected_spam"] for r in rows),
               "by_flag": _tally(rows)}
    summary["clean"] = summary["total"] - summary["suspected_spam"]
    return rows, summary


def _flags_for(transfer, native_amounts, references, chain, check_dex) -> list[str]:
    flags: list[str] = []
    if transfer.get("category") in ("erc20", "erc721", "erc1155"):
        flags += symbol_flags(transfer.get("asset"))
        contract = (transfer.get("rawContract") or {}).get("address")
        if contract and check_dex and DexScreener.has_pair(chain, contract) is False:
            flags.append("no_dex_pair")
        if transfer.get("value"):
            try:
                if round(float(transfer["value"]), 8) in native_amounts:
                    flags.append("mirror_amount")
            except (TypeError, ValueError):
                pass
    flags += lookalike_flags(transfer.get("to") or "", references)
    flags += lookalike_flags(transfer.get("from") or "", references)
    return flags


def _tally(rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        for flag in row["flags"]:
            key = flag.split(":")[0].split("(")[0]
            counts[key] = counts.get(key, 0) + 1
    return counts
