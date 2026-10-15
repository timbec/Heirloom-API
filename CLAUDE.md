# CLAUDE.md

FastAPI backend for Heirloom. Replaces the Heirloom parts of the old Laravel app. Read `../CLAUDE.md` for what Heirloom is and `../docs/backend-port.md` for the full plan (API contract, prompts, known bugs, build order). Progress is tracked in `../tasks/todo.md`.

## Running locally

Postgres 17 runs natively via **Postgres.app** (port 5432, your macOS user, no password). Start it from the menu bar; quit it when you're done. No Docker.

```bash
uv sync                                   # install deps
cp .env.example .env                      # first time only; fill in GROQ_API_KEY
uv run uvicorn app.main:app --reload      # http://localhost:8000/api/health, docs at /docs
uv run pytest                             # tests (always use the heirloom_test database)
uv run ruff format . && uv run ruff check .
```

Databases: `heirloom` (dev) and `heirloom_test` (tests). If they're missing:
`createdb heirloom && createdb heirloom_test` (psql tools are in `/Applications/Postgres.app/Contents/Versions/latest/bin`).

## Conventions

- Every route lives under `/api`. Keep the existing contract (`docs/backend-port.md` §4) so `heirloom-web` works unchanged.
- Errors are Laravel-shaped: `{message}` and, for validation, `{message, errors}`. See `app/errors.py`. The frontend reads `message`.
- Multi-tenant: every user-facing query is scoped to the current user. Only the admin panel sees across users (`users.is_admin`).
- AI provider settings and model names come from env (`app/config.py`), never hardcoded.
- Tests use pytest-asyncio (auto mode) with an httpx `AsyncClient` fixture; fake Groq with respx.
