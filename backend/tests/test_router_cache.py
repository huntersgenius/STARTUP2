"""Routing, budget, circuit breaker, and the semantic cache."""

from __future__ import annotations

import pytest

from app.ai.cache import InMemoryCacheBackend, SemanticCache, context_bucket
from app.ai.providers.base import LlmUnavailable
from app.ai.providers.llm import ScriptedProvider, estimate_cost
from app.ai.router import (
    BreakerState,
    Budget,
    CircuitBreaker,
    ModelRouter,
    RoutingDecision,
    Tier,
    choose_tier,
)


class AlwaysFails:
    name = "broken"

    def __init__(self) -> None:
        self.calls = 0

    def available(self) -> bool:
        return True

    def complete(self, **kwargs):
        self.calls += 1
        raise LlmUnavailable("simulated outage")


# --- routing -------------------------------------------------------------


def test_no_connectivity_routes_local():
    assert choose_tier(concepts={"cough"}, red_flags=0, offline=True).tier is Tier.local


def test_simple_presentation_routes_local_to_protect_the_cost_ceiling():
    decision = choose_tier(concepts={"common_cold"}, red_flags=0, offline=False)
    assert decision.tier is Tier.local


def test_complex_presentation_routes_standard():
    decision = choose_tier(
        concepts={"chest_pain", "dyspnea", "syncope", "palpitations"}, red_flags=0, offline=False
    )
    assert decision.tier is Tier.standard


def test_red_flag_requests_a_second_opinion():
    decision = choose_tier(concepts={"chest_pain"}, red_flags=1, offline=False)
    assert decision.needs_second_opinion is True


def test_edge_clinic_keeps_simple_cases_local():
    decision = choose_tier(
        concepts={"headache"}, red_flags=0, offline=False, clinic_offline_mode=True
    )
    assert decision.tier is Tier.local


# --- circuit breaker -----------------------------------------------------


def test_breaker_opens_after_repeated_failures():
    breaker = CircuitBreaker("test")
    assert breaker.state is BreakerState.closed
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state is BreakerState.open
    assert not breaker.allows()


def test_breaker_half_opens_after_the_recovery_window(monkeypatch):
    breaker = CircuitBreaker("test", recovery_seconds=0.0)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.state is BreakerState.half_open
    assert breaker.allows()


def test_success_resets_the_failure_count():
    breaker = CircuitBreaker("test")
    breaker.record_failure()
    breaker.record_success()
    assert breaker.failures == 0
    assert breaker.state is BreakerState.closed


def test_router_falls_back_to_local_and_marks_degraded():
    broken = AlwaysFails()
    local = ScriptedProvider(default='{"differentials": []}')
    router = ModelRouter(openai=broken, anthropic=broken, local=local)

    result = router.complete(
        system="s",
        user="u",
        decision=RoutingDecision(Tier.standard, "test"),
        budget=Budget(max_cost_usd=0.05, max_latency_ms=6000),
    )
    assert result.provider_name == "local"
    assert result.degraded is True
    assert result.attempts == ["openai", "anthropic", "local"]


def test_open_breaker_skips_the_dead_provider_without_waiting():
    broken = AlwaysFails()
    local = ScriptedProvider(default="{}")
    router = ModelRouter(openai=broken, anthropic=broken, local=local)
    budget = Budget(max_cost_usd=0.05, max_latency_ms=6000)
    decision = RoutingDecision(Tier.standard, "test")

    for _ in range(3):
        router.complete(system="s", user="u", decision=decision, budget=budget)
    calls_before = broken.calls
    router.complete(system="s", user="u", decision=decision, budget=budget)
    # The breaker is open, so the dead provider is not called again.
    assert broken.calls == calls_before


def test_every_provider_down_raises_rather_than_hanging():
    broken = AlwaysFails()
    router = ModelRouter(openai=broken, anthropic=broken, local=broken)
    with pytest.raises(LlmUnavailable):
        router.complete(
            system="s",
            user="u",
            decision=RoutingDecision(Tier.standard, "test"),
            budget=Budget(max_cost_usd=0.05, max_latency_ms=6000),
        )


# --- budget --------------------------------------------------------------


def test_exhausted_budget_restricts_the_chain_to_the_free_model():
    paid = AlwaysFails()
    local = ScriptedProvider(default="{}")
    router = ModelRouter(openai=paid, anthropic=paid, local=local)
    budget = Budget(max_cost_usd=0.05, max_latency_ms=6000, spent_usd=0.05)

    result = router.complete(
        system="s", user="u", decision=RoutingDecision(Tier.standard, "test"), budget=budget
    )
    assert result.attempts == ["local"]
    assert paid.calls == 0


