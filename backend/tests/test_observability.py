"""Error reports are an external service; patient data must not reach them."""

from __future__ import annotations

from app.core.observability import before_send, configure_sentry, scrub


def test_sensitive_keys_are_redacted():
    event = {
        "request": {
            "data": {
                "chief_complaint": "Bemor Aziza Yusupova yo'talyapti",
                "password": "hunter2",
                "temperature_c": 38.5,
            }
        }
    }
    scrubbed = scrub(event)
    assert scrubbed["request"]["data"]["chief_complaint"] == "[redacted]"
    assert scrubbed["request"]["data"]["password"] == "[redacted]"
    # Clinical values that are not identifiers stay, or the report is useless.
    assert scrubbed["request"]["data"]["temperature_c"] == 38.5


def test_identifier_patterns_are_scrubbed_from_free_text():
    event = {"message": "failed for +998901234567 / AA1234567 / a@b.uz"}
    scrubbed = scrub(event)
    assert "998901234567" not in scrubbed["message"]
    assert "AA1234567" not in scrubbed["message"]
    assert "a@b.uz" not in scrubbed["message"]


def test_nested_structures_are_scrubbed():
    event = {"extra": {"patients": [{"full_name": "Aziza", "mrn": "P-1"}]}}
    scrubbed = scrub(event)
    assert scrubbed["extra"]["patients"][0]["full_name"] == "[redacted]"


def test_before_send_returns_a_scrubbed_event():
    assert before_send({"message": "tel +998901234567"}, {})["message"].endswith("[redacted]")


def test_sentry_is_off_without_a_dsn():
    # No DSN configured in tests, so nothing is initialised and nothing is sent.
    assert configure_sentry() is False
