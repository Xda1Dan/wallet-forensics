"""EVM data access: keyless public JSON-RPC and Alchemy.

``Rpc`` fails over between a chain's public endpoints and batches calls into one
HTTP request; map_concurrent fans that across a thread pool. A
method-level RPC error comes back as ``{"_rpc_error": ...}`` instead of raising,
so one bad call does not abort a scan. RpcError is raised only when
every endpoint fails, with the message redacted.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

from . import address as addr
from . import chains as chain_registry
from . import http
from .abi import CATEGORIES_WITHOUT_INTERNAL, TRANSFER_CATEGORIES
from .units import to_int, to_units


class RpcError(RuntimeError):
    """All endpoints for a chain failed."""


def is_error(value) -> bool:
    """True when a value is an ``{"_rpc_error": ...}`` marker from this module."""
    return isinstance(value, dict) and "_rpc_error" in value


class Rpc:
    """JSON-RPC client for one chain, with public-RPC failover."""

    def __init__(self, chain: str, urls: list[str] | None = None):
        self.chain = chain_registry.resolve(chain)
        self.urls = urls or chain_registry.info(chain)["rpcs"]

    def call(self, method: str, params: list):
        """Call one method, trying each endpoint in turn."""
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
                # A method-level error is not worth retrying on other nodes.
                return {"_rpc_error": data["error"], "method": method}
            return data.get("result")
        raise RpcError(f"all endpoints failed for {self.chain}: {errors[-2:]}")

    def batch(self, calls: list[tuple[str, list]]):
        """Call many methods in one request. Returns results in input order.

        Falls back to sequential calls if the endpoint rejects batching. A
        per-call error is surfaced as ``{"_rpc_error": ...}`` in its slot rather
        than blanking the slot to None.
        """
        if not calls:
            return []
        body = [
            {"jsonrpc": "2.0", "id": i, "method": method, "params": params}
            for i, (method, params) in enumerate(calls)
        ]
        for url in self.urls:
            try:
                data = http.post(url, json=body, timeout=90).json()
            except (http.RequestError, ValueError):
                continue
            if not isinstance(data, list):
                break  # endpoint refused the batch
            by_id = {item.get("id"): item for item in data if isinstance(item, dict)}
            results = []
            for i, (method, _params) in enumerate(calls):
                item = by_id.get(i)
                if item is None:
                    results.append({"_rpc_error": {"message": "no result in batch"},
                                    "method": method})
                elif "error" in item:
                    results.append({"_rpc_error": item["error"], "method": method})
                else:
                    results.append(item.get("result"))
            return results
        return [self.call(method, params) for method, params in calls]

    # --- convenience wrappers -------------------------------------------
    def transaction(self, tx_hash: str):
        return self.call("eth_getTransactionByHash", [tx_hash])

    def receipt(self, tx_hash: str):
        return self.call("eth_getTransactionReceipt", [tx_hash])

    def balance(self, address: str) -> int:
        result = self.call("eth_getBalance", [address, "latest"])
        if is_error(result):
            return 0
        return to_int(result)

    def code(self, address: str) -> str:
        result = self.call("eth_getCode", [address, "latest"])
        if is_error(result) or not isinstance(result, str):
            return "0x"
        return result or "0x"

    def nonce(self, address: str) -> int:
        result = self.call("eth_getTransactionCount", [address, "latest"])
        if is_error(result):
            return 0
        return to_int(result)

    def logs(self, params: dict):
        return self.call("eth_getLogs", [params])


def map_concurrent(fn, items, workers: int = 8):
    """Apply ``fn`` to every item on a small thread pool, preserving order."""
    items = list(items)
    if len(items) <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(fn, items))


def normalize_transfer(transfer: dict, decimals_map: dict | None = None) -> dict:
    """Turn a raw alchemy_getAssetTransfers entry into a canonical row.

    Used by transfers/flow and screen alike, so the two cannot scale or name a
    value differently. ``decimals_map`` supplies decimals for tokens Alchemy
    returned with ``decimal: null``. When the scale cannot be determined the row
    carries ``amount_raw`` and an ``amount_note`` instead of presenting base
    units as a human figure.
    """
    raw_contract = transfer.get("rawContract") or {}
    raw = raw_contract.get("value")
    contract = raw_contract.get("address")
    decimals = raw_contract.get("decimal")
    if decimals is None and decimals_map:
        decimals = decimals_map.get(contract)

    amount = to_units(raw, decimals) if raw else None
    if amount is None and not raw:
        # Native transfers carry no rawContract; `value` is already human.
        amount = transfer.get("value")

    row = {
        "hash": transfer.get("hash"),
        "block": transfer.get("blockNum"),
        "time": (transfer.get("metadata") or {}).get("blockTimestamp"),
        "category": transfer.get("category"),
        "asset": transfer.get("asset") or contract,
        "contract": contract,
        "amount": amount,
        "from": addr.normalize(transfer.get("from")),
        "to": addr.normalize(transfer.get("to")),
    }
    if raw and amount is None:
        row["amount_raw"] = raw
        row["amount_note"] = "decimals unknown; raw base units, not scaled"
    return row


class Alchemy:
    """Alchemy-backed reads (transfers, tokens, prices). Requires ALCHEMY_KEY."""

    def __init__(self, key: str | None = None):
        self.key = key or os.environ.get("ALCHEMY_KEY")
        if not self.key:
            raise RuntimeError("ALCHEMY_KEY is not set")
        # Most recent failure from _rpc, or None. Set here so callers can read
        # it unconditionally (a bare `price` never calls _rpc).
        self.last_error: object | None = None

    def url(self, chain: str) -> str:
        slug = chain_registry.ALCHEMY_SLUGS[chain_registry.resolve(chain)]
        return f"https://{slug}.g.alchemy.com/v2/{self.key}"

    def _rpc(self, chain: str, method: str, params: list):
        """One Alchemy JSON-RPC call. Returns the result, or None on failure.

        A failure is recorded in last_error rather than raised, so
        callers can fall back (e.g. the internal-category retry in transfers).
        """
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        try:
            response = http.post(self.url(chain), json=body, timeout=60)
            data = response.json()
        except (http.RequestError, ValueError) as exc:
            self.last_error = http.redact(exc)
            return None
        if not isinstance(data, dict):
            self.last_error = "unexpected non-object response"
            return None
        if "error" in data:
            self.last_error = data["error"]
            return None
        self.last_error = None
        return data.get("result")

    def transfers(self, chain: str, address: str, direction: str = "from",
                  cap: int = 5000, include_zero: bool = False) -> list[dict]:
        """Full transfer history for an address, newest last.

        Chains that reject the ``internal`` category are retried with the reduced
        set. An empty result is distinguished from a hard failure by last_error.
        """
        chain = chain_registry.resolve(chain)
        side = "fromAddress" if direction == "from" else "toAddress"
        base = {
            "fromBlock": "0x0", "toBlock": "latest",
            "withMetadata": True, "excludeZeroValue": not include_zero,
            "maxCount": "0x3e8", side: addr.normalize(address),
        }
        for categories in (TRANSFER_CATEGORIES, CATEGORIES_WITHOUT_INTERNAL):
            page, results, supported = dict(base, category=list(categories)), [], False
            while len(results) < cap:
                payload = self._rpc(chain, "alchemy_getAssetTransfers", [dict(page)])
                if payload is None:
                    break
                supported = True
                results.extend(payload.get("transfers", []))
                key = payload.get("pageKey")
                if not key:
                    break
                page["pageKey"] = key
            if supported:
                return results
        return []

    def fill_missing_decimals(self, chain: str, transfers: list[dict]) -> dict:
        """Resolve decimals for tokens Alchemy returned with ``decimal: null``.

        Arc's native USDC is one: the raw integer would otherwise be presented as
        if it were already scaled, off by ``10**decimals``. Returns a
        ``{contract: decimals}`` map for the tokens that needed it.
        """
        missing = sorted({
            contract
            for t in transfers
            if (contract := (t.get("rawContract") or {}).get("address"))
            and (t.get("rawContract") or {}).get("value")
            and (t.get("rawContract") or {}).get("decimal") is None
        })
        if not missing:
            return {}
        metas = map_concurrent(lambda c: self.token_metadata(chain, c), missing)
        return {c: m.get("decimals") for c, m in zip(missing, metas)
                if isinstance(m, dict) and m.get("decimals") is not None}

    def token_balances(self, chain: str, address: str, include_zero: bool = False):
        result = self._rpc(chain, "alchemy_getTokenBalances",
                           [addr.normalize(address), "erc20"]) or {}
        balances = result.get("tokenBalances", [])
        if include_zero:
            return balances
        return [b for b in balances if b.get("tokenBalance") not in (None, "0x0", "0x")]

    def token_metadata(self, chain: str, token: str):
        return self._rpc(chain, "alchemy_getTokenMetadata",
                         [addr.normalize(token)]) or {}

    def price_by_symbol(self, symbols: list[str]) -> dict:
        response = self._prices_get(
            "https://api.g.alchemy.com/prices/v1/tokens/by-symbol",
            params={"symbols": ",".join(symbols)},
        )
        prices = {}
        for row in (response or {}).get("data", []):
            quotes = row.get("prices") or []
            if quotes and not row.get("error"):
                prices[row["symbol"]] = quotes[0]["value"]
        return prices

    def price_at(self, symbol: str, start: str, end: str,
                 interval: str = "5m") -> list[dict]:
        """Historical price series for ``symbol`` between two ISO timestamps."""
        response = self._prices_post(
            "https://api.g.alchemy.com/prices/v1/tokens/historical",
            json={"symbol": symbol, "startTime": start, "endTime": end,
                  "interval": interval},
        )
        return (response or {}).get("data", [])

    # --- Prices API transport, with the same error capture as _rpc ----------
    def _prices_get(self, url: str, **kwargs):
        return self._prices_call(http.get, url, **kwargs)

    def _prices_post(self, url: str, **kwargs):
        return self._prices_call(http.post, url, **kwargs)

    def _prices_call(self, method, url: str, **kwargs):
        """Call the Prices API, recording failures in last_error."""
        kwargs.setdefault("headers", {})
        kwargs["headers"]["Authorization"] = f"Bearer {self.key}"
        try:
            response = method(url, timeout=60, **kwargs)
            data = response.json()
        except (http.RequestError, ValueError) as exc:
            self.last_error = http.redact(exc)
            return None
        if not isinstance(data, dict):
            self.last_error = "unexpected non-object response"
            return None
        self.last_error = None
        return data
