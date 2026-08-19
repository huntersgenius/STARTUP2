"""Embedding providers.

`HashingEmbeddings` is the offline/CI default: a deterministic hashed
bag-of-character-ngrams projection. It is *not* semantic — two paraphrases do
not land near each other — so offline retrieval leans on BM25 and the
terminology map, and the evaluation report labels which embedder produced a
run. Treating an offline pass as production-quality is the failure mode this
naming is meant to prevent.
"""

from __future__ import annotations

import hashlib
import math

from app.core.config import get_settings


def _tokens(text: str) -> list[str]:
    from app.ai.rag.textnorm import tokenize

    return tokenize(text)


class HashingEmbeddings:
    """Deterministic, dependency-free, offline. Lexical, not semantic."""

    name = "hashing-v1"

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim

    def _bucket(self, token: str) -> int:
        return int.from_bytes(hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest(), "big")

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dim
            tokens = _tokens(text)
            for token in tokens:
                vector[self._bucket(token) % self.dim] += 1.0
                # Character 4-grams give partial credit for Uzbek suffixes,
                # where "yo'tal" and "yo'talyapman" share a stem.
                for i in range(len(token) - 3):
                    gram = token[i : i + 4]
                    vector[self._bucket(gram) % self.dim] += 0.5
            norm = math.sqrt(sum(v * v for v in vector))
            vectors.append([v / norm for v in vector] if norm else vector)
        return vectors


class OpenAIEmbeddings:
    """Production embeddings. Requires a key; never used in CI."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.embedding_model
        self.dim = settings.embedding_dim
        self.name = f"openai:{self.model}"

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is not configured")
        import httpx

        response = httpx.post(
            "https://api.openai.com/v1/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": texts},
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()["data"]
        return [item["embedding"] for item in sorted(data, key=lambda d: d["index"])]


def get_embeddings(prefer_offline: bool = False) -> HashingEmbeddings | OpenAIEmbeddings:
    settings = get_settings()
    if prefer_offline or settings.testing or not settings.openai_api_key:
        return HashingEmbeddings()
    return OpenAIEmbeddings()


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
