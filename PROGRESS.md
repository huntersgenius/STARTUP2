# SihhatAI — Progress

Updated at the end of every sprint. Format: shipped / stubbed / next.

## Sprint 1 — Skeleton, auth, domain, audit, i18n ✅

**Shipped**
- `infra/docker-compose.yml`: postgres 16 + pgvector, redis, backend, mailhog, all health-checked.
- FastAPI app with pydantic-settings, `.env.example`, `/health` (build SHA + DB/Redis status),
  `/health/live`, `/metrics` (dependency-free Prometheus text format).
- Full domain model + Alembic migrations, verified up and down. Patient identifiers are an
  AES-256-GCM blob bound to the row id; a database dump contains no names.
- JWT access/refresh with role dependencies. Cross-clinic reads return **404, not 403**, so the
  existence of another clinic's record is not leaked. Nine tests cover the isolation boundary.
- Append-only hash-chained `AuditLog`, plus a Postgres trigger that rejects UPDATE/DELETE, so
  tampering requires visibly dropping the trigger. Identifiers are refused in audit metadata at
  write time.
- Offline sync (`POST /sync`): idempotent by `operation_id`, per-field last-write-wins, and every
  discarded value recorded in `SyncMergeLog` — last-write-wins is only acceptable if the loser is
  recoverable. One bad operation cannot discard the rest of a batch.
- Admin surfaces: clinic onboarding, bulk users, per-clinic metrics (acceptance rate is the headline),
  audit chain verification, CSV audit export for the regulatory sandbox.
- i18n: uz/ru/en catalogs with a test asserting the clinical strings are actually translated,
  not copied from English. `uz-Cyrl` and `kaa` resolve to `uz`.
- CI: ruff, ruff-format, mypy, pytest with an 80% coverage gate, a separate un-skippable red-team job,
  and a migration up/down check.

**Numbers**: 70 tests green, 84% coverage on `app/`, mypy clean on 39 files.

**Stubbed**
- `app/api/ai.py` is an empty router until Sprint 3.
- `app/seed.py` has no test coverage (dev-only helper; refuses to run outside dev/test).
- The `web` and `mobile` CI jobs reference projects that arrive in Sprints 4 and 6.

**Next**: Sprint 2 — knowledge ingestion, terminology map, hybrid retrieval, formulary.
