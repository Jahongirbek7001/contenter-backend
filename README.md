# Contentor AI — backend

Telegram bot (aiogram 3), API (FastAPI), worker (arq), model gateway (Gemini Hydrogen, Omni Flash, Veo 3.1 Lite, Nano Banana, Lyria).

Stack: Python 3.12, uv, PostgreSQL, Redis, SQLAlchemy 2 async, Alembic, ffmpeg.

Product plan and decisions: `../docs/plan.md`.

## Local development

```bash
docker compose up -d          # PostgreSQL 16 + Redis 7
uv sync                       # dependencies
uv run ruff check . && uv run mypy app tests && uv run pytest
```

Environment variables (`.env`, never committed): `DATABASE_URL`, `REDIS_URL`, `GEMINI_API_KEY`, `GCP_PROJECT_ID`, `GCP_LOCATION`, `GOOGLE_APPLICATION_CREDENTIALS`, `TELEGRAM_BOT_TOKEN`.

Tests need the compose Postgres and a `contentor_test` database (created once):

```bash
docker compose exec postgres psql -U contentor -c "CREATE DATABASE contentor_test;"
```

Migrations: `DATABASE_URL=... uv run alembic upgrade head`.

## Structure

- `app/models` — SQLAlchemy models; `migrations/` — Alembic (schema + catalog seed).
- `app/domain/credits` — ⚡ ledger: holds, spend, release, payment crediting (idempotent, trial once).
- `app/gateway` — provider contracts, capabilities, product→model registry, fake provider.
