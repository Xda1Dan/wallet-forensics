"""Tests for forensics.env, the dependency-free .env loader."""
import os

from forensics import env


def test_parse_ignores_blanks_and_comments():
    text = """
    # a comment
    ALCHEMY_KEY=abc123

    ETHERSCAN_KEY = def456
    """
    assert env.parse(text) == {"ALCHEMY_KEY": "abc123", "ETHERSCAN_KEY": "def456"}


def test_parse_strips_quotes_and_export_prefix():
    text = 'export ALCHEMY_KEY="quoted-key"\nHELIUS_KEY=\'single\''
    assert env.parse(text) == {"ALCHEMY_KEY": "quoted-key", "HELIUS_KEY": "single"}


def test_parse_keeps_equals_signs_in_value():
    assert env.parse("K=a=b=c") == {"K": "a=b=c"}


def test_load_sets_missing_vars(tmp_path, monkeypatch):
    monkeypatch.delenv("ALCHEMY_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text("ALCHEMY_KEY=from-file\n")
    env.load(path)
    assert os.environ["ALCHEMY_KEY"] == "from-file"


def test_load_does_not_clobber_real_environment(tmp_path, monkeypatch):
    """An explicit export must always win over a stale .env file."""
    monkeypatch.setenv("ALCHEMY_KEY", "from-shell")
    path = tmp_path / ".env"
    path.write_text("ALCHEMY_KEY=from-file\n")
    env.load(path)
    assert os.environ["ALCHEMY_KEY"] == "from-shell"


def test_load_missing_file_is_not_an_error(tmp_path):
    assert env.load(tmp_path / "nope.env") == {}


def test_load_skips_empty_values(tmp_path, monkeypatch):
    monkeypatch.delenv("ALCHEMY_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text("ALCHEMY_KEY=\n")
    env.load(path)
    assert "ALCHEMY_KEY" not in os.environ


def test_known_keys_are_the_documented_ones():
    assert set(env.KNOWN_KEYS) == {"ALCHEMY_KEY", "ETHERSCAN_KEY", "HELIUS_KEY"}
