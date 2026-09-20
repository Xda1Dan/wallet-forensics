"""Third-party REST providers that are not chain RPCs."""
from __future__ import annotations

import os

from . import chains as chain_registry
from . import http

ETHERSCAN_V2 = "https://api.etherscan.io/v2/api"


class ProviderError(RuntimeError):
    """A provider call failed in a way the caller should surface as data."""


class Etherscan:
    """Etherscan V2: one key, many chains. Free tier: 3 calls/s, 100k/day.

    Not all chains are on the free tier (BNB is paid-only; Robinhood and Arc
    are free until 2026-10-15). Source/ABI endpoints stay free everywhere.
    """

    def __init__(self, key: str | None = None):
        self.key = key or os.environ.get("ETHERSCAN_KEY")
        if not self.key:
            raise RuntimeError("ETHERSCAN_KEY is not set")

    def call(self, chain_id: int, module: str, action: str, **params):
        """One Etherscan call, returned as-is.

        A transport failure comes back as a redacted ``{"_rpc_error": ...}``,
        mirroring the RPC modules.
        """
        try:
            response = http.get(ETHERSCAN_V2, params={
                "chainid": chain_id, "module": module, "action": action,
                "apikey": self.key, **params,
            })
            data = response.json()
        except (http.RequestError, ValueError) as exc:
            return {"_rpc_error": {"message": http.redact(exc)},
                    "module": module, "action": action}
        return data

    def transactions(self, chain: int, address: str, **overrides):
        params = {"address": address, "startblock": 0, "endblock": 99_999_999,
                  "sort": "asc", "page": 1, "offset": 100, **overrides}
        return self.call(chain, "account", "txlist", **params)

    def token_transfers(self, chain: int, address: str, **overrides):
        params = {"address": address, "page": 1, "offset": 100, "sort": "asc",
                  **overrides}
        return self.call(chain, "account", "tokentx", **params)


class DexScreener:
    """Free token price/liquidity lookup (no key), including brand-new pools.

    Results are memoised per process: a screen run asks about the same contract
    once per transfer, and the free tier is ~60 req/min.
    """

    _cache: dict[tuple[str, str], list] = {}

    @classmethod
    def _slug(cls, chain: str) -> str:
        return chain_registry.DEXSCREENER_SLUGS.get(
            chain_registry.resolve(chain), chain)

    @classmethod
    def _pairs(cls, chain: str, token_address: str) -> list | None:
        """Raw pair list for a token, cached.

        Returns [] for a token with genuinely no market, or None when the lookup
        failed. Failures are not cached: caching an empty list on a transient
        error would make the token look pair-less for the rest of the process.
        """
        slug = cls._slug(chain)
        key = (slug, (token_address or "").lower())
        if key in cls._cache:
            return cls._cache[key]
        try:
            data = http.get(
                f"https://api.dexscreener.com/tokens/v1/{slug}/{token_address}"
            ).json()
        except (http.RequestError, ValueError):
            return None
        pairs = data if isinstance(data, list) else []
        cls._cache[key] = pairs
        return pairs

    @classmethod
    def token(cls, chain: str, token_address: str) -> dict:
        pairs = cls._pairs(chain, token_address) or []
        if pairs:
            pair = pairs[0]
            return {"price_usd": pair.get("priceUsd"),
                    "liquidity_usd": (pair.get("liquidity") or {}).get("usd"),
                    "dex": pair.get("dexId"), "pair": pair.get("pairAddress")}
        return {}

    @classmethod
    def has_pair(cls, chain: str, token_address: str) -> bool | None:
        """Whether a token has any DEX pair. ``None`` when unknown."""
        pairs = cls._pairs(chain, token_address)
        if pairs is None:
            return None
        return bool(pairs)


class Jupiter:
    """Solana token metadata (symbol, name, decimals) by mint. No key needed.

    Used to name SPL mints, which the chain itself does not do. Results are
    memoised per process, and a lookup failure is not cached so a transient
    error does not blank the symbol for the rest of the run.
    """

    BASE = "https://lite-api.jup.ag/tokens/v2/search"
    _cache: dict[str, dict | None] = {}

    @classmethod
    def tokens(cls, mints: list[str]) -> dict[str, dict]:
        """Metadata for the given mints, keyed by mint.

        Mints are looked up in one request; unknown mints are simply absent
        from the result rather than being an error.
        """
        wanted = [m for m in dict.fromkeys(mints) if m]
        missing = [m for m in wanted if m not in cls._cache]
        if missing:
            cls._fetch(missing)
        return {m: cls._cache[m] for m in wanted if cls._cache.get(m)}

    @classmethod
    def _fetch(cls, mints: list[str]) -> None:
        try:
            response = http.get(cls.BASE, params={"query": ",".join(mints)})
            data = response.json()
        except (http.RequestError, ValueError):
            return  # leave the cache untouched; a failure is not "no metadata"
        if not isinstance(data, list):
            return
        found = {entry.get("id"): entry for entry in data
                 if isinstance(entry, dict) and entry.get("id")}
        for mint in mints:
            entry = found.get(mint)
            cls._cache[mint] = ({
                "symbol": entry.get("symbol"),
                "name": entry.get("name"),
                "decimals": entry.get("decimals"),
            } if entry else None)
