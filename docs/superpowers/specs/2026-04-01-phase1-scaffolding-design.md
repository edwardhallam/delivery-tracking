# Phase 1: Project Scaffolding — Design Spec

**Date**: 2026-04-01
**Linear**: DEL-5
**Status**: Approved
**Architecture refs**: ARCH-OVERVIEW (all), 08-deployment.md (all)

---

## Scope

Create the complete project directory structure, configuration files, Docker infrastructure, and empty package markers for the delivery tracking web service. No business logic — just the skeleton that all subsequent phases build on.

## Files

### Project root

| File | Source | Notes |
|------|--------|-------|
| `docker-compose.yml` | DEPLOY-REQ-001–005, 035–038 | 3 services, health checks, log rotation |
| `.env.example` | DEPLOY-REQ-048 + global CLAUDE.md secrets policy | 1Password refs for secret vars |
| `.gitignore` | — | Python, Node, Docker, .env, __pycache__, .DS_Store |

### `api/`

| File | Source | Notes |
|------|--------|-------|
| `Dockerfile` | DEPLOY-REQ-006–010 | Two-stage: builder (deps) + runtime (python:3.12-slim, non-root) |
| `entrypoint.sh` | DEPLOY-REQ-021–025 | `set -e`, alembic upgrade head, seed, exec uvicorn |
| `requirements.txt` | ARCH-OVERVIEW §1 | Pinned versions, all runtime deps |
| `alembic.ini` | — | Points to `alembic/`, uses async driver from `app.config` |
| `alembic/env.py` | — | Async SQLAlchemy env, imports `DATABASE_URL` from config |
| `alembic/versions/.gitkeep` | — | Empty directory marker (migrations come in Phase 4) |
| `app/main.py` | — | Placeholder: `# Phase 5: App factory + lifespan` |
| `app/config.py` | ARCH-OVERVIEW §8.1 | pydantic-settings `Settings` with all §8.2 env vars + validators |

### `api/app/` package tree (empty `__init__.py` only)

```
app/
├── __init__.py
├── domain/
│   ├── __init__.py
│   ├── entities/__init__.py
│   ├── value_objects/__init__.py
│   └── repositories/__init__.py
├── application/
│   ├── __init__.py
│   ├── use_cases/
│   │   ├── __init__.py
│   │   ├── auth/__init__.py
│   │   ├── deliveries/__init__.py
│   │   ├── polling/__init__.py
│   │   └── system/__init__.py
│   └── dtos/__init__.py
├── infrastructure/
│   ├── __init__.py
│   ├── database/
│   │   ├── __init__.py
│   │   ├── models/__init__.py
│   │   └── repositories/__init__.py
│   ├── mappers/__init__.py
│   ├── parcel_api/__init__.py
│   └── scheduler/__init__.py
└── presentation/
    ├── __init__.py
    ├── routers/__init__.py
    ├── schemas/__init__.py
    └── middleware/__init__.py
```

### `frontend/` (placeholder)

| File | Source | Notes |
|------|--------|-------|
| `Dockerfile` | — | Single-stage nginx:alpine, copies static + nginx.conf |
| `nginx.conf` | DEPLOY-REQ-029–032 | API proxy to api:8000, SPA fallback, static asset caching |
| `public/index.html` | — | Bare placeholder page |

## Key decisions

1. **`requirements.txt` over `pyproject.toml`** — ARCH-OVERVIEW §3 and the Dockerfile template reference it explicitly.
2. **Frontend placeholder** — minimal nginx serving a static page so `docker compose up` works end-to-end from Phase 1.
3. **1Password references in `.env.example`** — global CLAUDE.md requires `# 1Password: nexus > Item Name` for secret vars. Added for `POSTGRES_PASSWORD`, `PARCEL_API_KEY`, `JWT_SECRET_KEY`, `ADMIN_PASSWORD`.
4. **`config.py` with validators** — pydantic-settings validators enforce key lengths and value ranges at import time (ARCH-OVERVIEW §8.1). This is the only file with real logic in Phase 1.

## Dependency versions (pinned in `requirements.txt`)

| Package | Version | Purpose |
|---------|---------|---------|
| fastapi | 0.115.* | Web framework |
| uvicorn[standard] | 0.34.* | ASGI server |
| sqlalchemy[asyncio] | 2.0.* | ORM + async support |
| psycopg[binary] | 3.2.* | PostgreSQL async driver |
| alembic | 1.14.* | Database migrations |
| httpx | 0.28.* | Async HTTP client (Parcel API) |
| apscheduler | 3.10.* | Background scheduler |
| pydantic-settings | 2.7.* | Environment config |
| passlib[bcrypt] | 1.7.* | Password hashing |
| python-jose[cryptography] | 3.3.* | JWT tokens |

## QA

**Risk**: Low (file creation only, no logic except config validators)
**Complexity**: Low (1 file with logic: `config.py`)
**Execution**: Self-verify — confirm all files exist, `__init__.py` count matches architecture, config.py imports cleanly.

## Out of scope

- Domain entities, value objects, repository ABCs (Phase 2)
- Use cases, DTOs (Phase 3)
- ORM models, mappers, concrete repos, Parcel client, scheduler (Phase 4)
- Routers, schemas, DI wiring, middleware, app factory (Phase 5)
- Seed script implementation (Phase 4/5 — entrypoint.sh references it but it doesn't exist yet)
- Alembic migrations (Phase 4)
