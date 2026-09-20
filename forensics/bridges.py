"""Cross-chain bridge resolution.

A drain that bridges out leaves a dead end on the origin chain: the value sits
in a bridge contract or vault, not in an attacker wallet. Resolving the
bridge's *intent* turns that dead end into a destination chain and recipient,
which is where the money actually went.

Relay is implemented because it is what the cases so far have used, and it
exposes a public request lookup keyed on the origin transaction hash. The
``resolve`` entry point dispatches over providers, so another can be added
without changing callers.

Matching is deliberately strict: a provider that returns requests not tied to
the requested hash must yield ``found: false``, never a neighbouring request's
destination. Mis-attributing a destination is worse than returning nothing.
"""
from __future__ import annotations

from . import http

RELAY_API = "https://api.relay.link"

# Relay chain ids -> display names, used when the live /chains call is
# unavailable. Refreshable from the API (see _chain_names).
_BUILTIN_CHAINS = {
    1: "Ethereum", 10: "Optimism", 56: "BNB", 100: "Gnosis", 130: "Unichain",
    137: "Polygon", 143: "Monad", 146: "Sonic", 999: "HyperEVM",
    1337: "Hyperliquid", 2741: "Abstract", 4663: "Robinhood Chain",
    5000: "Mantle", 5042: "Arc", 8453: "Base", 9745: "Plasma",
    42161: "Arbitrum", 43114: "Avalanche", 57073: "Ink", 59144: "Linea",
    80094: "Berachain", 81457: "Blast", 534352: "Scroll",
    9286185: "Eclipse", 792703809: "Solana",
}

_chain_cache: dict[int, str] | None = None


def _chain_names() -> dict[int, str]:
    """Chain id -> name, from Relay's /chains, cached for the process.

    Falls back to the builtin map when the API is unreachable, so a resolve
    still names the common chains rather than degrading to a bare id.
    """
    global _chain_cache
    if _chain_cache is not None:
        return _chain_cache
    names = dict(_BUILTIN_CHAINS)
    try:
        data = http.get(f"{RELAY_API}/chains", timeout=30).json()
        for chain in (data or {}).get("chains", []):
            if chain.get("id") is not None and chain.get("displayName"):
                names[chain["id"]] = chain["displayName"]
    except (http.RequestError, ValueError, AttributeError):
        pass
    _chain_cache = names
    return names


def chain_name(chain_id) -> str:
    if chain_id is None:
        return "unknown"
    return _chain_names().get(chain_id, f"chain {chain_id}")


def _same_hash(a, b) -> bool:
    """Compare tx hashes. EVM hex is case-insensitive; base58 is not."""
    if not a or not b:
        return False
    a, b = str(a), str(b)
    if a.startswith("0x") or b.startswith("0x"):
        return a.lower() == b.lower()
    return a == b


def _find_in_tx(request: dict, tx_hash: str) -> dict | None:
    for entry in ((request.get("data") or {}).get("inTxs") or []):
        if _same_hash(entry.get("hash"), tx_hash):
            return entry
    return None


def _amount(section: dict) -> dict | None:
    """Normalise a metadata currencyIn/Out block into {amount, symbol, usd}."""
    if not section:
        return None
    currency = section.get("currency") or {}
    return {
        "amount": section.get("amountFormatted"),
        "symbol": currency.get("symbol"),
        "usd": section.get("amountUsd"),
    }


def relay_request(tx_hash: str) -> dict:
    """Resolve one Relay request by its origin transaction hash.

    Returns a verbose dict. ``found`` is False when Relay knows nothing about
    the hash, or when the requests it returns do not actually contain it.
    """
    try:
        response = http.get(f"{RELAY_API}/requests/v2",
                            params={"hash": tx_hash}, timeout=30)
    except http.RequestError as exc:
        return {"provider": "relay", "found": False,
                "_rpc_error": http.redact(exc)}
    if response.status_code != 200:
        return {"provider": "relay", "found": False,
                "_rpc_error": f"relay HTTP {response.status_code}"}
    try:
        requests = (response.json() or {}).get("requests") or []
    except ValueError:
        return {"provider": "relay", "found": False,
                "_rpc_error": "relay returned non-JSON"}

    match = next((q for q in requests if _find_in_tx(q, tx_hash)), None)
    if match is None:
        # Relay returned requests, but none is this hash. Do not guess.
        return {"provider": "relay", "found": False,
                "note": "no Relay request matches this hash"}

    data = match.get("data") or {}
    metadata = data.get("metadata") or {}
    in_tx = _find_in_tx(match, tx_hash) or {}
    out_txs = data.get("outTxs") or []
    out_tx = out_txs[0] if out_txs else {}
    route = metadata.get("route") or {}
    origin = route.get("origin") or {}
    destination = route.get("destination") or {}

    result = {
        "provider": "relay",
        "found": True,
        "request_id": match.get("id"),
        "status": match.get("status"),
        "origin": {
            "chain": chain_name(in_tx.get("chainId")),
            "chain_id": in_tx.get("chainId"),
            "tx": in_tx.get("hash") or tx_hash,
            "sender": match.get("user"),
            "amount": (_amount(metadata.get("currencyIn")) or {}).get("amount"),
            "symbol": (_amount(metadata.get("currencyIn")) or {}).get("symbol"),
        },
        "destination": {
            "chain": chain_name(out_tx.get("chainId")
                                or (destination.get("inputCurrency") or {})
                                .get("currency", {}).get("chainId")),
            "chain_id": out_tx.get("chainId"),
            "recipient": match.get("recipient"),
            "amount": (_amount(metadata.get("currencyOut")) or {}).get("amount"),
            "symbol": (_amount(metadata.get("currencyOut")) or {}).get("symbol"),
            "tx": out_tx.get("hash"),
        },
        "fees_usd": data.get("feesUsd"),
    }
    if in_tx.get("timestamp") and out_tx.get("timestamp"):
        result["settled_in_seconds"] = out_tx["timestamp"] - in_tx["timestamp"]
    if not out_tx:
        result["note"] = "no destination payout yet; the request may still be pending"
    return result


# Providers tried in order. Relay first; add others as they are needed.
RESOLVERS = (relay_request,)


def resolve(tx_hash: str) -> dict:
    """Resolve a bridge transaction to its destination chain and recipient.

    Tries each known provider; returns the first positive match. When none
    matches, returns a ``found: false`` envelope rather than raising, so a
    caller can distinguish "not a bridge we know" from a transport failure.
    """
    attempts = []
    for resolver in RESOLVERS:
        result = resolver(tx_hash)
        if result.get("found"):
            return result
        attempts.append({"provider": result.get("provider"),
                         "reason": result.get("note")
                         or result.get("_rpc_error")
                         or "not found"})
    return {"provider": None, "found": False, "tx": tx_hash,
            "attempts": attempts}
