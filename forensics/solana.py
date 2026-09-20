"""Solana data access: public RPC (no key) and Helius (key, parsed)."""
from __future__ import annotations

import os

from . import chains as chain_registry
from . import http

LAMPORTS_PER_SOL = 1_000_000_000


class SolanaError(RuntimeError):
    pass


def is_error(value) -> bool:
    """True when a value is an ``{"_rpc_error": ...}`` marker."""
    return isinstance(value, dict) and "_rpc_error" in value


class Solana:
    """Keyless Solana JSON-RPC with endpoint failover."""

    def __init__(self, urls: list[str] | None = None):
        self.urls = urls or chain_registry.info("sol")["rpcs"]

    def call(self, method: str, params: list):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        errors: list[str] = []
        for url in self.urls:
            try:
                data = http.post(url, json=body, timeout=45).json()
            except (http.RequestError, ValueError) as exc:
                errors.append(f"{http.redact(url)}: {http.redact(exc)}")
                continue
            if not isinstance(data, dict):
                errors.append(f"{http.redact(url)}: unexpected non-object response")
                continue
            if "error" in data:
                return {"_rpc_error": data["error"], "method": method}
            return data.get("result")
        raise SolanaError(f"all Solana endpoints failed: {errors[-2:]}")

    def balance_sol(self, address: str) -> float:
        result = self.call("getBalance", [address])
        if is_error(result) or not isinstance(result, dict):
            return 0.0
        return result.get("value", 0) / LAMPORTS_PER_SOL

    def signatures(self, address: str, limit: int = 50) -> list[dict]:
        result = self.call("getSignaturesForAddress",
                           [address, {"limit": limit}])
        if is_error(result) or not isinstance(result, list):
            return []
        return [
            {"signature": s.get("signature"), "slot": s.get("slot"),
             "time": s.get("blockTime"), "err": s.get("err"),
             "memo": s.get("memo")}
            for s in result
        ]

    def transaction(self, signature: str) -> dict | None:
        result = self.call(
            "getTransaction",
            [signature, {"encoding": "json", "maxSupportedTransactionVersion": 0}],
        )
        if is_error(result):
            return result
        if not result:
            return None
        message = (result.get("transaction") or {}).get("message") or {}
        meta = result.get("meta") or {}
        # jsonParsed returns {"pubkey": ...}; plain json returns bare strings.
        keys = [k.get("pubkey") if isinstance(k, dict) else k
                for k in message.get("accountKeys", [])]
        required = message.get("header", {}).get("numRequiredSignatures", 1)
        return {
            "signature": signature,
            "slot": result.get("slot"),
            "time": result.get("blockTime"),
            "success": meta.get("err") is None,
            "signers": keys[:required],
            "account_keys": keys,
            "pre_balances": meta.get("preBalances"),
            "post_balances": meta.get("postBalances"),
            "pre_token_balances": meta.get("preTokenBalances"),
            "post_token_balances": meta.get("postTokenBalances"),
            "fee_lamports": meta.get("fee"),
        }


class Helius:
    """Helius Enhanced Transactions (parsed Solana activity). Requires HELIUS_KEY."""

    def __init__(self, key: str | None = None):
        self.key = key or os.environ.get("HELIUS_KEY")
        if not self.key:
            raise RuntimeError("HELIUS_KEY is not set")

    def parsed_transactions(self, address: str, limit: int = 50):
        """Parsed transactions, falling back to raw signatures if unavailable.

        ``api.helius.xyz`` is the working host; ``api-mainnet.helius.xyz`` does
        not resolve.
        """
        try:
            response = http.get(
                f"https://api.helius.xyz/v0/addresses/{address}/transactions",
                params={"api-key": self.key, "limit": limit},
            )
            if response.status_code == 200:
                return response.json()
            note = f"parsed endpoint HTTP {response.status_code}"
        except http.RequestError as exc:
            note = f"parsed endpoint error: {http.redact(exc)}"
        try:
            fallback = http.post(
                f"https://mainnet.helius-rpc.com/?api-key={self.key}",
                json={"jsonrpc": "2.0", "id": 1,
                      "method": "getSignaturesForAddress",
                      "params": [address, {"limit": limit}]},
            ).json()
        except (http.RequestError, ValueError) as exc:
            return {"_rpc_error": {"message": http.redact(exc)},
                    "_fallback": "getSignaturesForAddress", "_note": note}
        return {"_fallback": "getSignaturesForAddress", "_note": note,
                "result": (fallback or {}).get("result")}
