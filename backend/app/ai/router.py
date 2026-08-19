"""Model routing, per-request budget, and a circuit breaker.

Routing policy, in the order it is applied:

1. **Offline or edge-mode clinic** → local Llama. No network, no cost.
2. **Simple case** (few concepts, no red flags, common presentation) → local
   Llama. Most primary care is not diagnostically hard, and routing it to a
   frontier model is how the $0.05 ceiling gets blown.
3. **Standard case** → GPT-4o.
4. **Red flag fired, ambiguous case, or low first-pass confidence** → a second
   pass on Claude. This is the only path that spends twice.

The circuit breaker sits in front of every remote provider. After
`FAILURE_THRESHOLD` consecutive failures it opens for `RECOVERY_SECONDS`, and
calls fall straight through to the local model with `degraded=True` rather than
waiting on a timeout that will not succeed. A clinician waiting 30 seconds for
an error is worse than an immediate local answer.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

from app.ai.providers.base import LlmProvider, LlmResponse, LlmUnavailable
from app.ai.providers.llm import AnthropicProvider, LocalLlamaProvider, OpenAIProvider
from app.core import metrics
from app.core.config import get_settings

logger = logging.getLogger("sihhatai.ai.router")

FAILURE_THRESHOLD = 3
RECOVERY_SECONDS = 60.0


class Tier(str, Enum):
    local = "local"
    standard = "standard"
    second_opinion = "second_opinion"


class BreakerState(str, Enum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = FAILURE_THRESHOLD
    recovery_seconds: float = RECOVERY_SECONDS
    failures: int = 0
    opened_at: float | None = None

    @property
    def state(self) -> BreakerState:
        if self.opened_at is None:
            return BreakerState.closed
        if time.monotonic() - self.opened_at >= self.recovery_seconds:
            return BreakerState.half_open
        return BreakerState.open

    def allows(self) -> bool:
        return self.state is not BreakerState.open

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()
            logger.warning("circuit breaker opened for %s", self.name)
            metrics.inc("sihhatai_breaker_opened_total", {"provider": self.name})

    def reset(self) -> None:
        self.failures = 0
        self.opened_at = None


@dataclass
class Budget:
    """Per-consultation spend and latency budget."""

    max_cost_usd: float
    max_latency_ms: int
    spent_usd: float = 0.0
    elapsed_ms: int = 0

    def can_afford(self, estimated_usd: float = 0.0) -> bool:
        return (self.spent_usd + estimated_usd) <= self.max_cost_usd

    @property
    def exhausted(self) -> bool:
        """Spend has reached the ceiling: only the free local model remains.

        Distinct from `can_afford(0)`, which is still true at exactly the
        ceiling — that is the boundary where a further paid call must not be
        made.
        """
        return self.spent_usd >= self.max_cost_usd

    def has_time(self) -> bool:
        return self.elapsed_ms < self.max_latency_ms

    def charge(self, response: LlmResponse) -> None:
        self.spent_usd += response.cost_usd
        self.elapsed_ms += response.latency_ms


@dataclass
class RoutingDecision:
    tier: Tier
    reason: str
    needs_second_opinion: bool = False


@dataclass
class RouteResult:
    response: LlmResponse
    provider_name: str
    tier: Tier
    degraded: bool
    #: Every provider tried, in order, for the audit trail.
    attempts: list[str] = field(default_factory=list)


#: Concept count below which a case is treated as simple enough for the local
#: model. Calibrated against the eval set in Sprint 5, not guessed at runtime.
SIMPLE_CASE_MAX_CONCEPTS = 3

#: Presentations that are common, well-protocolised, and safe to triage
#: locally when nothing else is going on.
SIMPLE_PRESENTATIONS = {
    "common_cold",
    "rhinorrhea",
    "sore_throat",
    "nasal_congestion",
    "headache",
    "low_back_pain",
    "myalgia",
    "constipation",
    "heartburn",
    "pruritus",
    "rash",
}


def choose_tier(
    *,
    concepts: set[str],
    red_flags: int,
    offline: bool,
    clinic_offline_mode: bool = False,
) -> RoutingDecision:
    if offline:
        return RoutingDecision(Tier.local, "no connectivity")
    if clinic_offline_mode and red_flags == 0 and len(concepts) <= SIMPLE_CASE_MAX_CONCEPTS:
        return RoutingDecision(Tier.local, "edge clinic, simple case")
    if red_flags > 0:
        # A red flag has already fired deterministically; the model's job is
        # now the harder one of not missing what sits behind it.
        return RoutingDecision(Tier.standard, "red flag fired", needs_second_opinion=True)
    if concepts and concepts <= SIMPLE_PRESENTATIONS and len(concepts) <= SIMPLE_CASE_MAX_CONCEPTS:
        return RoutingDecision(Tier.local, "simple, well-protocolised presentation")
    return RoutingDecision(Tier.standard, "standard case")


class ModelRouter:
    def __init__(
        self,
        *,
        openai: LlmProvider | None = None,
        anthropic: LlmProvider | None = None,
        local: LlmProvider | None = None,
    ) -> None:
        self.providers: dict[str, LlmProvider] = {
            "openai": openai or OpenAIProvider(),
            "anthropic": anthropic or AnthropicProvider(),
            "local": local or LocalLlamaProvider(),
        }
        self.breakers = {name: CircuitBreaker(name) for name in self.providers}

    def reset_breakers(self) -> None:
        for breaker in self.breakers.values():
            breaker.reset()

    def _call(self, name: str, system: str, user: str, timeout_s: float) -> LlmResponse:
        provider = self.providers[name]
        breaker = self.breakers[name]
        if not breaker.allows():
            raise LlmUnavailable(f"{name}: circuit open")
        if not provider.available():
            raise LlmUnavailable(f"{name}: not configured")
        try:
            response = provider.complete(system=system, user=user, timeout_s=timeout_s)
        except LlmUnavailable:
            breaker.record_failure()
            metrics.inc("sihhatai_llm_failures_total", {"provider": name})
            raise
        breaker.record_success()
        metrics.inc("sihhatai_llm_calls_total", {"provider": name})
        metrics.observe(
            "sihhatai_llm_latency_seconds", response.latency_ms / 1000, {"provider": name}
        )
        return response

    def complete(
        self,
        *,
        system: str,
        user: str,
        decision: RoutingDecision,
        budget: Budget,
        second_opinion: bool = False,
    ) -> RouteResult:
        """Run one model call, falling back down the chain as needed."""
        timeout_s = max(1.0, (budget.max_latency_ms - budget.elapsed_ms) / 1000)

        if second_opinion:
            chain = ["anthropic", "openai", "local"]
        elif decision.tier is Tier.local:
            chain = ["local", "openai"]
        else:
            chain = ["openai", "anthropic", "local"]

        # A request that has already spent its budget may only use the free
        # local model — the ceiling is a hard constraint, not a target.
        if budget.exhausted:
            chain = ["local"]

        attempts: list[str] = []
        last_error: Exception | None = None
        for name in chain:
            attempts.append(name)
            try:
                response = self._call(name, system, user, timeout_s)
            except LlmUnavailable as exc:
                last_error = exc
                logger.info("provider %s unavailable: %s", name, exc)
                continue
            budget.charge(response)
            degraded = name != chain[0] or name == "local" and decision.tier is not Tier.local
            return RouteResult(
                response=response,
                provider_name=name,
                tier=decision.tier,
                degraded=degraded,
                attempts=attempts,
            )

        raise LlmUnavailable(
            f"all providers failed (tried {', '.join(attempts)}): {last_error}"
        ) from last_error

    def should_escalate(self, decision: RoutingDecision, top_confidence: float) -> bool:
        """Second opinion when the first pass is uncertain or a flag fired."""
        settings = get_settings()
        return decision.needs_second_opinion or top_confidence < settings.min_confidence_to_rank
