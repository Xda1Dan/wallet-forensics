"""Command line: ``python -m forensics.cli <command> ...``.

Every command performs one query and prints verbose JSON. Nothing prints a
verdict: the caller (usually an AI agent) reads the output and reasons.

Errors are returned as ``{"_error": ...}`` / ``{"_rpc_error": ...}`` rather than
tracebacks, so a caller can adapt mid-investigation. main is the single
choke point that guarantees this: any exception a command fails to handle is
turned into JSON, with provider keys redacted.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

from . import __version__
from . import address as addr
from . import bridges
from . import chains as chain_registry
from . import env
from . import http
from . import labels
from . import spam
from .abi import EVENTS, SELECTORS, TOPIC_APPROVAL, TOPIC_APPROVAL_FOR_ALL, TOPIC_TRANSFER
from .evm import Alchemy, Rpc, RpcError, is_error, map_concurrent, normalize_transfer
from .providers import DexScreener
from .solana import Helius, Solana, SolanaError
from .units import to_int, to_units


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------
def _has_alchemy() -> bool:
    return bool(os.environ.get("ALCHEMY_KEY"))


def _rpc(chain: str, force_public: bool = False) -> Rpc:
    """A chain RPC client, preferring Alchemy's node when a key is present."""
    if _has_alchemy() and not force_public:
        slug = chain_registry.ALCHEMY_SLUGS.get(chain_registry.resolve(chain))
        if slug:
            key = os.environ["ALCHEMY_KEY"]
            return Rpc(chain, [f"https://{slug}.g.alchemy.com/v2/{key}"])
    return Rpc(chain)


def _alchemy() -> Alchemy:
    return Alchemy()


def _emit(payload) -> None:
    print(json.dumps(payload, indent=2))


def _decode_call(data: str) -> dict:
    if not data or data in ("0x", "0x0"):
        return {"fn": "plain_send", "selector": None}
    selector = data[:10]
    return {"fn": SELECTORS.get(selector, f"unknown_{selector}"),
            "selector": selector}


def _label(value: str | None):
    return labels.annotate(value) if value else None


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_tx(args) -> dict:
    chain = chain_registry.resolve(args.chain)
    rpc = _rpc(chain, args.no_alchemy)
    tx = rpc.transaction(args.hash)
    if is_error(tx):
        return tx
    tx = tx or {}
    receipt = rpc.receipt(args.hash)
    if is_error(receipt):
        receipt = {}

    logs = []
    for entry in (receipt.get("logs") or []) if isinstance(receipt, dict) else []:
        topics = entry.get("topics") or [""]
        decoded = {"contract": entry.get("address"),
                   "event": EVENTS.get(topics[0], "other")}
        if topics[0] == TOPIC_TRANSFER and len(topics) == 3:
            decoded.update({"from": addr.from_topic(topics[1]),
                            "to": addr.from_topic(topics[2]),
                            "amount_raw": entry.get("data")})
        logs.append(decoded)

    call = _decode_call(tx.get("input", "0x"))
    return {
        "chain": chain,
        "hash": args.hash,
        "from": tx.get("from"), "from_label": _label(tx.get("from")),
        "to": tx.get("to"), "to_label": _label(tx.get("to")),
        "value_wei": to_int(tx.get("value")),
        "nonce": tx.get("nonce"),
        "type": tx.get("type"),
        "gas": tx.get("gas"),
        "gas_used": receipt.get("gasUsed") if isinstance(receipt, dict) else None,
        "status": receipt.get("status") if isinstance(receipt, dict) else None,
        "block": (receipt.get("blockNumber") if isinstance(receipt, dict) else None)
        or tx.get("blockNumber"),
        "fn": call["fn"],
        "input_full": tx.get("input", "0x"),
        "logs": logs,
    }


def cmd_transfers(args) -> dict:
    chain = chain_registry.resolve(args.chain)
    alchemy = _alchemy()
    transfers = alchemy.transfers(chain, args.addr, direction=args.dir,
                                  cap=args.cap, include_zero=args.include_dust)
    decimals = alchemy.fill_missing_decimals(chain, transfers)
    return {"chain": chain, "dir": args.dir, "count": len(transfers),
            "error": alchemy.last_error,
            "transfers": [_transfer_row(t, decimals) for t in transfers]}


def _transfer_row(t: dict, decimals_map: dict | None = None) -> dict:
    """A canonical transfer row (see evm.normalize_transfer) plus labels."""
    return {**normalize_transfer(t, decimals_map),
            "from_label": _label(t.get("from")),
            "to_label": _label(t.get("to"))}


def cmd_flow(args) -> dict:
    args.dir = "from"
    return cmd_transfers(args)


