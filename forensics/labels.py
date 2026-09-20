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
}


def lookup(address: str) -> dict | None:
    """The label for an address, checking the shared KB then every case."""
    key = addr.normalize(address)
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
