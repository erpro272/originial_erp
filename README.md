# Manufacturing ERP

ERP for small and mid-sized Indian manufacturers (fasteners, bolts, nuts, steel
assemblies): **Orders · Planning · Purchasing · Production · Billing · Finance**.

## Run it

Requirements: Docker with Compose.

```bash
docker compose up -d --build --wait
```

| What | URL |
|---|---|
| Web app | http://localhost:5173 |
| API docs (OpenAPI) | http://localhost:8000/api/docs |
| MinIO console | http://localhost:9001 (minioadmin / minioadmin) |

On first start the database is migrated and seeded. Sign in with any of these
(password **`Demo@12345`**):

| Email | Role |
|---|---|
| `owner@demo.example` | Owner of both demo companies (shows the company picker) |
| `planner@demo.example` | Planner |
| `purchaser@demo.example` | Purchaser |
| `accountant@demo.example` | Accountant |
| `owner@second.example` | Owner of the second company only |

### After `git pull`: empty pages?
Postgres data lives in a Docker volume that survives `git pull`. On startup the API now adds demo
data to the demo companies that have none (dev only, `ERP_SEED_DEMO=true` in compose), and never
touches a company that already has data. To start over with fresh demo data (**wipes the local
database**):

```bash
docker compose exec api python -m seed.run --reset
```

To use the real AI for invoice extraction, put `ANTHROPIC_API_KEY=...` in a `.env` file
next to `docker-compose.yml`. Without it the AI runs in mock mode.

## Develop

`make help` lists everything. Typical loop: `make infra`, then `make api`, `make worker`
and `make web` in separate terminals; `make test`, `make lint`, `make typecheck`;
`make gen-api` after changing the API. Details and conventions are in [CLAUDE.md](CLAUDE.md);
status is in [docs/PROGRESS.md](docs/PROGRESS.md).

```
backend/    FastAPI modular monolith (core, orders, customers, planning, …, ai)
frontend/   React + TypeScript (Vite), design system from the mockups
e2e/        Playwright end-to-end tests
infra/      Postgres init (database roles)
docs/       Progress and decisions
```
