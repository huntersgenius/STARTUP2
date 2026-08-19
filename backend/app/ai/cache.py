"""Semantic cache for model responses.

Primary care is repetitive: a dozen children a day with the same diarrhoea
presentation. Caching on the normalised symptom vector — not on the raw text —
means "3 kundan beri yo'tal va isitma" and "isitma va yo'tal, 3 kun" hit the
same entry.

Two safety constraints shape the design:

- **Never cache across patients whose clinical context differs.** The key
  includes age band, sex, pregnancy and the red-flag set, so a cached adult
  answer can never be served to a child.
- **Never cache a degraded response.** A rules-only or fallback answer is
  cached nowhere; otherwise one outage poisons the cache for a week.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Any, Protocol, cast

from app.ai.providers.embeddings import cosine
from app.core.config import get_settings

logger = logging.getLogger("sihhatai.ai.cache")

CACHE_PREFIX = "sihhat:sem:"


@dataclass
class CacheEntry:
    response: str
    embedding: list[float]
    model: str
    prompt_version: str


class CacheBackend(Protocol):
    def get_bucket(self, bucket: str) -> list[dict[str, Any]]: ...
    def append(self, bucket: str, payload: dict[str, Any], ttl_seconds: int) -> None: ...


class InMemoryCacheBackend:
    """Used in tests and on edge devices with no Redis."""

    def __init__(self) -> None:
        self.store: dict[str, list[dict[str, Any]]] = {}

    def get_bucket(self, bucket: str) -> list[dict[str, Any]]:
        return self.store.get(bucket, [])

    def append(self, bucket: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        self.store.setdefault(bucket, []).append(payload)


class RedisCacheBackend:
    def __init__(self, url: str | None = None) -> None:
        import redis

        self.client = redis.Redis.from_url(
            url or get_settings().redis_url, socket_connect_timeout=1, decode_responses=True
        )

    def get_bucket(self, bucket: str) -> list[dict[str, Any]]:
        try:
            items = cast(list[str], self.client.lrange(bucket, 0, 49))
            return [json.loads(item) for item in items]
        except Exception as exc:  # noqa: BLE001 - a cache miss must never fail a consultation
            logger.warning("semantic cache read failed: %s", exc)
            return []

    def append(self, bucket: str, payload: dict[str, Any], ttl_seconds: int) -> None:
        try:
            pipe = self.client.pipeline()
            pipe.lpush(bucket, json.dumps(payload, ensure_ascii=False))
            pipe.ltrim(bucket, 0, 49)
            pipe.expire(bucket, ttl_seconds)
            pipe.execute()
        except Exception as exc:  # noqa: BLE001
            logger.warning("semantic cache write failed: %s", exc)


def context_bucket(
    *,
    age_band: str,
    sex: str,
    pregnant: bool,
    language: str,
    red_flag_codes: list[str],
    prompt_version: str,
    model_tier: str,
) -> str:
    """Cache entries are only ever shared within an identical clinical context."""
    digest = hashlib.sha256(
        json.dumps(
            {
                "age_band": age_band,
                "sex": sex,
                "pregnant": pregnant,
                "language": language,
                "red_flags": sorted(red_flag_codes),
                "prompt_version": prompt_version,
                "tier": model_tier,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()[:20]
    return f"{CACHE_PREFIX}{digest}"


class SemanticCache:
    def __init__(self, backend: CacheBackend | None = None, threshold: float | None = None) -> None:
        settings = get_settings()
        self.backend = backend or self._default_backend()
        self.threshold = threshold if threshold is not None else settings.semantic_cache_threshold
        self.ttl = settings.semantic_cache_ttl_seconds
        self.hits = 0
        self.misses = 0

    @staticmethod
    def _default_backend() -> CacheBackend:
        settings = get_settings()
        if settings.testing:
            return InMemoryCacheBackend()
        try:
            return RedisCacheBackend()
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis unavailable, using in-memory semantic cache: %s", exc)
            return InMemoryCacheBackend()

    def get(self, bucket: str, embedding: list[float]) -> CacheEntry | None:
        best: tuple[float, dict[str, Any]] | None = None
        for item in self.backend.get_bucket(bucket):
            similarity = cosine(embedding, item.get("embedding") or [])
            if similarity >= self.threshold and (best is None or similarity > best[0]):
                best = (similarity, item)
        if best is None:
            self.misses += 1
            return None
        self.hits += 1
        _, item = best
        return CacheEntry(
            response=item["response"],
            embedding=item["embedding"],
            model=item.get("model", "unknown"),
            prompt_version=item.get("prompt_version", "unknown"),
        )

    def put(
        self,
        bucket: str,
        embedding: list[float],
        response: str,
        *,
        model: str,
        prompt_version: str,
        degraded: bool = False,
    ) -> None:
        if degraded:
            # One outage must not poison a week of answers.
            return
        self.backend.append(
            bucket,
            {
                "embedding": embedding,
                "response": response,
                "model": model,
                "prompt_version": prompt_version,
            },
            self.ttl,
        )
