from __future__ import annotations

from app.core import metrics


def test_liveness_reports_build_sha(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert "build_sha" in response.json()


def test_health_reports_dependency_status(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["checks"]["database"] == "ok"
    # Redis is genuinely absent in CI; health must say so rather than crash.
    assert "redis" in body["checks"]
    assert body["status"] in ("ok", "degraded")


def test_health_never_raises_when_a_dependency_is_down(client, monkeypatch):
    monkeypatch.setattr("app.api.health._redis_status", lambda: "unavailable: ConnectionError")
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"


def test_metrics_endpoint_renders_prometheus_text(client):
    metrics.reset()
    client.get("/health/live")
    body = client.get("/metrics").text
    assert "sihhatai_requests_total" in body
    assert "sihhatai_request_duration_seconds_bucket" in body
    assert 'le="+Inf"' in body


def test_request_id_is_echoed(client):
    response = client.get("/health/live", headers={"X-Request-ID": "abc-123"})
    assert response.headers["X-Request-ID"] == "abc-123"
