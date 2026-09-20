"""Solana data access: public RPC (no key) and Helius (key, parsed).

Two ways in, mirroring ``evm.py``:

* ``Solana``  — keyless JSON-RPC, with endpoint failover.
* ``Helius``  — parsed transactions (native + SPL transfers in one shape).

Both expose ``transfers`` so ``kit sol transfers`` / ``sol flow`` work with or
without a key. Helius is preferred when a key is present because it returns
clean per-transfer rows; the keyless path derives them from ``jsonParsed``
instructions, which is slower and capped.

A "transfer row" is the Solana analogue of ``evm.normalize_transfer``: one
canonical shape (``hash, block, time, category, asset, contract, amount, from,
to``) so callers reason about value the same way on both chains.
"""
from __future__ import annotations

import datetime
import os

from . import chains as chain_registry
from . import http
from .units import to_units

LAMPORTS_PER_SOL = 1_000_000_000
SOL_DECIMALS = 9
SYSTEM_PROGRAM = "11111111111111111111111111111111"
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"      # SPL Token
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"  # Token-2022
TOKEN_PROGRAMS = {TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID}


class SolanaError(RuntimeError):
    pass


def is_error(value) -> bool:
    """True when a value is an ``{"_rpc_error": ...}`` marker."""
    return isinstance(value, dict) and "_rpc_error" in value


