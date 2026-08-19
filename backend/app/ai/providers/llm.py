"""LLM providers. The only modules in the codebase that speak to a vendor."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import httpx

from app.ai.providers.base import LlmResponse, LlmUnavailable
from app.core.config import get_settings

#: USD per 1M tokens (input, output). Kept here rather than in config so a
#: pricing change is a reviewed code change — cost per consultation is a
#: product constraint, not a runtime setting.
PRICING: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "claude-sonnet-4-5": (3.00, 15.00),
    "claude-opus-4-5": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    input_rate, output_rate = PRICING.get(model, (0.0, 0.0))
    return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000


def _approx_tokens(text: str) -> int:
    return max(1, len(text) // 4)


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.openai_api_key
        self.model = model or settings.openai_model

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1500,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
    ) -> LlmResponse:
        if not self.available():
            raise LlmUnavailable("OPENAI_API_KEY is not configured")
        started = time.perf_counter()
        try:
            response = httpx.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                },
                timeout=timeout_s,
            )
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise LlmUnavailable(f"openai: {type(exc).__name__}") from exc

        body = response.json()
        usage = body.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        return LlmResponse(
            text=body["choices"][0]["message"]["content"],
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=estimate_cost(self.model, prompt_tokens, completion_tokens),
            raw={"id": body.get("id")},
        )


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.anthropic_model

    def available(self) -> bool:
        return bool(self.api_key)

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1500,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
    ) -> LlmResponse:
        if not self.api_key:
            raise LlmUnavailable("ANTHROPIC_API_KEY is not configured")
        started = time.perf_counter()
        try:
            response = httpx.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": str(self.api_key),
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                },
                timeout=timeout_s,
            )
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise LlmUnavailable(f"anthropic: {type(exc).__name__}") from exc

        body = response.json()
        usage = body.get("usage", {})
        prompt_tokens = int(usage.get("input_tokens", 0))
        completion_tokens = int(usage.get("output_tokens", 0))
        text = "".join(block.get("text", "") for block in body.get("content", []))
        return LlmResponse(
            text=text,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=estimate_cost(self.model, prompt_tokens, completion_tokens),
            raw={"id": body.get("id")},
        )


class LocalLlamaProvider:
    """Ollama-compatible endpoint on the clinic edge box. Free, offline, slower."""

    name = "local"

    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.base_url = (base_url or settings.local_llm_base_url or "").rstrip("/")
        self.model = model or settings.local_model

    def available(self) -> bool:
        return bool(self.base_url)

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1500,
        temperature: float = 0.0,
        timeout_s: float = 60.0,
    ) -> LlmResponse:
        if not self.available():
            raise LlmUnavailable("LOCAL_LLM_BASE_URL is not configured")
        started = time.perf_counter()
        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
                timeout=timeout_s,
            )
            response.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            raise LlmUnavailable(f"local: {type(exc).__name__}") from exc

        body = response.json()
        return LlmResponse(
            text=body.get("message", {}).get("content", ""),
            model=f"local:{self.model}",
            prompt_tokens=int(body.get("prompt_eval_count", _approx_tokens(system + user))),
            completion_tokens=int(body.get("eval_count", 0)),
            latency_ms=int((time.perf_counter() - started) * 1000),
            cost_usd=0.0,  # self-hosted
            raw={},
        )


class ScriptedProvider:
    """Replays recorded responses. Used by CI, the eval harness and demos.

    Cassettes are keyed by a hash of the system+user prompt, so a changed
    prompt misses the cassette loudly rather than silently replaying a stale
    answer. `strict=False` falls back to a rules-shaped empty response, which
    is what the offline eval baseline uses.
    """

    name = "scripted"

    def __init__(
        self,
        cassette_dir: Path | str | None = None,
        *,
        responses: dict[str, str] | None = None,
        default: str | None = None,
        strict: bool = False,
        latency_ms: int = 5,
    ) -> None:
        self.cassette_dir = Path(cassette_dir) if cassette_dir else None
        self.responses = responses or {}
        self.default = default
        self.strict = strict
        self.latency_ms = latency_ms
        self.model = "scripted"
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def key_for(system: str, user: str) -> str:
        return hashlib.sha256(f"{system}\n---\n{user}".encode()).hexdigest()[:16]

    def available(self) -> bool:
        return True

    def record(self, system: str, user: str, response: str) -> str:
        key = self.key_for(system, user)
        if self.cassette_dir:
            self.cassette_dir.mkdir(parents=True, exist_ok=True)
            (self.cassette_dir / f"{key}.json").write_text(
                json.dumps({"response": response}, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        self.responses[key] = response
        return key

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int = 1500,
        temperature: float = 0.0,
        timeout_s: float = 30.0,
    ) -> LlmResponse:
        key = self.key_for(system, user)
        self.calls.append({"key": key, "system": system, "user": user})

        text = self.responses.get(key)
        if text is None and self.cassette_dir:
            path = self.cassette_dir / f"{key}.json"
            if path.exists():
                text = json.loads(path.read_text(encoding="utf-8"))["response"]
        if text is None:
            text = self.default
        if text is None:
            if self.strict:
                raise LlmUnavailable(f"no cassette for key {key}")
            # Not an error: the engine's rules-only degradation path is a
            # supported outcome, and the eval harness measures it explicitly.
            raise LlmUnavailable("scripted provider has no response for this prompt")

        return LlmResponse(
            text=text,
            model=self.model,
            prompt_tokens=_approx_tokens(system + user),
            completion_tokens=_approx_tokens(text),
            latency_ms=self.latency_ms,
            cost_usd=0.0,
        )
