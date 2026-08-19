"""Error reporting.

Sentry is optional and off unless a DSN is configured. When it is on, two
things are non-negotiable: request bodies never leave the process, and the
`before_send` hook strips anything that looks like an identifier. An error
tracker is an external service, and patient data does not go to external
services.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core.config import get_settings

logger = logging.getLogger("sihhatai.observability")

#: Keys scrubbed from every event before it is sent.
SENSITIVE_KEYS = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "secret_key",
    "pii_encryption_key",
    "pii",
    "pii_blob",
    "full_name",
    "phone",
    "passport",
    "address",
    "chief_complaint",
    "raw_output",
}

#: Patterns scrubbed from free-text fields that survive key-based scrubbing.
_PATTERNS = (
    re.compile(r"(?:\+?998|8)[\s\-()]*\d{2}[\s\-()]*\d{3}[\s\-()]*\d{2}[\s\-()]*\d{2}"),
    re.compile(r"\b[A-ZА-Я]{2}\s?\d{7}\b"),
    re.compile(r"\b\d{14}\b"),
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"),
)


def scrub(value: Any) -> Any:
    """Recursively remove identifiers from an event payload."""
    if isinstance(value, dict):
        return {
            key: "[redacted]" if key.lower() in SENSITIVE_KEYS else scrub(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [scrub(item) for item in value]
    if isinstance(value, str):
        scrubbed = value
        for pattern in _PATTERNS:
            scrubbed = pattern.sub("[redacted]", scrubbed)
        return scrubbed
    return value


def before_send(event: dict, hint: dict) -> dict | None:  # noqa: ARG001
    return scrub(event)


def configure_sentry() -> bool:
    """Returns True when Sentry was initialised."""
    settings = get_settings()
    if not settings.sentry_dsn:
        return False
    try:
        import sentry_sdk
    except ImportError:
        logger.warning("SENTRY_DSN is set but sentry-sdk is not installed")
        return False

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.environment,
        release=settings.build_sha,
        # Request bodies can contain a chief complaint. They never leave.
        send_default_pii=False,
        max_request_body_size="never",
        traces_sample_rate=0.05 if settings.environment == "prod" else 0.0,
        before_send=before_send,
    )
    logger.info("sentry initialised for environment %s", settings.environment)
    return True
