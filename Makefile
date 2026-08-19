.PHONY: help up down logs migrate seed test lint fmt typecheck eval eval-report ingest coverage clean

VENV ?= .venv
PY   ?= $(VENV)/bin/python
PIP  ?= $(VENV)/bin/pip

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

$(VENV):  ## create the local virtualenv
	python3 -m venv $(VENV)
	$(PIP) install -q -r backend/requirements-dev.txt

up:  ## start postgres, redis, backend, mailhog
	docker compose -f infra/docker-compose.yml up -d --build

down:  ## stop the stack
	docker compose -f infra/docker-compose.yml down

logs:  ## tail backend logs
	docker compose -f infra/docker-compose.yml logs -f backend

migrate: $(VENV)  ## apply migrations to DATABASE_URL
	cd backend && ../$(PY) -m alembic upgrade head

seed: $(VENV)  ## seed a development clinic (dev/test only)
	cd backend && ../$(PY) -m app.seed --if-empty

test: $(VENV)  ## run the backend test suite
	cd backend && ../$(PY) -m pytest

coverage: $(VENV)  ## run tests with coverage gate
	cd backend && ../$(PY) -m pytest --cov=app --cov-report=term-missing --cov-fail-under=80

lint: $(VENV)  ## ruff
	cd backend && ../$(VENV)/bin/ruff check app tests ../knowledge

fmt: $(VENV)  ## ruff format
	cd backend && ../$(VENV)/bin/ruff format app tests ../knowledge

typecheck: $(VENV)  ## mypy
	cd backend && ../$(VENV)/bin/mypy app

ingest: $(VENV)  ## rebuild the knowledge base from knowledge/corpus
	cd backend && ../$(PY) -m knowledge.ingest --corpus ../knowledge/corpus --reset

eval: $(VENV)  ## run the clinical evaluation suite and print the table
	cd backend && ../$(PY) -m app.ai.eval.run --offline

eval-report: $(VENV)  ## run the evaluation suite and write eval/report.html
	cd backend && ../$(PY) -m app.ai.eval.run --offline --html

clean:
	find . -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true
	rm -rf backend/.pytest_cache backend/.mypy_cache backend/.coverage
