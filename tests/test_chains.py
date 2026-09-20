"""Tests for forensics.chains and forensics.labels."""
import pytest

from forensics import chains, labels


def test_resolve_aliases():
    assert chains.resolve("Ethereum") == "eth"
    assert chains.resolve("HyperEVM") == "hyper"
    assert chains.resolve("rob") == "robinhood"
    assert chains.resolve("solana") == "sol"
    assert chains.resolve("  eth  ") == "eth"


def test_resolve_rejects_unknown_chain():
    with pytest.raises(KeyError):
        chains.resolve("nope")


def test_facts_that_matter():
    """The two chain facts that keep getting mis-priced."""
    assert chains.info("hyper")["native_symbol"] == "HYPE"
    assert chains.info("arc")["chain_id"] == 5042
    assert chains.info("robinhood")["native_symbol"] == "ETH"


def test_every_chain_has_required_fields():
    for key, chain in chains.CHAINS.items():
        for field in ("name", "native_symbol", "native_decimals", "rpcs", "explorer"):
            assert chain[field], f"{key} missing {field}"
        assert isinstance(chain["rpcs"], list) and chain["rpcs"]


def test_evm_chains_excludes_solana():
    assert "sol" not in chains.EVM_CHAINS
    assert set(chains.EVM_CHAINS) <= set(chains.CHAINS)


def test_labels_shared_and_case_tiers():
    assert labels.lookup("0x4cd00e387622c35bddb9b4c962c136462338bc31")["kind"] == "bridge"
    # Case-specific addresses live outside the shared KB but still resolve.
    case_addr = "0xe0340cd1bb55e008258c4cdbc94ed412a3f58838"
    assert case_addr not in labels.LABELS
    assert labels.lookup(case_addr) is not None
    assert "case d23729fc" in labels.annotate(case_addr)


def test_labels_unknown_address():
    assert labels.lookup("0x" + "1" * 40) is None
    assert labels.annotate("0x" + "1" * 40) is None
    assert labels.annotate(None) is None