def _iso(timestamp) -> str | None:
    """Unix seconds to the ISO-8601 millisecond form EVM rows use."""
    if not timestamp:
        return None
    return (datetime.datetime.fromtimestamp(timestamp, datetime.timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z")


def normalize_transfer(signature, slot, timestamp, category, asset,
                       contract, amount, frm, to, raw=None) -> dict:
    """One canonical Solana transfer row (see module docstring).

    When ``amount`` could not be scaled (unknown token decimals) but ``raw``
    base units are known, the row carries ``amount_raw`` and an ``amount_note``
    rather than presenting unscaled base units as a human figure — the same
    contract as ``evm.normalize_transfer``.
    """
    row = {
        "hash": signature,
        "block": slot,
        "time": _iso(timestamp),
        "category": category,      # "native" | "spl"
        "asset": asset,
        "contract": contract,      # mint, or None for native SOL
        "amount": amount,
        "from": frm,
        "to": to,
    }
    if amount is None and raw is not None:
        row["amount_raw"] = raw
        row["amount_note"] = "decimals unknown; raw base units, not scaled"
    return row


def _keep(amount, include_dust: bool) -> bool:
    """Drop exact-zero transfers unless dust was explicitly requested."""
    return include_dust or bool(amount)


class Solana:
    """Keyless Solana JSON-RPC with endpoint failover."""

    def __init__(self, urls: list[str] | None = None):
        self.urls = urls or chain_registry.info("sol")["rpcs"]
        self._decimals_cache: dict[str, int | None] = {}

    def mint_decimals(self, mint: str) -> int | None:
        """Decimals for an SPL mint, cached. None when it cannot be resolved."""
        if mint in self._decimals_cache:
            return self._decimals_cache[mint]
        result = self.call("getAccountInfo", [mint, {"encoding": "jsonParsed"}])
        decimals = None
        if isinstance(result, dict) and isinstance(result.get("value"), dict):
            info = ((result["value"].get("data") or {}).get("parsed") or {}).get("info") or {}
            decimals = info.get("decimals")
        self._decimals_cache[mint] = decimals
        return decimals

    def token_accounts(self, owner: str) -> list[dict]:
        """SPL token accounts for an owner, with mint, amount and delegate.

        Covers both the original Token program and Token-2022. A failed query
        for one program is skipped so the other still returns.
        """
        accounts: list[dict] = []
        for program in (TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID):
            result = self.call(
                "getTokenAccountsByOwner",
                [owner, {"programId": program}, {"encoding": "jsonParsed"}])
            if is_error(result) or not isinstance(result, dict):
                continue
            for entry in result.get("value") or []:
                parsed = ((entry.get("account") or {}).get("data") or {}).get("parsed") or {}
                info = parsed.get("info") or {}
                amount = info.get("tokenAmount") or {}
                accounts.append({
                    "account": entry.get("pubkey"),
                    "mint": info.get("mint"),
                    "amount": amount.get("uiAmount"),
                    "amount_raw": amount.get("amount"),
                    "decimals": amount.get("decimals"),
                    "delegate": info.get("delegate"),
                    "state": info.get("state"),
                    "program": program,
                })
        return accounts

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
        """Lamport balance in SOL.

        Raises on an RPC error rather than returning 0.0: a malformed address
        must not be indistinguishable from a real, empty wallet.
        """
        result = self.call("getBalance", [address])
        if is_error(result):
            raise SolanaError(f"getBalance failed: {result['_rpc_error']}")
        if not isinstance(result, dict):
            raise SolanaError("getBalance returned an unexpected response")
        return result.get("value", 0) / LAMPORTS_PER_SOL

    def signatures(self, address: str, limit: int = 50) -> list[dict]:
        """Recent signatures, newest first. Raises on an RPC error."""
        result = self.call("getSignaturesForAddress",
                           [address, {"limit": limit}])
        if is_error(result):
            raise SolanaError(
                f"getSignaturesForAddress failed: {result['_rpc_error']}")
        if not isinstance(result, list):
            raise SolanaError("getSignaturesForAddress returned an unexpected response")
        return [
            {"signature": s.get("signature"), "slot": s.get("slot"),
             "time": s.get("blockTime"), "err": s.get("err"),
             "memo": s.get("memo")}
            for s in result
        ]

    def raw_transaction(self, signature: str) -> dict | None:
        """The raw ``getTransaction`` (jsonParsed) result, or an error marker."""
        return self.call(
            "getTransaction",
            [signature, {"encoding": "jsonParsed",
                         "maxSupportedTransactionVersion": 0}],
        )

    def transaction(self, signature: str) -> dict | None:
        result = self.raw_transaction(signature)
        if is_error(result):
            return result
        if not result:
            return None
        message = (result.get("transaction") or {}).get("message") or {}
        meta = result.get("meta") or {}
        # jsonParsed returns {"pubkey": ..., "signer": bool}; plain json returns
        # bare strings. When the signer flag is present, trust it over the
        # header count: Helius' jsonParsed omits `header` entirely, which would
        # otherwise collapse a multi-signer transaction to a single signer.
        account_keys = message.get("accountKeys", [])
        keys = [k.get("pubkey") if isinstance(k, dict) else k
                for k in account_keys]
        flagged = [k["pubkey"] for k in account_keys
                   if isinstance(k, dict) and k.get("signer")]
        required = message.get("header", {}).get("numRequiredSignatures", 1)
        return {
            "signature": signature,
            "slot": result.get("slot"),
            "time": result.get("blockTime"),
            "success": meta.get("err") is None,
            "signers": flagged if flagged else keys[:required],
            "account_keys": keys,
            "programs": _programs(message, meta),
            "pre_balances": meta.get("preBalances"),
            "post_balances": meta.get("postBalances"),
            "pre_token_balances": meta.get("preTokenBalances"),
            "post_token_balances": meta.get("postTokenBalances"),
            "fee_lamports": meta.get("fee"),
        }

    def transfers(self, address: str, direction: str = "from", cap: int = 200,
                  include_dust: bool = False) -> list[dict]:
        """Derive transfer rows from jsonParsed transactions (no key).

        Bounded by ``cap``: each transaction is a separate RPC round-trip, so
        this is far slower than the Helius path. Use it for a quick look, or
        set HELIUS_KEY for full history.
        """
        signatures = self.call("getSignaturesForAddress",
                               [address, {"limit": min(cap, 1000)}])
        if is_error(signatures):
            raise SolanaError(
                f"getSignaturesForAddress failed: {signatures['_rpc_error']}")
        if not isinstance(signatures, list):
            raise SolanaError("getSignaturesForAddress returned an unexpected response")
        rows: list[dict] = []
        for entry in signatures[:cap]:
            result = self.raw_transaction(entry["signature"])
            if is_error(result) or not result:
                continue
            rows.extend(_transfers_from_parsed(result, entry["signature"],
                                               decimals_lookup=self.mint_decimals))
        return _filter_direction(rows, address, direction, include_dust)


class Helius:
    """Helius Enhanced Transactions (parsed Solana activity). Requires HELIUS_KEY."""

    PAGE = 100  # Helius caps the parsed-transactions endpoint at 100 per call.

    def __init__(self, key: str | None = None):
        self.key = key or os.environ.get("HELIUS_KEY")
        if not self.key:
            raise RuntimeError("HELIUS_KEY is not set")

    def _parsed_page(self, address: str, limit: int, before: str | None):
        params = {"api-key": self.key, "limit": min(limit, self.PAGE)}
        if before:
            params["before"] = before
        response = http.get(
            f"https://api.helius.xyz/v0/addresses/{address}/transactions",
            params=params, timeout=60)
        if response.status_code != 200:
            return {"_rpc_error": {"message": f"parsed endpoint HTTP {response.status_code}"}}
        return response.json()

    def parsed_transactions(self, address: str, limit: int = 50):
        """Parsed transactions, falling back to raw signatures if unavailable.

        ``api.helius.xyz`` is the working host; ``api-mainnet.helius.xyz`` does
        not resolve. ``limit`` is clamped to one page (100); use ``transfers``
        for full history.
        """
        page = self._parsed_page(address, limit, None)
        if isinstance(page, list):
            return page
        note = "parsed endpoint unavailable"
        try:
            fallback = http.post(
                f"https://mainnet.helius-rpc.com/?api-key={self.key}",
                json={"jsonrpc": "2.0", "id": 1,
                      "method": "getSignaturesForAddress",
                      "params": [address, {"limit": min(limit, self.PAGE)}]},
            ).json()
        except (http.RequestError, ValueError) as exc:
            return {"_rpc_error": {"message": http.redact(exc)},
                    "_fallback": "getSignaturesForAddress", "_note": note}
        return {"_fallback": "getSignaturesForAddress", "_note": note,
                "result": (fallback or {}).get("result")}

    def transfers(self, address: str, direction: str = "from", cap: int = 2000,
                  include_dust: bool = False) -> list[dict]:
        """Full transfer history for an address, paginating Helius.

        Each Helius tx is flattened into one row per native/SPL transfer that
        touches ``address``, in the same canonical shape as the keyless path.
        """
        rows: list[dict] = []
        before = None
        seen_pages = 0
        while len(rows) < cap and seen_pages < 100:
            page = self._parsed_page(address, self.PAGE, before)
            if is_error(page) or not isinstance(page, list) or not page:
                break
            seen_pages += 1
            for tx in page:
                rows.extend(_transfers_from_parsed_helius(tx, address))
            if len(page) < self.PAGE:
                break
            before = page[-1].get("signature")
        return _filter_direction(rows, address, direction, include_dust)


# --------------------------------------------------------------------------
# transfer extraction
# --------------------------------------------------------------------------
def _transfers_from_parsed_helius(tx: dict, owner: str) -> list[dict]:
    """Flatten one Helius parsed transaction into canonical rows."""
    signature = tx.get("signature")
    slot = tx.get("slot")
    timestamp = tx.get("timestamp")
    rows: list[dict] = []
    for n in tx.get("nativeTransfers") or []:
        frm, to = n.get("fromUserAccount"), n.get("toUserAccount")
        if owner not in (frm, to):
            continue
        rows.append(normalize_transfer(
            signature, slot, timestamp, "native", "SOL", None,
            to_units(n.get("amount"), SOL_DECIMALS), frm, to))
    for t in tx.get("tokenTransfers") or []:
        frm, to = t.get("fromUserAccount"), t.get("toUserAccount")
        if owner not in (frm, to):
            continue
        mint = t.get("mint")
        rows.append(normalize_transfer(
            signature, slot, timestamp, "spl", mint, mint,
            t.get("tokenAmount"), frm, to))
    return rows


def _transfers_from_parsed(result: dict, signature: str | None,
                           decimals_lookup=None) -> list[dict]:
    """Flatten one jsonParsed transaction into canonical rows (keyless path).

    ``decimals_lookup(mint)`` is consulted when neither the instruction nor the
    pre/post token balances carry decimals — common for the transient pool
    accounts a DEX route uses, which never appear in the balance lists.
    """
    signature = signature or _signature_of(result)
    slot = result.get("slot")
    timestamp = result.get("blockTime")
    message = (result.get("transaction") or {}).get("message") or {}
    meta = result.get("meta") or {}
    account_keys = [k.get("pubkey") if isinstance(k, dict) else k
                    for k in message.get("accountKeys") or []]
    token_index = _token_account_index(meta, account_keys)

    rows: list[dict] = []
    for ix in _all_instructions(message, meta):
        parsed = ix.get("parsed")
        if not isinstance(parsed, dict):
            continue
        program = ix.get("programId")
        info = parsed.get("info") or {}
        kind = parsed.get("type")
        if program == SYSTEM_PROGRAM and kind == "transfer":
            rows.append(normalize_transfer(
                signature, slot, timestamp, "native", "SOL", None,
                to_units(info.get("lamports"), SOL_DECIMALS),
                info.get("source"), info.get("destination")))
        elif program in TOKEN_PROGRAMS and kind in ("transfer", "transferChecked"):
            src, dst = info.get("source"), info.get("destination")
            entry = token_index.get(src) or token_index.get(dst) or {}
            # `transfer` may carry `amount` or a `tokenAmount` object; the
            # latter already includes decimals, so prefer it when present.
            token_amount = info.get("tokenAmount") or {}
            mint = info.get("mint") or entry.get("mint")
            raw = info.get("amount") or token_amount.get("amount")
            decimals = info.get("decimals") or token_amount.get("decimals")
            if decimals is None:
                decimals = entry.get("decimals")
            if decimals is None and mint and decimals_lookup:
                decimals = decimals_lookup(mint)
            amount = to_units(raw, decimals) if decimals is not None else None
            rows.append(normalize_transfer(
                signature, slot, timestamp, "spl", mint, mint, amount,
                _owner_for(token_index, src), _owner_for(token_index, dst),
                raw=raw))
    return [r for r in rows if r["from"] or r["to"]]


def _signature_of(result: dict) -> str | None:
    sigs = (result.get("transaction") or {}).get("signatures") or []
    return sigs[0] if sigs else None


def _all_instructions(message: dict, meta: dict):
    """Top-level instructions plus inner ones, flattened."""
    for ix in message.get("instructions") or []:
        yield ix
    for group in meta.get("innerInstructions") or []:
        for ix in group.get("instructions") or []:
            yield ix


def _token_account_index(meta: dict, account_keys: list) -> dict[str, dict]:
    """token-account address -> {mint, owner, decimals}.

    ``postTokenBalances``/``preTokenBalances`` carry an integer ``accountIndex``,
    not the account address, so resolve it through ``accountKeys``.
    """
    index: dict[str, dict] = {}
    for balance in (meta.get("postTokenBalances") or []) + (meta.get("preTokenBalances") or []):
        position = balance.get("accountIndex")
        if not isinstance(position, int) or position >= len(account_keys):
            continue
        address = account_keys[position]
        index.setdefault(address, {
            "mint": balance.get("mint"),
            "owner": balance.get("owner"),
            "decimals": (balance.get("uiTokenAmount") or {}).get("decimals"),
        })
    return index


def _owner_for(index: dict[str, dict], account_address):
    if not account_address:
        return None
    entry = index.get(account_address)
    return entry.get("owner") if entry else None


def _programs(message: dict, meta: dict) -> list[str]:
    """Unique program ids invoked, top-level and inner, in order."""
    seen: list[str] = []
    for ix in _all_instructions(message, meta):
        program = ix.get("programId")
        if program and program not in seen:
            seen.append(program)
    return seen


def _filter_direction(rows: list[dict], address: str, direction: str,
                      include_dust: bool) -> list[dict]:
    """Keep rows touching ``address`` on the requested side, drop dust."""
    out = []
    for row in rows:
        if not _keep(row.get("amount"), include_dust):
            continue
        if direction == "from" and row.get("from") != address:
            continue
        if direction == "to" and row.get("to") != address:
            continue
        out.append(row)
    return out
