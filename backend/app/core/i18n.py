"""Message catalogs and Accept-Language resolution.

Uzbek is the default. English exists for admin/dev surfaces only — no clinical
string is ever shown to a clinician in English unless they chose it.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from app.core.config import get_settings

LOCALES_DIR = Path(__file__).parent / "locales"


@lru_cache
def catalog(language: str) -> dict[str, str]:
    settings = get_settings()
    lang = language if language in settings.supported_languages else settings.default_language
    path = LOCALES_DIR / f"{lang}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def translate(key: str, language: str, **kwargs: object) -> str:
    """Look up `key`; fall back to the default language, then to the key itself."""
    settings = get_settings()
    text = catalog(language).get(key)
    if text is None:
        text = catalog(settings.default_language).get(key, key)
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


def resolve_language(accept_language: str | None, *, fallback: str | None = None) -> str:
    """Parse an Accept-Language header into one of our supported languages.

    Uzbek Cyrillic (`uz-Cyrl`) and Karakalpak (`kaa`) resolve to `uz`; every
    other unknown tag falls through to the caller's fallback.
    """
    settings = get_settings()
    default = fallback or settings.default_language
    if not accept_language:
        return default

    candidates: list[tuple[float, str]] = []
    for part in accept_language.split(","):
        piece = part.strip()
        if not piece:
            continue
        tag, _, params = piece.partition(";")
        quality = 1.0
        if params.strip().startswith("q="):
            try:
                quality = float(params.strip()[2:])
            except ValueError:
                quality = 0.0
        candidates.append((quality, tag.strip().lower()))

    for _, tag in sorted(candidates, key=lambda c: c[0], reverse=True):
        base = tag.split("-")[0]
        if base in ("uz", "kaa"):
            return "uz"
        if base in settings.supported_languages:
            return base
    return default
