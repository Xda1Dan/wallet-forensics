"""Selectors and event topics used for decoding.

Kept in one place so a result is compared against a named constant rather than a
bare hex literal. Values are keccak-256 hashes of the signatures alongside them.
"""
from __future__ import annotations

# --- function selectors (first 4 bytes of calldata) -----------------------
SELECTORS = {
    "0x095ea7b3": "approve(address,uint256)",
    "0xa22cb465": "setApprovalForAll(address,bool)",
    "0xa9059cbb": "transfer(address,uint256)",
    "0x23b872dd": "transferFrom(address,address,uint256)",
    "0xd505accf": "permit(address,address,uint256,uint256,uint8,bytes32,bytes32)",
    "0xac9650d8": "multicall(bytes[])",
    # Relay bridge (relay.link)
    "0x49290c1c": "depositNative(address,bytes32)",
    "0xe8017952": "depositErc20(address,address,uint256,bytes32)",
    # Routers commonly seen in trading-bot activity
    "0x38ed1739": "swapExactTokensForTokens(...)",
    "0x7ff36ab5": "swapExactETHForTokens(...)",
    "0x18cbafe5": "swapExactTokensForETH(...)",
    "0x414bf389": "exactInputSingle(...)",
    "0xc04b8d59": "exactInput(...)",
    "0x3593564c": "0xRouter.execute(...)",
}

# --- event topics ---------------------------------------------------------
TOPIC_TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TOPIC_APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
TOPIC_APPROVAL_FOR_ALL = "0x17307eab39ab6107e8899845ad3d59bd9653f200f220920489ca2b5937696c31"

EVENTS = {
    TOPIC_TRANSFER: "Transfer",
    TOPIC_APPROVAL: "Approval",
    TOPIC_APPROVAL_FOR_ALL: "ApprovalForAll",
}

# Transfer categories, and the reduced set for chains that reject `internal`.
TRANSFER_CATEGORIES = ("external", "internal", "erc20", "erc721", "erc1155")
CATEGORIES_WITHOUT_INTERNAL = tuple(c for c in TRANSFER_CATEGORIES if c != "internal")

# Selectors that indicate an on-chain permission grant rather than a send.
PERMISSION_SELECTORS = frozenset({"0x095ea7b3", "0xa22cb465", "0xd505accf"})
