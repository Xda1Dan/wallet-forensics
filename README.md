# wallet-forensics

Query tools for tracing how a crypto wallet was drained and where the funds
went, across EVM chains and Solana.

It is built to be driven by an agent. Every command runs one query and prints
verbose JSON. Nothing prints a verdict: the caller reads the output, chains the
commands, and reasons about the drain. The tools shorten the work, they do not
replace it.

```
victim address + drainer address (+ when it happened)
        |
        v
  verify each tx  ->  classify the mechanism  ->  follow the funds
```

## Install

Python 3.10+. One dependency:

```bash
pip install requests
```

API keys are optional. The tools fall back to public RPCs without them.

| Variable | Unlocks | Free tier |
|---|---|---|
| `ALCHEMY_KEY` | full transfer history, token balances, prices | 30M CU/month |
| `HELIUS_KEY` | parsed Solana transactions | 1M credits/month |
| `ETHERSCAN_KEY` | explorer-verified history and labels | 100k calls/day |

Single-tx reads, balances, code checks and basic Solana work with no key at all.

## Keys

```bash
cp .env.example .env
```

Fill in what you have. `.env` is gitignored and loaded at startup. A real
environment variable wins over the file, so `ALCHEMY_KEY=... python3 kit.py ...`
overrides it, which is what you want in CI.

Never commit `.env`. Keys travel inside request URLs, and while errors are
redacted (`http.redact`), a key that reaches a file or a log should be rotated.

## Usage

```bash
export ALCHEMY_KEY=...

# verify a transaction and see what it actually was
python3 kit.py tx --chain hyper --hash 0x559722745acccbbbefd4d32b7de99a7a84785dc49b66fddfad2e73fc6cc7d419

# pull an address's full transfer history
python3 kit.py transfers --chain eth --addr 0xVICTIM

# follow the money (one hop; call again for the next)
python3 kit.py flow --chain arc --addr 0xDRAINER

# flag spam a drainer planted in the history
python3 kit.py screen --chain eth --addr 0xVICTIM --ref collector=0xREAL

# price assets, current or at the moment of the drain
python3 kit.py price --symbol ETH,BNB,HYPE
python3 kit.py price --symbol ETH --at 2026-09-19T03:00:00Z
```

`python3 kit.py --help` lists every command.

## Commands

| Command | Returns |
|---|---|
| `tx` | one transaction, decoded: signer, function/selector, receipt, logs, labels |
| `transfers` | full transfer history for an address (dust excluded by default) |
| `flow` | outbound transfers from any address, one hop |
| `approvals` | Approval/ApprovalForAll logs for an owner, plus a permit fingerprint |
| `balances` | native balance, nonce, code and EIP-7702 delegation per chain |
| `tokens` | ERC-20 balances with symbol/decimals metadata |
| `price` | current or historical USD prices |
| `screen` | annotate spam / address poisoning |
| `sol` | Solana: `balance`, `sigs`, `tx`, `parsed` |

## How a drain is classified

The decisive question is who signed the transaction that moved the asset.

- A plain value send (`input: 0x`, 21,000 gas) signed by the victim means the
  attacker held the key.
- A direct `transfer()` signed by the victim means the same.
- An outflow signed by someone other than the victim points to an approval or
  permit being redeemed, and the attacker never needed the key.

`tx` gives you the raw material for that call. It does not make it.

## Notes that matter

- HyperEVM's native coin is HYPE, not ETH. Pricing it as ETH overstates value by
  roughly 28x. The chain registry encodes this.
- Arc mainnet is chain 5042, not 5042002. The latter is the testnet.
- Drainers plant lookalike spam. Fake tokens with homoglyph symbols (`E឴឴ꓔH`) go
  to vanity addresses that mimic the real collector. Counting them inflates the
  haul; `screen` flags them.
- Alchemy's free tier caps `eth_getLogs` to 10-block ranges. Wide log scans need
  Etherscan or a paid plan.

## Errors are data

Every command exits with JSON, never a traceback, including a missing key, an
unknown chain, or every endpoint for a chain being down. Failures come back in
one of two shapes:

| Shape | Meaning |
|---|---|
| `{"_error": ..., "type": ...}` | the command could not run (bad input, missing key, all endpoints failed) |
| `{"_rpc_error": ..., "method": ...}` | one call inside a larger query failed; the rest of the result is still valid |

Exit code is 0 on success and 1 when either marker is present, so a shell
pipeline can branch without parsing. Keys ride inside request URLs, so every
error message passes through `http.redact()` before it is emitted.

## Development

```bash
pip install -e ".[dev]"   # or: pip install -r requirements.txt && pip install pytest
python3 -m pytest
```

The suite covers the pure logic (numeric parsing, address similarity, spam
flagging, key redaction) and the CLI's error envelope. It needs no network and
no keys.

## Layout

```
forensics/
  chains.py     chain registry: ids, RPCs, native assets
  http.py       pooled session, retry/backoff, key redaction
  env.py        .env loader (real env vars win)
  evm.py        EVM reads: public RPC and Alchemy
  solana.py     Solana reads: public RPC and Helius
  providers.py  Etherscan and DexScreener
  abi.py        selectors and event topics
  units.py      numeric parsing and scaling
  address.py    addresses, EIP-7702, lookalike similarity
  labels.py     known-address knowledge base (shared + per-case tiers)
  spam.py       spam / poisoning detection
  cli.py        the `kit` command line
kit.py          entry point
tests/          offline test suite
```

## Contributing

Add verified addresses to `forensics/labels.py` as you identify them; a labelled
address saves every future investigation from re-deriving it. Keep reusable
infrastructure in `LABELS` and anything that only means something inside one case
in `CASE_LABELS[<case id>]`, so the shared list stays generic. New commands stay
single-purpose: one query, verbose JSON, errors as data.

## License

MIT. See [LICENSE](LICENSE).

You can use, modify, and redistribute this code, including commercially, as
long as the copyright notice stays with it. It comes with no warranty: the
output is raw evidence, not legal advice or a definitive finding.
