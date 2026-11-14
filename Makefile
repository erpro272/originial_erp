# Common commands. Run `make help`.
.PHONY: help up down reset-db logs infra api web worker migrate seed test test-backend test-frontend e2e lint typecheck format gen-api check

help:
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-15s %s\n", $$1, $$2}'

up: ## Start the whole stack (postgres, redis, minio, api, worker, web)
	docker compose up -d --build --wait
	@echo "Web: http://localhost:5173   API docs: http://localhost:8000/api/docs"
down: ## Stop the stack
	docker compose down
reset-db: ## Stop the stack and delete the database volume (fresh seed on next `make up`)
	docker compose down -v
logs: ## Follow logs of api, worker and web
	docker compose logs -f api worker web

infra: ## Start only postgres, redis and minio (for running api/web on the host)
	docker compose up -d --wait postgres redis minio
api: ## Run the API on the host with reload
	cd backend && uv run alembic upgrade head && ERP_SEED_DEMO=true uv run python -m seed.run --if-empty && uv run uvicorn app.main:app --reload --port 8000
worker: ## Run the background worker on the host
	cd backend && uv run arq app.worker.WorkerSettings
web: ## Run the web app on the host
	cd frontend && npm run dev
migrate: ## Apply database migrations
	cd backend && uv run alembic upgrade head
seed: ## Wipe and re-seed the dev database
	cd backend && uv run python -m seed.run --reset

test: test-backend test-frontend ## Backend + frontend tests
test-backend: ## pytest against the real Postgres test DB (needs `make infra`)
	cd backend && uv run pytest
test-frontend: ## Vitest + React Testing Library
	cd frontend && npm test
e2e: ## Playwright against the running stack (needs `make up`)
	cd e2e && npx playwright test --trace off

lint: ## ruff + ESLint + Prettier check
	cd backend && uv run ruff check . && uv run ruff format --check .
	cd frontend && npm run -s lint && npm run -s format:check
typecheck: ## mypy + tsc
	cd backend && uv run mypy app seed
	cd frontend && npm run -s typecheck
format: ## Auto-format everything
	cd backend && uv run ruff format . && uv run ruff check --fix .
	cd frontend && npm run -s format
gen-api: ## Regenerate OpenAPI schema + TypeScript types (run after changing the API)
	cd backend && uv run python -m scripts.export_openapi
	cd frontend && npm run -s gen:api

check: lint typecheck test ## Everything CI runs except e2e