def cmd_approvals(args) -> dict:
    chain = chain_registry.resolve(args.chain)
    rpc = _rpc(chain, args.no_alchemy)
    owner = addr.normalize(args.owner)
    results = []
    for topic, kind in ((TOPIC_APPROVAL, "erc20_approve"),
                        (TOPIC_APPROVAL_FOR_ALL, "nft_approval_for_all")):
        logs = rpc.logs({"topics": [topic, addr.topic(owner)],
                         "fromBlock": args.from_block, "toBlock": args.to_block})
        if is_error(logs):
            results.append({"kind": kind, "error": logs["_rpc_error"],
                            "hint": "range too wide? narrow with --from-block/--to-block"})
            continue
        # Cap before resolving senders: no point paying for txs we will not show.
        logs = (logs or [])[: args.cap]
        senders = _approval_senders(rpc, [lg["transactionHash"] for lg in logs])
        for log in logs:
            value = to_int(log.get("data")) if kind == "erc20_approve" else None
            sender = senders.get(log["transactionHash"], "")
            results.append({
                "kind": kind, "block": log.get("blockNumber"),
                "tx": log.get("transactionHash"),
                "spender": addr.from_topic(log["topics"][2]),
                "unlimited": value is not None and value >= 2 ** 255,
                "value_raw": value,
                "tx_sender": sender,
                # Heuristic, not proof: a grant sent by someone other than the
                # owner suggests an off-chain signature (permit phishing) was
                # redeemed. The permit payload itself is not decoded.
                "permit_fingerprint": bool(sender) and sender != owner,
            })
    return {"chain": chain, "owner": args.owner, "count": len(results),
            "approvals": results}


def _approval_senders(rpc: Rpc, hashes: list[str]) -> dict[str, str]:
    """Resolve the sender of each tx in one batched call."""
    if not hashes:
        return {}
    receipts = rpc.batch([("eth_getTransactionReceipt", [h]) for h in hashes])
    return {
        h: addr.normalize((receipt or {}).get("from", ""))
        for h, receipt in zip(hashes, receipts)
        if not is_error(receipt)
    }


def cmd_balances(args) -> dict:
    chains = ([chain_registry.resolve(c) for c in args.chains.split(",")]
              if args.chains else list(chain_registry.EVM_CHAINS))
    out = {}
    for chain in chains:
        rpc = _rpc(chain, args.no_alchemy)
        info = chain_registry.info(chain)
        try:
            code = rpc.code(args.addr)
            out[chain] = {
                "symbol": info["native_symbol"],
                "chain_id": info["chain_id"],
                "native": rpc.balance(args.addr) / 10 ** info["native_decimals"],
                "nonce": rpc.nonce(args.addr),
                "has_code": code not in ("0x", "0x0"),
                "eip7702_delegate": addr.delegate(code),
            }
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as JSON
            out[chain] = {"error": http.redact(str(exc))[:200]}
    return out


def cmd_tokens(args) -> dict:
    chain = chain_registry.resolve(args.chain)
    alchemy = _alchemy()
    balances = alchemy.token_balances(chain, args.addr, args.include_dust)[: args.cap]
    # Metadata lookups are independent; fetch them concurrently.
    metadata = map_concurrent(
        lambda b: alchemy.token_metadata(chain, b["contractAddress"]), balances)
    rows = []
    for balance, meta in zip(balances, metadata):
        decimals = meta.get("decimals")
        rows.append({
            "contract": balance["contractAddress"],
            "symbol": meta.get("symbol"),
            "decimals": decimals,
            "amount": to_units(balance.get("tokenBalance"), decimals)
            if decimals is not None else balance.get("tokenBalance"),
        })
    return {"chain": chain, "addr": args.addr, "error": alchemy.last_error,
            "tokens": rows}


def cmd_price(args) -> dict:
    if args.token:
        chain, token = args.token.split(":", 1)
        return {"source": "dexscreener", "token": DexScreener.token(chain, token)}
    alchemy = _alchemy()
    if args.at:
        end = datetime.datetime.fromisoformat(args.at.replace("Z", "+00:00"))
        start = end - datetime.timedelta(hours=1)
        prices = {}
        for symbol in args.symbol.split(","):
            series = alchemy.price_at(
                symbol, start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                end.strftime("%Y-%m-%dT%H:%M:%SZ"))
            prices[symbol] = {"at": args.at,
                              "price": series[-1]["value"] if series else None}
        return {"source": "alchemy-historical", "prices": prices,
                "error": alchemy.last_error}
    return {"source": "alchemy",
            "error": alchemy.last_error,
            "prices": alchemy.price_by_symbol(args.symbol.split(","))}


