.PHONY: help install up down migrate revision run worker test lint verify-db

help:
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n",$$1,$$2}'

install:  ## Create .venv and install dependencies
	uv venv .venv && VIRTUAL_ENV=.venv uv pip install -e ".[dev]"

up:  ## Start postgres + redis
	docker compose up -d postgres redis

down:  ## Stop everything
	docker compose down

migrate:  ## Apply migrations
	.venv/bin/alembic upgrade head

revision:  ## Autogenerate a migration: make revision m="add x"
	.venv/bin/alembic revision --autogenerate -m "$(m)"

run:  ## Run the API with reload
	.venv/bin/uvicorn app.main:app --reload

worker:  ## Run the arq task worker
	.venv/bin/arq app.workers.tasks.WorkerSettings

test:  ## Run the test suite
	.venv/bin/pytest -q

lint:  ## Lint and type-check
	.venv/bin/ruff check app tests && .venv/bin/mypy app

verify-db:  ## Run the schema invariant harness against the running database
	docker compose exec -T postgres psql -U crshop -d crshop -v ON_ERROR_STOP=1 < db/verify_constraints.sql
