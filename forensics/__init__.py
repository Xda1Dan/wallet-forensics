"""wallet-forensics: tracing crypto wallet drains across chains.

    chains     static chain registry (ids, RPCs, native assets)
    http       one pooled HTTP session with retry/backoff + key redaction
    env        dependency-free `.env` loader (real env vars win)
    evm        EVM data access (keyless public RPC + Alchemy)
    solana     Solana data access (keyless public RPC + Helius)
    providers  third-party REST (Etherscan, Alchemy Prices, DexScreener)
    abi        the handful of selectors/events that matter here
    units      numeric parsing/formatting
    address    address parsing, EIP-7702, lookalike similarity
    labels     known-address knowledge base
    spam       spam / address-poisoning detection
    cli        the `kit` command line
"""

__version__ = "0.1.0"
