"""Minimal ``.env`` loader.

Parses the handful of lines a ``.env`` contains rather than adding python-dotenv
as a dependency. A real environment variable always wins over the file, so an
explicit export overrides a stale ``.env``.
"""
from __future__ import annotations

import os
from pathlib import Path

# The keys this package understands, in the order the README documents them.
KNOWN_KEYS = ("ALCHEMY_KEY", "ETHERSCAN_KEY", "HELIUS_KEY")


def _strip_quotes(value: str) -> str:
    """Drop a single matching pair of surrounding quotes, if present."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def parse(text: str) -> dict[str, str]:
    """Parse ``.env`` text into a mapping. Blanks and ``#`` comments ignored."""
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        name, _, value = line.partition("=")
        name = name.strip()
        if not name:
            continue
        values[name] = _strip_quotes(value.strip())
    return values


def load(path: str | os.PathLike | None = None) -> dict[str, str]:
    """Load a ``.env`` file into ``os.environ`` without clobbering set vars.

    Returns the mapping that was parsed (possibly empty). A missing or unreadable
    file is not an error; keys are optional and the tools degrade gracefully.
    """
    if path is None:
        path = find()
    if path is None:
        return {}
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return {}
    loaded = parse(text)
    for name, value in loaded.items():
        if value and not os.environ.get(name):
            os.environ[name] = value
    return loaded


def find() -> Path | None:
    """Locate a ``.env``: the current directory first, then the repo root."""
    candidates = (
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None
