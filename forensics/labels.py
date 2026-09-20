"""Known-address knowledge base.

``LABELS`` holds reusable infrastructure (bridges, DEX routers, CEX, launchers,
known spam tokens). ``CASE_LABELS`` holds addresses that only mean something
inside one case, keyed by case id, so the shared list stays generic.

Kinds: bridge, dex_router, cex, launcher, router_bot, treasury, spam_token.
"""
from __future__ import annotations

from . import address as addr

LABELS: dict[str, dict] = {
    # --- bridges ---------------------------------------------------------
    "0x4cd00e387622c35bddb9b4c962c136462338bc31": {
        "name": "Relay: Depository",
        "kind": "bridge",
        "chains": ["eth", "bnb", "hyper", "robinhood", "arc"],
        "source": "Etherscan public tag (relay.link/bridge); code verified on all 5 chains",
        "note": "Deposit side of the Relay cross-chain bridge. "
                "depositNative(address,bytes32)=0x49290c1c, "
                "depositErc20(address,address,uint256,bytes32)=0xe8017952, "
                "event RelayNativeDeposit(address,uint256,bytes32). "
                "Owner EOA 0xf61a305199fa1135d76ffab3752d42f55cbd775a.",
    },
    # --- DEX routers -----------------------------------------------------
    "0x28b1dc1a5e3699a428bc51d234dfab7c9cb2a183": {
        "name": "OKX DEX Router", "kind": "dex_router", "chains": ["eth"],
        "source": "collector outbound activity",
        "note": "Collector sent 4.865 ETH here: swap/bridge hop toward an exchange.",
    },
    # --- trading-bot routers seen in victim activity ---------------------
    "0x671089cee2ae3bad03fdd33b2450543e1f914e6e": {
        "name": "Hook-AMM router bot A", "kind": "router_bot", "chains": ["eth"],
        "source": "victim activity; selector 0xeffbec13",
    },
    "0xa840d6d0a8490568deb99b9b64efe33a23bab995": {
        "name": "Hook-AMM router bot B", "kind": "router_bot", "chains": ["eth"],
        "source": "victim activity; identical 11 KB router",
    },
    "0x000000000004444c5dc75cb358380d2e3de08a90": {
        "name": "Token launcher (vanity)", "kind": "launcher", "chains": ["eth"],
        "source": "56 victim transfers; minted BLUECHIP",
    },
    # --- spam / poisoning (reusable homoglyph tokens) --------------------
    "0x5605200744ab25ed9e510e40c047f531fce3ded7": {
        "name": "Fake 'E឴឴ꓔH' token (homoglyph spam)", "kind": "spam_token",
        "chains": ["eth"], "source": "poisoned into victim, 2026-09-19/20",
    },
    # --- Relay solver (shared across cases) ------------------------------
    "0xf70da97812cb96acdf810712aa562db8dfa3dbef": {
        "name": "Relay: solver payout EOA", "kind": "bridge",
        "chains": ["robinhood", "eth"],
        "source": "pays Relay bridge destinations on Robinhood Chain; seen in "
                  "case d23729fc and case sol_5gNX",
        "note": "Not the attacker: this is the solver that fronts destination-"
                "chain funds. The recipient it pays is the attacker.",
    },
    # --- Relay on Solana (shared: reusable bridge infrastructure) ---------
    "99vQwtBwYtrqqD9YSXbdum3KBdxPAVxYTaQ3cfnJSrN2": {
        "name": "Relay: Solana depository program", "kind": "bridge",
        "chains": ["sol"],
        "source": "Relay /chains API depository; Anchor program",
        "note": "DepositNative / DepositToken entry point. A drain that calls "
                "this is bridging out, not transferring.",
    },
    "7uTT8Xi5RWXzy7h9XL244GRgEycDYDhLjr3ZyNdXi8pZ": {
        "name": "Relay: Solana depository vault", "kind": "bridge",
        "chains": ["sol"],
        "source": "Relay /chains API depositoryVault; bridge-out endpoint",
        "note": "Explorer label is 'Relay' and is correct. Receives "
                "DepositNative deposits; NOT a drainer wallet.",
    },
}