def test_budget_tracks_spend_and_latency():
    budget = Budget(max_cost_usd=0.05, max_latency_ms=6000)
    assert budget.can_afford(0.04)
    assert not budget.can_afford(0.06)


def test_cost_estimate_matches_published_pricing():
    # 1M input tokens of gpt-4o at $2.50.
    assert estimate_cost("gpt-4o", 1_000_000, 0) == pytest.approx(2.50)
    assert estimate_cost("unknown-model", 1_000_000, 1_000_000) == 0.0


def test_a_typical_consultation_stays_under_the_cost_ceiling():
    # ~4k input tokens of protocol context, ~800 output tokens.
    cost = estimate_cost("gpt-4o", 4000, 800)
    assert cost < 0.05, f"a single call already costs {cost:.4f}"


# --- semantic cache ------------------------------------------------------


def test_cache_returns_a_near_identical_query():
    cache = SemanticCache(backend=InMemoryCacheBackend(), threshold=0.9)
    bucket = "b"
    cache.put(bucket, [1.0, 0.0, 0.0], "response", model="m", prompt_version="v1")
    hit = cache.get(bucket, [0.99, 0.01, 0.0])
    assert hit is not None
    assert hit.response == "response"


def test_cache_misses_a_different_query():
    cache = SemanticCache(backend=InMemoryCacheBackend(), threshold=0.97)
    cache.put("b", [1.0, 0.0, 0.0], "response", model="m", prompt_version="v1")
    assert cache.get("b", [0.0, 1.0, 0.0]) is None


def test_degraded_responses_are_not_stored():
    backend = InMemoryCacheBackend()
    cache = SemanticCache(backend=backend)
    cache.put("b", [1.0], "response", model="m", prompt_version="v1", degraded=True)
    assert backend.store == {}


def test_a_child_never_receives_an_adults_cached_answer():
    adult = context_bucket(
        age_band="adult",
        sex="female",
        pregnant=False,
        language="uz",
        red_flag_codes=[],
        prompt_version="v1",
        model_tier="standard",
    )
    child = context_bucket(
        age_band="under5",
        sex="female",
        pregnant=False,
        language="uz",
        red_flag_codes=[],
        prompt_version="v1",
        model_tier="standard",
    )
    assert adult != child


def test_a_different_red_flag_set_is_a_different_bucket():
    clean = context_bucket(
        age_band="adult",
        sex="male",
        pregnant=False,
        language="uz",
        red_flag_codes=[],
        prompt_version="v1",
        model_tier="standard",
    )
    flagged = context_bucket(
        age_band="adult",
        sex="male",
        pregnant=False,
        language="uz",
        red_flag_codes=["acs_suspected"],
        prompt_version="v1",
        model_tier="standard",
    )
    assert clean != flagged


def test_a_prompt_change_invalidates_the_cache():
    old = context_bucket(
        age_band="adult",
        sex="male",
        pregnant=False,
        language="uz",
        red_flag_codes=[],
        prompt_version="v1@aaa",
        model_tier="standard",
    )
    new = context_bucket(
        age_band="adult",
        sex="male",
        pregnant=False,
        language="uz",
        red_flag_codes=[],
        prompt_version="v1@bbb",
        model_tier="standard",
    )
    assert old != new


def test_language_separates_buckets():
    uz = context_bucket(
        age_band="adult",
        sex="male",
        pregnant=False,
        language="uz",
        red_flag_codes=[],
        prompt_version="v1",
        model_tier="standard",
    )
    ru = context_bucket(
        age_band="adult",
        sex="male",
        pregnant=False,
        language="ru",
        red_flag_codes=[],
        prompt_version="v1",
        model_tier="standard",
    )
    assert uz != ru


# --- cassette provider ---------------------------------------------------


def test_cassette_key_changes_when_the_prompt_changes(tmp_path):
    provider = ScriptedProvider(cassette_dir=tmp_path)
    key = provider.record("system", "user", '{"differentials": []}')
    assert provider.complete(system="system", user="user").text == '{"differentials": []}'
    # A changed prompt must miss loudly rather than replay a stale answer.
    with pytest.raises(LlmUnavailable):
        provider.complete(system="system", user="different user")
    assert (tmp_path / f"{key}.json").exists()
