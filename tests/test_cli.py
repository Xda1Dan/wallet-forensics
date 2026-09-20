"""Tests for forensics.cli: the error envelope and command wiring."""
import json

import pytest

from forensics import cli


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """Keep these tests hermetic.

    ``cli.main`` calls ``env.load()``, so a developer's real ``.env`` would leak
    a key into a test that deliberately clears one. Neutralise the file lookup
    and start from a clean environment.
    """
    monkeypatch.setattr(cli.env, "find", lambda: None)
    for name in ("ALCHEMY_KEY", "ETHERSCAN_KEY", "HELIUS_KEY"):
        monkeypatch.delenv(name, raising=False)


def run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_main_returns_json_on_missing_alchemy_key(capsys, monkeypatch):
    """The headline promise: no traceback, ever, even with no keys set."""
    monkeypatch.delenv("ALCHEMY_KEY", raising=False)
    code, payload = run(["transfers", "--chain", "eth", "--addr", "0x" + "1" * 40],
                        capsys)
    assert code == 1
    assert payload["_error"] == "ALCHEMY_KEY is not set"
    assert payload["type"] == "RuntimeError"


def test_main_returns_json_on_unknown_chain(capsys):
    code, payload = run(["balances", "--addr", "0x" + "1" * 40, "--chains", "nope"],
                        capsys)
    assert code == 1
    assert payload["_error"].startswith("unknown chain 'nope'")
    assert payload["type"] == "KeyError"


def test_main_redacts_keys_in_errors(capsys, monkeypatch):
    monkeypatch.setenv("ALCHEMY_KEY", "supersecretkey12345")

    def boom(*_args, **_kwargs):
        raise RuntimeError("POST https://eth-mainnet.g.alchemy.com/v2/supersecretkey12345 failed")

    monkeypatch.setattr(cli, "_alchemy", boom)
    _, payload = run(["price", "--symbol", "ETH"], capsys)
    assert "supersecretkey12345" not in json.dumps(payload)
    assert "***" in payload["_error"]


def test_main_redacts_keys_in_rpc_errors(capsys, monkeypatch):
    from forensics.evm import RpcError
    monkeypatch.setenv("ALCHEMY_KEY", "supersecretkey12345")

    def boom(*_args, **_kwargs):
        raise RpcError("all endpoints failed: https://eth-mainnet.g.alchemy.com/v2/supersecretkey12345")

    monkeypatch.setattr(cli, "_rpc", boom)
    code, payload = run(["tx", "--chain", "eth", "--hash", "0xdead"], capsys)
    assert code == 1
    assert "supersecretkey12345" not in json.dumps(payload)
    assert payload["type"] == "RpcError"


def test_success_exit_code_is_zero(capsys, monkeypatch):
    monkeypatch.setattr(cli, "cmd_price", lambda args: {"source": "test", "prices": {}})
    parser = cli.build_parser()
    args = parser.parse_args(["price"])
    code = 0 if "_error" not in cli.cmd_price(args) else 1
    assert code == 0


def test_main_reads_key_from_dotenv(capsys, monkeypatch, tmp_path):
    """A `.env` supplies keys to the CLI when no real env var is set."""
    dotenv = tmp_path / ".env"
    dotenv.write_text("ALCHEMY_KEY=alch_fromdotenv\n")
    # Point the loader at our file (supersedes the hermetic stub) and make sure
    # no real key is present, so the file is the only possible source.
    monkeypatch.setattr(cli.env, "find", lambda: dotenv)
    for name in ("ALCHEMY_KEY", "ETHERSCAN_KEY", "HELIUS_KEY"):
        monkeypatch.delenv(name, raising=False)

    captured = {}

    def fake_alchemy():
        captured["key"] = cli.os.environ.get("ALCHEMY_KEY")
        return type("A", (), {"last_error": None,
                              "transfers": lambda *a, **k: []})()

    monkeypatch.setattr(cli, "_alchemy", fake_alchemy)
    cli.main(["transfers", "--chain", "eth", "--addr", "0x" + "1" * 40])
    capsys.readouterr()
    assert captured["key"] == "alch_fromdotenv"


def test_decode_call_recognises_known_selectors():
    assert cli._decode_call("0x") == {"fn": "plain_send", "selector": None}
    assert cli._decode_call("0x0")["fn"] == "plain_send"
    decoded = cli._decode_call("0xa9059cbb" + "0" * 64)
    assert decoded["fn"] == "transfer(address,uint256)"
    assert decoded["selector"] == "0xa9059cbb"
    assert cli._decode_call("0xdeadbeef")["fn"] == "unknown_0xdeadbeef"


def test_parse_references():
    assert cli._parse_references(None) == {}
    assert cli._parse_references("collector=0xabc,treasury=0xdef") == {
        "collector": "0xabc", "treasury": "0xdef"}
    assert cli._parse_references("garbage") == {}


def test_dedupe_transfers_removes_repeats():
    row = {"hash": "0x1", "category": "external", "from": "0xa", "to": "0xb",
           "value": 1.0, "rawContract": {"address": "0x0"}}
    assert len(cli._dedupe_transfers([row, dict(row)])) == 1
    other = dict(row, hash="0x2")
    assert len(cli._dedupe_transfers([row, other])) == 2
