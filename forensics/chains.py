"""Chain registry: ids, public RPCs, native assets, explorer slugs."""
from __future__ import annotations

# Alchemy network slugs, used to build per-chain JSON-RPC endpoints.
ALCHEMY_SLUGS = {
    "eth": "eth-mainnet",
    "bnb": "bnb-mainnet",
    "hyper": "hyperliquid-mainnet",
    "robinhood": "robinhood-mainnet",
    "arc": "arc-mainnet",
}

# DexScreener chain slugs, for long-tail token prices.
DEXSCREENER_SLUGS = {
    "eth": "ethereum",
    "bnb": "bsc",
    "hyper": "hyperliquid",
    "robinhood": "robinhood",
    "arc": "arc",
    "sol": "solana",
}

CHAINS = {
    "eth": {
        "name": "Ethereum",
        "chain_id": 1,
        "native_symbol": "ETH",
        "native_decimals": 18,
        "rpcs": [
            "https://ethereum-rpc.publicnode.com",
            "https://eth.llamarpc.com",
        ],
        "explorer": "https://etherscan.io",
        "etherscan_v2_id": 1,
    },
    "bnb": {
        "name": "BNB Chain",
        "chain_id": 56,
        "native_symbol": "BNB",
        "native_decimals": 18,
        "rpcs": [
            "https://bsc-dataseed.binance.org",
            "https://bsc-rpc.publicnode.com",
        ],
        "explorer": "https://bscscan.com",
        # Paid-tier only on Etherscan V2; use Alchemy for BNB history.
        "etherscan_v2_id": 56,
    },
    "hyper": {
        "name": "HyperEVM (Hyperliquid)",
        "chain_id": 999,
        # HyperEVM's native coin is HYPE, not ETH. Pricing it as ETH
        # overstates value by roughly 28x.
        "native_symbol": "HYPE",
        "native_decimals": 18,
        "rpcs": [
            "https://rpc.hyperliquid.xyz/evm",
            "https://hyperevm.rpc.sentio.xyz",
        ],
        "explorer": "https://hyperevmscan.io",
        "etherscan_v2_id": 999,
    },
    "robinhood": {
        "name": "Robinhood Chain",
        "chain_id": 4663,
        # Arbitrum Orbit L2; gas is ETH.
        "native_symbol": "ETH",
        "native_decimals": 18,
        "rpcs": [
            "https://rpc.mainnet.chain.robinhood.com",
            "https://robinhood-rpc.publicnode.com",
        ],
        "explorer": "https://robinscan.io",
        "etherscan_v2_id": 4663,
    },
    "arc": {
        "name": "Arc (Circle L1)",
        "chain_id": 5042,  # 5042002 is the *testnet*, not mainnet.
        "native_symbol": "USDC",  # USDC is the native gas asset on Arc.
        "native_decimals": 18,
        "rpcs": ["https://rpc.mainnet.arc.io"],
        "explorer": "https://explorer.arc.io",
        "etherscan_v2_id": 5042,
    },
    "sol": {
        "name": "Solana",
        "chain_id": None,
        "native_symbol": "SOL",
        "native_decimals": 9,
        "rpcs": [
            "https://api.mainnet-beta.solana.com",
            "https://solana-rpc.publicnode.com",
        ],
        "explorer": "https://solscan.io",
        "etherscan_v2_id": None,
    },
}

ALIASES = {
    "ethereum": "eth",
    "bsc": "bnb",
    "bnb_chain": "bnb",
    "hyperliquid": "hyper",
    "hyperevm": "hyper",
    "hyper_evm": "hyper",
    "robinhood_chain": "robinhood",
    "rob": "robinhood",
    "circle": "arc",
    "solana": "sol",
}

EVM_CHAINS = tuple(k for k, c in CHAINS.items() if c["chain_id"] is not None)


def resolve(name: str) -> str:
    """Normalise a user-supplied chain name to a canonical key."""
    key = ALIASES.get(name.strip().lower(), name.strip().lower())
    if key not in CHAINS:
        raise KeyError(f"unknown chain {name!r}; known: {sorted(CHAINS)}")
    return key


def info(chain: str) -> dict:
    return CHAINS[resolve(chain)]
