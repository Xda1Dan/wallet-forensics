"""Identify an address: what it is, who labels it, and where to look.

The gap this closes: a raw address in a transfer row gives no hint that it is a
bridge vault, a program, or a known exchange. That has to be noticed by hand,
and it is easy to miss. ``identify`` answers "what is this?" from what is
actually knowable:

* the curated knowledge base (``labels.py``)
* the account's *type* on chain -- program vs wallet, mint vs token account,
  contract vs EOA -- which is authoritative and needs no third party
* explorer links, so a human can go deeper

External tag services (Solscan, Orb) are consulted best-effort. When they are
unreachable the result says so, rather than silently implying the address has
no label.
"""
from __future__ import annotations

from . import chains as chain_registry
from . import labels

# Built-in Solana program names. These are protocol constants, not a
# third-party KB, so they are safe to assert.
SOLANA_PROGRAMS = {
    "11111111111111111111111111111111": "System Program",
    "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA": "SPL Token Program",
    "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb": "Token-2022 Program",
    "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL": "Associated Token Program",
    "ComputeBudget111111111111111111111111111111": "Compute Budget Program",
    "BPFLoaderUpgradeab1e11111111111111111111111": "BPF Upgradeable Loader",
    "BPFLoader2111111111111111111111111111111111": "BPF Loader",
    "Vote111111111111111111111111111111111111111": "Vote Program",
    "Stake11111111111111111111111111111111111111": "Stake Program",
    "AddressLookupTab1e1111111111111111111111111": "Address Lookup Table Program",
    "L2TExMFKdjpN9kozasaurPirfHy9P8sbXoAN1qA3S95": "Lighthouse Assertion Program",
    "Send9wszHjEiS3hwKcPeSLsPRu5Gb62iCrJEcG4Mq3b": "Unknown helper program (seen in drain txs)",
}

_B58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def detect_chain(address: str) -> str:
    """Best-effort chain for an address: 'sol' for base58, else the EVM default."""
    if address and not address.lower().startswith("0x") and set(address) <= _B58:
        return "sol"
    return "eth"


def is_solana(address: str) -> bool:
    return bool(address) and not address.lower().startswith("0x") \
        and set(address) <= _B58 and 32 <= len(address) <= 44


def identify(address: str, chain: str | None = None) -> dict:
    """Everything knowable about an address, from the KB and the chain."""
    if not address:
        return {"_error": "an address is required", "type": "MissingAddress"}
    resolved = chain_registry.resolve(chain) if chain else detect_chain(address)
    result = {
        "address": address,
        "chain": resolved,
        "known_label": labels.lookup(address),
        "explorer": _explorer_url(resolved, address),
    }
    if resolved == "sol":
        result.update(_identify_solana(address))
    else:
        result.update(_identify_evm(resolved, address))
    # A single human-facing name: the KB label wins, else a builtin program
    # name, else nothing (the caller decides what to call an unknown address).
    label = result.get("known_label") or {}
    result["name"] = (label.get("name")
                      or result.get("program_name")
                      or SOLANA_PROGRAMS.get(address))
    result["external_labels"] = _external_labels(resolved, address)
    return result


def _explorer_url(chain: str, address: str) -> str | None:
    try:
        base = chain_registry.info(chain).get("explorer")
    except KeyError:
        return None
    if not base:
        return None
    if chain == "sol":
        return f"{base}/account/{address}"
    return f"{base}/address/{address}"


def _identify_solana(address: str) -> dict:
    from .solana import Solana, is_error, TOKEN_PROGRAM_ID

    out: dict = {}
    if address in SOLANA_PROGRAMS:
        out["type"] = "program"
        out["program_name"] = SOLANA_PROGRAMS[address]
    client = Solana()
    info = client.call("getAccountInfo", [address, {"encoding": "jsonParsed"}])
    if is_error(info):
        out["_rpc_error"] = info["_rpc_error"]
        return out
    value = (info or {}).get("value") if isinstance(info, dict) else None
    if not value:
        out.setdefault("type", "uninitialized")
        out["note"] = "no account exists at this address on Solana"
        return out
    out["executable"] = value.get("executable")
    out["owner_program"] = value.get("owner")
    out["owner_program_name"] = SOLANA_PROGRAMS.get(value.get("owner"))
    out["space"] = value.get("space")
    out["lamports"] = value.get("lamports")

    # `data` is {"parsed": ...} for a known account, but a [base64, "base64"]
    # pair for a program or an unparsed account.
    raw_data = value.get("data")
    parsed = raw_data.get("parsed") if isinstance(raw_data, dict) else None
    if isinstance(parsed, dict) and parsed.get("type"):
        out["parsed_type"] = parsed["type"]
        out["parsed_info"] = parsed.get("info")
    if out.get("type") != "program":
        out["type"] = _classify_solana(value, parsed)
    return out


def _classify_solana(value: dict, parsed: dict) -> str:
    owner = value.get("owner")
    if value.get("executable"):
        return "program"
    kind = (parsed or {}).get("type")
    if kind == "mint":
        return "spl_mint"
    if kind == "account":
        return "spl_token_account"
    if owner == "11111111111111111111111111111111" and value.get("space") == 0:
        return "wallet"  # a plain System Program keypair
    if owner == "11111111111111111111111111111111":
        return "system_account"
    return f"account_owned_by_{owner}"


def _identify_evm(chain: str, address: str) -> dict:
    from . import chains as registry
    from .evm import Rpc, is_error
    import os

    out: dict = {}
    try:
        slug = registry.ALCHEMY_SLUGS.get(chain)
        key = os.environ.get("ALCHEMY_KEY")
        rpc = (Rpc(chain, [f"https://{slug}.g.alchemy.com/v2/{key}"])
               if key and slug else Rpc(chain))
        code = rpc.code(address)
        if is_error(code):
            out["_rpc_error"] = code.get("_rpc_error")
            return out
        out["type"] = "contract" if code not in ("0x", "0x0", None) else "eoa"
        out["has_code"] = out["type"] == "contract"
        out["nonce"] = rpc.nonce(address)
    except Exception as exc:  # noqa: BLE001
        out["_rpc_error"] = str(exc)[:200]
    return out


def _external_labels(chain: str, address: str) -> dict:
    """Best-effort third-party tags. Reports unreachable sources explicitly."""
    sources: dict = {}
    sources["solscan"] = _solscan_tag(address) if chain == "sol" else {"status": "n/a"}
    sources["local_kb"] = "checked"
    return sources


def _solscan_tag(address: str) -> dict:
    """Solscan's public tag, if reachable. Cloudflare often blocks this."""
    from . import http

    try:
        response = http.get(
            f"https://api-v2.solscan.io/v2/account/{address}",
            headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
    except http.RequestError as exc:
        return {"status": "unreachable", "detail": http.redact(exc)[:120]}
    if response.status_code != 200:
        return {"status": f"http {response.status_code}"}
    try:
        data = response.json().get("data") or {}
    except (ValueError, AttributeError):
        return {"status": "bad response"}
    return {"status": "ok", "tag": data.get("name") or data.get("tag"),
            "type": data.get("type")}
