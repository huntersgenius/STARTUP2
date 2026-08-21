"""Reuse the project's own fixtures, so the audit runs against the same wiring.

`backend/tests/conftest.py` sets ENVIRONMENT/DATABASE_URL at import time and
defines the db/client/factory fixtures. Loading it as a plugin keeps this
directory free of a second, subtly different harness.
"""

pytest_plugins = ["tests.conftest"]