def cmd_screen(args) -> dict:
    chain = chain_registry.resolve(args.chain)
    references = _parse_references(args.ref)
    alchemy = _alchemy()
    transfers = (alchemy.transfers(chain, args.addr, "from", args.cap, True)
                 + alchemy.transfers(chain, args.addr, "to", args.cap, True))
    transfers = _dedupe_transfers(transfers)
    decimals = alchemy.fill_missing_decimals(chain, transfers)
    rows, summary = spam.screen(transfers, references, chain,
                                check_dex=not args.no_dex, decimals_map=decimals)
    return {"chain": chain, "addr": args.addr, "references": references,
            "error": alchemy.last_error, "summary": summary,
            "clean": [r for r in rows if not r["suspected_spam"]],
            "suspected_spam": [r for r in rows if r["suspected_spam"]]}


def _dedupe_transfers(transfers: list[dict]) -> list[dict]:
    """Drop rows repeated across the from/to halves of a ``screen`` pull.

    Keyed on the fields that identify a transfer, since a self-send (or any
    transfer matching both directions) otherwise appears twice.
    """
    seen: set[tuple] = set()
    unique = []
    for t in transfers:
        key = (t.get("hash"), t.get("category"),
               (t.get("rawContract") or {}).get("address"),
               t.get("from"), t.get("to"), t.get("value"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    return unique


def _parse_references(spec: str | None) -> dict[str, str]:
    references = {}
    for item in (spec or "").split(","):
        if "=" in item:
            name, _, value = item.partition("=")
            references[name] = value
    return references


_B58 = set("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")


def _validate_sol_address(address: str | None) -> dict | None:
    """An error envelope for a missing/malformed Solana address, else None."""
    if not address:
        return {"_error": "a Solana address is required for this query",
                "type": "MissingAddress",
                "hint": "pass --addr <base58 address>"}
    if address.lower().startswith("0x") or not 32 <= len(address) <= 44 \
            or not set(address) <= _B58:
        return {"_error": f"not a base58 Solana address: {address!r}",
                "type": "BadAddress",
                "hint": "Solana addresses are base58, 32-44 chars, no 0x prefix "
                        "and no characters like 0, O, I or l"}
    return None


def cmd_sol(args) -> dict:
    if args.what == "tx":
        if not args.sig:
            return {"_error": "a transaction signature is required",
                    "type": "MissingSignature", "hint": "pass --sig <signature>"}
    else:
        problem = _validate_sol_address(args.addr)
        if problem:
            return problem
    try:
        if args.what == "parsed":
            return Helius().parsed_transactions(args.addr, args.cap)
        client = Solana()
        if args.what == "balance":
            return {"addr": args.addr, "sol": client.balance_sol(args.addr)}
        if args.what == "sigs":
            return {"addr": args.addr, "signatures": client.signatures(args.addr, args.cap)}
        if args.what == "tx":
            return _sol_tx(client.transaction(args.sig))
        if args.what in ("transfers", "flow"):
            return _sol_transfers(args)
    except Exception as exc:  # noqa: BLE001
        return {"_rpc_error": f"{type(exc).__name__}: {http.redact(str(exc))[:300]}",
                "hint": "Solana addresses are base58, not 0x...; use --addr"}
    raise ValueError("sol what must be balance|sigs|tx|transfers|flow|parsed")


def _sol_tx(tx) -> dict:
    """Annotate a decoded Solana tx with labels and any bridge program.

    A bridge program in the instruction set means value left this chain, which
    changes the read of a "transfer" completely — surface it, do not bury it.
    """
    if not isinstance(tx, dict) or "_rpc_error" in tx:
        return tx
    tx["signer_labels"] = [_label(s) for s in tx.get("signers", [])]
    programs = tx.get("programs") or []
    tx["program_labels"] = {p: _label(p) for p in programs if _label(p)}
    bridges = [p for p in programs
               if (labels.lookup(p) or {}).get("kind") == "bridge"]
    if bridges:
        tx["bridge_programs"] = bridges
        tx["bridge_note"] = ("this transaction invokes a bridge program; the "
                             "value likely left this chain")
    return tx


def _sol_transfers(args) -> dict:
    """Shared body for ``sol transfers`` and ``sol flow`` (flow == outbound)."""
    direction = "from" if args.what == "flow" else args.dir
    client, source = _sol_client()
    rows = client.transfers(args.addr, direction=direction, cap=args.cap,
                            include_dust=args.include_dust)
    annotated = [{**row, "from_label": _label(row.get("from")),
                  "to_label": _label(row.get("to"))} for row in rows]
    return {"chain": "sol", "addr": args.addr, "dir": direction,
            "source": source, "count": len(annotated), "transfers": annotated}


def _sol_client():
    """Prefer Helius (parsed, paginated); fall back to keyless RPC."""
    if os.environ.get("HELIUS_KEY"):
        return Helius(), "helius"
    return Solana(), "rpc"


def cmd_bridge(args) -> dict:
    """Resolve a bridge transaction to its destination chain and recipient.

    A drain that bridges out ends at a bridge contract on the origin chain;
    this reads the bridge's own intent to say where the value actually landed.
    """
    return bridges.resolve(args.tx)


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kit", description="Composable wallet-drain forensics queries (verbose JSON).")
    parser.add_argument("--version", action="version",
                        version=f"wallet-forensics {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("tx", help="decode one transaction")
    p.add_argument("--chain", required=True)
    p.add_argument("--hash", required=True)
    p.add_argument("--no-alchemy", action="store_true")
    p.set_defaults(func=cmd_tx)

    p = sub.add_parser("transfers", help="full transfer history for an address")
    p.add_argument("--chain", required=True)
    p.add_argument("--addr", required=True)
    p.add_argument("--dir", default="from", choices=["from", "to"])
    p.add_argument("--cap", type=int, default=2000)
    p.add_argument("--include-dust", action="store_true")
    p.set_defaults(func=cmd_transfers)

    p = sub.add_parser("flow", help="outbound transfers from any address (1 hop)")
    p.add_argument("--chain", required=True)
    p.add_argument("--addr", required=True)
    p.add_argument("--cap", type=int, default=500)
    p.add_argument("--include-dust", action="store_true")
    p.set_defaults(func=cmd_flow)

    p = sub.add_parser("approvals", help="Approval/ApprovalForAll logs for an owner")
    p.add_argument("--chain", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--from-block", default="0x0")
    p.add_argument("--to-block", default="latest")
    p.add_argument("--cap", type=int, default=200)
    p.add_argument("--no-alchemy", action="store_true")
    p.set_defaults(func=cmd_approvals)

    p = sub.add_parser("balances", help="native balance, nonce, code, 7702 per chain")
    p.add_argument("--addr", required=True)
    p.add_argument("--chains", default=None)
    p.add_argument("--no-alchemy", action="store_true")
    p.set_defaults(func=cmd_balances)

    p = sub.add_parser("tokens", help="ERC-20 balances with metadata")
    p.add_argument("--chain", required=True)
    p.add_argument("--addr", required=True)
    p.add_argument("--cap", type=int, default=100)
    p.add_argument("--include-dust", action="store_true")
    p.set_defaults(func=cmd_tokens)

    p = sub.add_parser("price", help="current or historical token prices")
    p.add_argument("--symbol", default="ETH,BNB,HYPE,USDC,SOL")
    p.add_argument("--token", default=None, help="chain:address for DexScreener")
    p.add_argument("--at", default=None, help="ISO time for historical price")
    p.set_defaults(func=cmd_price)

    p = sub.add_parser("screen", help="flag spam / address poisoning")
    p.add_argument("--chain", required=True)
    p.add_argument("--addr", required=True)
    p.add_argument("--ref", default=None, help="name=address,... known real addresses")
    p.add_argument("--cap", type=int, default=2000)
    p.add_argument("--no-dex", action="store_true")
    p.set_defaults(func=cmd_screen)

    p = sub.add_parser("bridge",
                       help="resolve a bridge tx to its destination chain/recipient")
    p.add_argument("--tx", required=True, help="origin-chain tx hash")
    p.set_defaults(func=cmd_bridge)

    p = sub.add_parser("sol", help="Solana queries")
    p.add_argument("what",
                   choices=["balance", "sigs", "tx", "transfers", "flow", "parsed"])
    p.add_argument("--addr", default=None)
    p.add_argument("--sig", default=None)
    p.add_argument("--dir", default="from", choices=["from", "to"])
    p.add_argument("--cap", type=int, default=2000)
    p.add_argument("--include-dust", action="store_true")
    p.set_defaults(func=cmd_sol)

    return parser


def main(argv: list[str] | None = None) -> int:
    # Load `.env` before anything reads a key; real env vars win.
    env.load()
    args = build_parser().parse_args(argv)
    try:
        payload = args.func(args)
    except KeyboardInterrupt:
        payload = {"_error": "interrupted", "type": "KeyboardInterrupt"}
    except (RpcError, SolanaError) as exc:
        payload = {"_error": http.redact(exc), "type": type(exc).__name__,
                   "hint": "all endpoints failed; retry, or pass --no-alchemy "
                           "to use public RPCs"}
    except KeyError as exc:
        # chains.resolve already produces a full message; unwrap its quotes.
        payload = {"_error": http.redact(exc.args[0] if exc.args else exc),
                   "type": "KeyError"}
    except Exception as exc:  # noqa: BLE001 - the whole point is to never traceback
        payload = {"_error": http.redact(exc), "type": type(exc).__name__,
                   "hint": "run with the relevant API key set (ALCHEMY_KEY / "
                           "ETHERSCAN_KEY / HELIUS_KEY) or add --no-alchemy"}
    _emit(payload)
    return 0 if "_error" not in payload and "_rpc_error" not in payload else 1


if __name__ == "__main__":
    sys.exit(main())
