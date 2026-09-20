# API guide

Which provider to use for what, and what the free tiers actually allow.
Researched September 2026 against live provider docs. Limits and prices change,
so re-check before paying for anything.

## The stack

Cheapest option that works, in the order to reach for them.

| Layer | Provider | Free tier | Key | Use for |
|---|---|---|---|---|
| Verification | Public JSON-RPC (PublicNode, LlamaRPC, Ankr, chain-native) | Free forever | No | `eth_getTransactionByHash/Receipt/Balance/Code`, Solana `getBalance/getSignaturesForAddress/getTransaction` |
| EVM history + labels | Etherscan V2 (`api.etherscan.io/v2/api?chainid=`) | 3 calls/s, 100k/day. BNB is paid-only; Robinhood (4663) and Arc (5042) free until Oct 15 2026 | Yes | `txlist`, `tokentx`, `tokennfttx`, contract source |
| EVM + Solana transfers | Alchemy (Transfers/Token/Prices APIs) | 30M CU/month, 25 rps | Yes | `alchemy_getAssetTransfers` (full history in one call), token balances, prices |
| Solana depth | Helius (parsed txs, DAS, webhooks) | 1M credits/month, 10 rps | Yes | parsed Solana drains, token accounts, stake/freeze state |
| Meme-token prices | DexScreener (`api.dexscreener.com`) | ~60 req/min | No | long-tail tokens CoinGecko does not cover |
| BNB history | BscScan legacy API | Free tier | Yes | BNB `txlist`/`tokentx` without paying for V2 |

## Is Alchemy the best choice?

For one key covering EVM and Solana with the largest free tier, yes: 30M CU/month
against Helius's 1M and Etherscan's 100k calls/day rate-capped.

It does not win everywhere:

- Explorer-verified history on new chains goes to Etherscan V2, which has native
  labels and source code. Free for 999, 4663 and 5042 right now.
- Solana parsing goes to Helius. Alchemy's own docs defer on Solana depth.
- Meme-token prices go to DexScreener, which needs no key and covers day-old
  pools.
- Keyless proof goes to public RPCs, which need no signup and are not
  rate-limited at this volume.

So: Alchemy primary, Etherscan V2 as cross-check, Helius for Solana, DexScreener
for prices, public RPC as fallback. That is what `providers.py` implements.

## Commands

One subcommand is one query and prints verbose JSON. The agent reads the logs and
reasons; nothing prints a verdict.

| Command | What it hands back |
|---|---|
| `transfers --chain --addr --dir` | raw history, dropping the `internal` category on chains that 400 on it (BNB, HyperEVM, Robinhood) |
| `tx --chain --hash` | signer, function/args, receipt, decoded Transfer/Approval logs |
| `approvals --owner` | Approval logs plus the tx sender of each (the permit fingerprint); chunk with `--from-block/--to-block` |
| `balances --addr` | native balance, nonce, code, 7702 delegate, one chain or all |
| `tokens --addr` | ERC-20 balances and metadata |
| `price` | Alchemy by symbol, or DexScreener `--token chain:addr` for long-tail |
| `flow --addr` | one-hop outbound; the agent chains the rest |
| `screen --addr --ref name=0xREAL` | annotate spam and poisoning: homoglyph symbols, no-DEX-pair tokens, mirror amounts, vanity lookalike addresses. Returns `clean` and `suspected_spam`; the agent decides |
| `bridge --tx` | resolve a bridge origin tx to its destination chain, recipient and payout tx, via the bridge's own intent API (Relay implemented). Returns `found:false` rather than guessing when the hash is not a known bridge request |
| `sol balance\|sigs\|tx\|transfers\|flow\|parsed` | Solana via public RPC, or Helius parsed with `HELIUS_KEY`. `transfers`/`flow` paginate Helius for full history; without a key they fall back to keyless `jsonParsed` scanning, which is capped and slower |

`tx`, `transfers` and `flow` include `from_label`/`to_label` from `labels.py`, a
known-address KB of bridges, DEX routers, CEX, launchers and treasuries. Add
verified entries as you identify them.

Errors come back as JSON (`{"_rpc_error": ...}`), never tracebacks, so the agent
can adapt. An ETH `eth_getLogs` call that 400s on a full range, for example, can
be retried with the range split.

## Free-tier gotchas

- Public Solana RPCs are **not archive nodes**: `getTransaction` returns
  `null` for transactions older than the node's retention window (observed on
  a 15-month-old tx). Use Helius for historical transaction detail.
- Alchemy's free tier caps `eth_getLogs` to a 10-block range. Full-history log
  scans are not possible on the free key; chunk to 10 blocks or use Etherscan V2.
- Non-ETH chains reject the `internal` transfer category (BNB, HyperEVM and
  Robinhood return 400). `transfers` and `flow` retry with four categories.
- BNB public RPCs block archive `eth_getLogs` with `limit exceeded` or an archive
  token requirement. Use Alchemy for BNB history.

## Spam and address poisoning

Drainers flood the victim's history with fake lookalike tokens (homoglyph symbols
like `E឴឴ꓔH`, `BṆB`, `UЅDТ`) sent to vanity addresses that mimic the collector,
usually sharing a suffix like `…42ee`. Counting these inflates the total and
mis-attributes hops. `spam.py` and `kit.py screen` flag them:

- `non_ascii_symbol` / `homoglyphs:` - the symbol is not plain ASCII
- `no_dex_pair` / `no_code` - the token has no market or no contract
- `mirror_amount` - an ERC-20 amount equals a native amount in the same window
- `lookalike_of:` / `vanity_suffix:` - the address shares a long prefix or suffix
  with a known real address

A real asset is the native coin, or a token with a live DEX pair. Verify
everything else before counting it.

## Ruled out for the free tier

- Moralis: no free tier any more. Starter is $149/month.
- QuickNode: free trial only, one month, then $49+/month.

## Chain details

- HyperEVM (999): native is HYPE, never ETH. Around $90 in September 2026, so an
  8.769-native transaction is roughly $800, not $21,860.
- Arc mainnet is 5042 (`rpc.mainnet.arc.io`, explorer `explorer.arc.io`). 5042002
  is the testnet and shows zero balances for mainnet victims.
- Arc gas is USDC with 18 decimals on mainnet.
- Robinhood Chain (4663) gas is ETH (Arbitrum Orbit), so the ETH label is correct
  there.
- Solana is non-EVM: base58 addresses, 9-decimal lamports, Associated Token
  Accounts. Use `solana.py`, not the EVM path.
