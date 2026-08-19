"""Versioned prompt templates.

Prompts are files, not inline strings, so a prompt change is a reviewable diff
and the version that produced any suggestion is recoverable from the database.
The version recorded on `AiSuggestion.prompt_version` is the directory name
plus the content hash, so an edited file cannot silently masquerade as the
version it replaced.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent
DEFAULT_VERSION = "v1"


class PromptNotFound(FileNotFoundError):
    pass


@lru_cache
def load(name: str, version: str = DEFAULT_VERSION) -> str:
    path = PROMPTS_DIR / version / f"{name}.txt"
    if not path.exists():
        raise PromptNotFound(f"no prompt {name!r} in version {version!r}")
    return path.read_text(encoding="utf-8")


@lru_cache
def prompt_version(version: str = DEFAULT_VERSION) -> str:
    """`v1@<hash>` — identifies the exact template content that was used."""
    directory = PROMPTS_DIR / version
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.txt")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return f"{version}@{digest.hexdigest()[:12]}"


def available_versions() -> list[str]:
    return sorted(
        p.name for p in PROMPTS_DIR.iterdir() if p.is_dir() and not p.name.startswith("__")
    )
