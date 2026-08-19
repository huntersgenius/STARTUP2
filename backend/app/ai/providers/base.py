"""Provider protocols.

Nothing outside this package imports a vendor SDK. See docs/adr/0001.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class LlmResponse:
    text: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    #: True when this came from a fallback path rather than the intended model.
    degraded: bool = False
    raw: dict = field(default_factory=dict)


class LlmUnavailable(RuntimeError):
    """Provider is down, over budget, or timed out. Callers must degrade."""


@runtime_checkable
class LlmProvider(Protocol):
    name: str

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1500,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
    ) -> LlmResponse: ...

    def available(self) -> bool: ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...