# Addresses meaningful only within one case. Kept out of ``LABELS`` so the
# shared KB stays reusable; ``lookup``/``annotate`` consult both.
CASE_LABELS: dict[str, dict[str, dict]] = {
    "d23729fc": {
        "0xe0340cd1bb55e008258c4cdbc94ed412a3f58838": {
            "name": "Scam treasury (case d23729fc)", "kind": "treasury",
            "chains": ["eth"],
            "source": "collector 0x7588..f42ee outbound; receives real ETH/USDT",
        },
        "0xf206892a9b9374f3800c3d175a6d9be01fa23621": {
            "name": "Scam cluster wallet (case d23729fc)", "kind": "treasury",
            "chains": ["eth"],
            "source": "collector outbound",
        },
    },
    "sol_5gNX": {
        "FncazAs6omJJjtLVzquzT9KoyXn6tFixr9kGjr42ktLj": {
            "name": "Drainer gas funder (case sol_5gNX)", "kind": "treasury",
            "chains": ["sol"],
            "source": "funded victim gas 2026-09-14 and co-signed the USDC "
                      "account close; 1k txs in 18 min on 2026-09-20",
        },
        "4J9qDfRrSfKCxcVEznQEezrg1VBJqzUb5cbaXRttEqfj": {
            "name": "Drainer pass-through (case sol_5gNX)", "kind": "treasury",
            "chains": ["sol"],
            "source": "received first 0.5 SOL sweep; forwards to "
                      "HgxSAFzFGpTnN7a9fWjCxtNc4aiy7zhyfDsstwU5ETfk",
        },
        "HgxSAFzFGpTnN7a9fWjCxtNc4aiy7zhyfDsstwU5ETfk": {
            "name": "Drainer consolidator (case sol_5gNX)", "kind": "treasury",
            "chains": ["sol"],
            "source": "0.5 SOL leg; forwards to DTAVTDQ3XxGpyLPdkH1xiRiBm2yqvsufbnm2Qzndb8dY",
        },
        "DTAVTDQ3XxGpyLPdkH1xiRiBm2yqvsufbnm2Qzndb8dY": {
            "name": "Drainer high-volume sink (case sol_5gNX)", "kind": "treasury",
            "chains": ["sol"],
            "source": "1k+ txs since 2026-09-19; receives from consolidator",
        },
        "AGRRCDVRn51mhzkPcZy9zscaSdseFhhJw8CTLh3aiTDY": {
            "name": "Address-poisoning duster (case sol_5gNX)", "kind": "treasury",
            "chains": ["sol"],
            "source": "1-lamport dust to victim + ~18 others, 2026-09-14",
        },
        "G9KqnfuyDw7Pm5j5h6diV1LM8JDjn8hE6f7eT9AzqhuT": {
            "name": "Fake USDC spam token (case sol_5gNX)", "kind": "spam_token",
            "chains": ["sol"],
            "source": "1.005427 sent to victim right after the drain",
        },
        "0x243f8FbC2b6CB5924b37Afbebab0de95C9249E74": {
            "name": "Bridge recipient / attacker (case sol_5gNX)", "kind": "treasury",
            "chains": ["robinhood"],
            "source": "Relay destination recipient for the 14.104650422 SOL "
                      "bridge; spends 6x0.05 ETH into FDT contract "
                      "0xe72334a0…; not linked to victim",
        },
        "0xe72334a03015466aa12ed430a55177beb87b66a6": {
            "name": "FDT contract (case sol_5gNX)", "kind": "treasury",
            "chains": ["robinhood"],
            "source": "Robinhood-chain contract the bridge recipient buys FDT "
                      "from; token 0xbd22784169572a2059bde07f5f4500011b519472",
        },
    },
}


def lookup(address: str) -> dict | None:
    """The label for an address, checking the shared KB then every case.

    EVM addresses are hex and case-insensitive, so they are lower-cased before
    lookup. Solana addresses are base58 and case-sensitive, so they are matched
    exactly; lower-casing them would corrupt the key (``7uTT…`` vs ``7utt…``).
    """
    raw = address or ""
    keys = {raw} if not raw.lower().startswith("0x") else {addr.normalize(raw)}
    for key in keys:
        entry = LABELS.get(key)
        if entry is not None:
            return entry
        for case in CASE_LABELS.values():
            if key in case:
                return case[key]
    return None


def annotate(address: str) -> str | None:
    """Human-readable tag for an address, or ``None`` when unknown."""
    entry = lookup(address)
    return f"{entry['name']} [{entry['kind']}]" if entry else None
