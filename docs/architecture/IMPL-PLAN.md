# Implementation Plan
## Delivery Tracking Web Service

**Document ID**: IMPL-PLAN  
**Status**: Ready for Implementation  
**Addresses**: All requirements documents (`00-master` through `08-deployment`); all architecture documents (`ARCH-OVERVIEW` through `ARCH-PRESENTATION`)  
**Layer Mapping**: All four Clean Architecture layers — ordered inward → outward

---

## Summary

This document is the structured implementation plan for the Delivery Tracking Web Service. It defines 8 phases with 35 concrete tasks, ordered by Clean Architecture dependency rules: the Domain layer is implemented before the Application layer depends on it; the Application layer before Infrastructure; Infrastructure before Presentation. Each task carries its architecture document reference, file deliverables, and acceptance criteria.

The plan is also tracked in the workspace planning system under plan ID `delivery_impl_plan`.

**Source documents driving this plan:**
- `ARCH-OVERVIEW.md` — canonical module structure, startup sequence, patterns
- `ARCH-DOMAIN.md` — entities, value objects, ABCs, domain exceptions
- `ARCH-APPLICATION.md` — use cases, DTOs, external service interfaces
- `ARCH-INFRASTRUCTURE.md` — ORM models, mappers, repositories, Parcel client, scheduler
- `ARCH-PRESENTATION.md` — config, schemas, JWT, routers, middleware, app factory

---

## Governing Constraints

| Constraint | Source | Impact |
|-----------|--------|--------|
| Dependencies flow inward only | ARCH-OVERVIEW §1 | No domain code imports infrastructure |
| APScheduler incompatible with `--workers > 1` | DEPLOY-REQ-023 | Single Uvicorn worker mandatory |
| Parcel API rate limit: 20 req/hr | POLL-REQ-006 | Minimum poll interval 5 min enforced |
| ±30s jitter on poll interval | ARCH-INFRASTRUCTURE §8 | Non-negotiable; prevents exact-minute hammering |
| `token_version` on users table | GAP-001 (ARCH-OVERVIEW §9) | Required by auth; missing from 02-data-model.md |
| 100% branch coverage on normalisation | NORM-REQ-012 | `normalize_status()` + `get_lifecycle_group()` |
| `set -e` in entrypoint.sh | DEPLOY-REQ-022 | Migration/seed failure stops container start |

---

## Phase Overview

| Phase | Focus | Tasks | Priority |
|-------|-------|------:|:--------:|
| 1 | Project Scaffolding | 7 | High |
| 2 | Domain Layer | 4 | High |
| 3 | Application Layer | 7 | High |
| 4 | Infrastructure Layer | 7 | High |
| 5 | Presentation Layer | 7 | High |
| 6 | Database Migrations | 2 | High |
| 7 | Configuration, Seed & Nginx | 3 | Medium |
| 8 | Testing | 5 | Medium/High |
| **Total** | | **42** | |

---

## Phase 1 — Project Scaffolding

**Goal**: Establish the complete monorepo skeleton. No domain logic yet — chassis only.  
**Arch ref**: ARCH-OVERVIEW §3, 08-deployment requirements throughout, ADRs 001–006.

---

### Task 1.1 — Create monorepo directory tree

**Deliverables**: Complete directory tree with `__init__.py` placeholders.

```
api/
  app/
    domain/entities/  domain/value_objects/  domain/repositories/
    application/use_cases/auth/  application/use_cases/deliveries/
    application/use_cases/polling/  application/use_cases/system/
    application/dtos/  application/services/
    infrastructure/database/models/  infrastructure/database/repositories/
    infrastructure/mappers/  infrastructure/parcel_api/  infrastructure/scheduler/
    presentation/routers/  presentation/schemas/  presentation/middleware/
  alembic/versions/
frontend/src/
  components/  pages/  hooks/  api/  context/  types/
nginx/
.scratch/
```

**Acceptance criteria**: `python -c "import app"` succeeds from `api/` directory.

---

### Task 1.2 — Python dependency manifest

**Deliverables**: `api/requirements.txt`, `api/requirements-dev.txt`.

**Runtime dependencies**:
```
fastapi>=0.111
uvicorn[standard]>=0.29
sqlalchemy[asyncio]>=2.0
psycopg[binary]>=3.1          # async psycopg3 driver
psycopg2-binary                # Alembic sync migration path
alembic>=1.13
pydantic>=2.0
pydantic-settings>=2.0
apscheduler>=3.10
httpx>=0.27
passlib[bcrypt]
python-jose[cryptography]
structlog
```

**Dev dependencies**: `pytest>=8`, `pytest-asyncio>=0.23`, `pytest-cov>=5`, `respx`, `anyio[trio]`

**Acceptance criteria**: `pip install -r requirements.txt` succeeds in a clean virtual environment.

---

### Task 1.3 — Docker Compose stack

**Deliverables**: `docker-compose.yml` at repository root.

**Key configuration** (Requirements: DEPLOY-REQ-001–020, DEPLOY-REQ-035–040, SEC-REQ-049–054):

| Service | Image | Port Exposure | Healthcheck |
|---------|-------|:-------------:|-------------|
| `postgres` | `postgres:16.3-alpine` | ❌ (internal only) | `pg_isready` — 10s interval, 30s start_period |
| `api` | `./api` build | ❌ (internal only) | `GET /api/health` — 30s interval, 60s start_period |
| `frontend` | `./frontend` build | ✅ `${FRONTEND_HTTP_PORT:-80}:80` | `wget -qO- http://localhost/` |

- All services: `restart: unless-stopped`
- `api` depends on `postgres` with `condition: service_healthy`
- Named volume `postgres_data` with `driver: local`
- Bridge network `delivery_network`
- Log rotation: `json-file` max-size 50m, max-file 5 on api and frontend

**Acceptance criteria**: `docker compose config` validates. Only port 80 exposed on host. All 3 healthchecks defined.

---

### Task 1.4 — Dockerfiles (api + frontend)

**Deliverables**: `api/Dockerfile`, `api/.dockerignore`, `frontend/Dockerfile`, `frontend/.dockerignore`.

**api/Dockerfile** (two-stage — DEPLOY-REQ-006–009):
- Stage 1 (`builder`): `python:3.12-slim` — install deps to `/install`
- Stage 2 (`runtime`): `python:3.12-slim` — copy deps, add `appuser` (non-root), `COPY` app
- `.env` is **never** `COPY`'d into the image (DEPLOY-REQ-009)

**frontend/Dockerfile** (multi-stage — DEPLOY-REQ-011):
- Stage 1 (`builder`): `node:20-alpine` — `npm ci` + `npm run build`
- Stage 2 (`runtime`): `nginx:alpine` — copy static dist only

**Acceptance criteria**: API image runs as `appuser` (not root). `.env` absent from image filesystem.

---

### Task 1.5 — api/entrypoint.sh

**Deliverables**: `api/entrypoint.sh`

```sh
#!/bin/sh
set -e                          # Any failure stops container (DEPLOY-REQ-022)
alembic upgrade head            # Migrations first
python -m app.seed              # Seed if empty
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 1 \                 # APScheduler requires single worker (DEPLOY-REQ-023)
  --no-access-log
```

**Acceptance criteria**: `set -e` present. `--workers 1` present. Alembic before seed, seed before Uvicorn.

---

### Task 1.6 — Alembic initialisation

**Deliverables**: `alembic.ini`, `alembic/env.py` (stub), `alembic/versions/` (empty).

Run `alembic init alembic` from `api/`. The `env.py` is stubbed here and completed in Task 6.1 once ORM models exist.

**Acceptance criteria**: `alembic current` runs without `ImportError`.

---

### Task 1.7 — .gitignore and .env.example stub

**Deliverables**: `.gitignore`, `.env.example` (minimal stub; completed in Task 7.1).

`.gitignore` must include: `.env`, `__pycache__/`, `.pytest_cache/`, `node_modules/`, `dist/`, `.scratch/`.

**Acceptance criteria**: `git check-ignore .env` returns `.env`. `.env.example` is committed to version control.

---

## Phase 2 — Domain Layer

**Goal**: Innermost layer — zero framework dependencies. Independently testable.  
**Arch ref**: ARCH-DOMAIN (entire document).  
**Constraint**: No `sqlalchemy`, `fastapi`, `httpx`, or `apscheduler` imports anywhere in `app/domain/`.

---

### Task 2.1 — Value objects: SemanticStatus and LifecycleGroup

**Deliverables**: `app/domain/value_objects/semantic_status.py`, `app/domain/value_objects/lifecycle_group.py`

**`SemanticStatus`** (10 values): `INFO_RECEIVED`, `IN_TRANSIT`, `OUT_FOR_DELIVERY`, `AWAITING_PICKUP`, `DELIVERED`, `DELIVERY_FAILED`, `EXCEPTION`, `NOT_FOUND`, `FROZEN`, `UNKNOWN`

**`PARCEL_CODE_TO_SEMANTIC`** mapping (authoritative; no other translation path):
```
0→DELIVERED  1→FROZEN  2→IN_TRANSIT  3→AWAITING_PICKUP  4→OUT_FOR_DELIVERY
5→NOT_FOUND  6→DELIVERY_FAILED  7→EXCEPTION  8→INFO_RECEIVED
```

**`normalize_status(parcel_code: int) → SemanticStatus`**:
- NEVER raises for any integer input (NORM-REQ-010)
- Unknown codes return `UNKNOWN`

**`LifecycleGroup`** (3 values): `ACTIVE`, `ATTENTION`, `TERMINAL`

| Group | Statuses |
|-------|---------|
| `ACTIVE` | INFO_RECEIVED, IN_TRANSIT, OUT_FOR_DELIVERY, AWAITING_PICKUP |
| `ATTENTION` | DELIVERY_FAILED, EXCEPTION, NOT_FOUND, UNKNOWN |
| `TERMINAL` | DELIVERED, FROZEN |

**`get_lifecycle_group(status: SemanticStatus) → LifecycleGroup`**:
- NEVER raises for any `SemanticStatus` value (NORM-REQ-011)

**Acceptance criteria**: 100% branch coverage on both functions (NORM-REQ-012). `normalize_status(99)` returns `UNKNOWN`. No external imports.

---

### Task 2.2 — Domain entities (5 dataclasses)

**Deliverables**: `app/domain/entities/delivery.py`, `delivery_event.py`, `status_history.py`, `user.py`, `poll_log.py`

All entities use Python `@dataclass`. No SQLAlchemy decorators. Key invariants:

| Entity | Critical invariants |
|--------|-------------------|
| `Delivery` | `timestamp_expected` preferred for sorting (DM-BR-024); `last_raw_response` not history |
| `DeliveryEvent` | `event_date_raw` NEVER parsed to timestamp (DM-BR-009/025) |
| `StatusHistory` | Immutable after creation (DM-BR-012); `detected_at` = poller time not carrier time |
| `User` | `password_hash` excluded from `__repr__`; `token_version` field present (GAP-001) |
| `PollLog` | Includes `PollOutcome` enum: `IN_PROGRESS`, `SUCCESS`, `PARTIAL`, `ERROR` |

**Acceptance criteria**: `User.__repr__` does not contain `password_hash` value. All field names match ARCH-DOMAIN §2 exactly. `from app.domain.entities.delivery import Delivery` imports with no framework dependencies.

---

### Task 2.3 — Repository ABCs (3 abstract base classes)

**Deliverables**: `app/domain/repositories/abstract_delivery_repository.py`, `abstract_user_repository.py`, `abstract_poll_log_repository.py`

**`AbstractDeliveryRepository`** — 8 methods:
- `get_snapshot() → dict[tuple[str,str], UUID]` — single query, O(1) lookup (POLL-REQ-015)
- `list_filtered(params) → tuple[list[Delivery], int]` — NULLs-last sort, parameterised LIKE
- `create_event(event) → Optional[DeliveryEvent]` — returns `None` on duplicate (DM-BR-007)
- + `get_by_id`, `create`, `update`, `get_events_for_delivery`, `create_status_history`, `get_status_history_for_delivery`

**`AbstractUserRepository`** — 6 methods including `increment_token_version()` (atomic, SEC-REQ-021)

**`AbstractPollLogRepository`** — 5 methods including `count_consecutive_errors()` (POLL-REQ-036)

**Acceptance criteria**: All methods decorated `@abstractmethod`. No SQLAlchemy, FastAPI, or httpx imports.

---

### Task 2.4 — Domain exceptions

**Deliverables**: `app/domain/exceptions.py`

8 exception classes under `DomainError` base:
`DeliveryNotFoundError`, `UserNotFoundError`, `InvalidCredentialsError` (generic — no username enumeration), `AccountDisabledError`, `TokenVersionMismatchError`, `InvalidStatusCodeError`, `AnomalousStatusTransitionError`

**Acceptance criteria**: `InvalidCredentialsError` message does not reveal whether username exists (API-REQ-006, SEC-REQ-008). No HTTP status codes. No FastAPI imports.

---

## Phase 3 — Application Layer

**Goal**: Use cases and orchestration. Imports domain only; never imports infrastructure or presentation.  
**Arch ref**: ARCH-APPLICATION (entire document).  
**Constraint**: No `sqlalchemy`, `fastapi`, `httpx`, `apscheduler` imports in `app/application/`.

---

### Task 3.1 — Application DTOs

**Deliverables**: `app/application/dtos/auth_dtos.py`, `delivery_dtos.py`, `system_dtos.py`

Key types:
- `DeliveryFilterParams` — `include_terminal: bool = False` default (API-REQ-010)
- `DeliverySummaryDTO` — includes `lifecycle_group: str` (derived, never stored — NORM-REQ-004)
- `DeliveryListDTO` — wraps `items`, `total`, `page`, `page_size`, `pages`
- `ParcelDeliveryDTO` / `ParcelEventDTO` — Parcel API response shapes
- `HealthDTO` — status: `healthy` | `degraded` | `unhealthy`

**Acceptance criteria**: `lifecycle_group` present on `DeliverySummaryDTO`. `DeliveryFilterParams` default `include_terminal=False`. No SQLAlchemy/FastAPI imports.

---

### Task 3.2 — External service interfaces (ABCs)

**Deliverables**: `app/application/services/interfaces.py`

4 abstract interfaces the application layer calls without knowing the concrete implementation:
- `AbstractParcelAPIClient` — `get_deliveries()`, `get_carriers()`
- `AbstractCarrierCache` — `get_carriers()` (sync), `refresh()` (async)
- `AbstractSchedulerState` — `is_running()`, `get_next_poll_at()`
- `AbstractDBHealthChecker` — `check()` with 3s timeout (API-REQ-016)

**Acceptance criteria**: No httpx, apscheduler, fastapi imports. Use cases reference these types via constructor injection.

---

### Task 3.3 — Auth use cases

**Deliverables**: `app/application/use_cases/auth/authenticate_user.py`, `refresh_token.py`, `logout_user.py`

**`AuthenticateUserUseCase.execute(credentials)`**:
1. Fetch user by username
2. If not found: run **dummy `passlib.verify()`** (constant-time; SEC-REQ-008) → raise `InvalidCredentialsError`
3. `passlib.verify(password, user.password_hash)` — failure → `InvalidCredentialsError`
4. `not user.is_active` → `AccountDisabledError`
5. `user_repo.update_last_login()` (API-REQ-007)
6. Return `user` entity

**`RefreshAccessTokenUseCase`**: validates `token_version` from refresh claims against DB (API-REQ-008)  
**`LogoutUserUseCase`**: atomically increments `token_version` (SEC-REQ-020–021, API-REQ-009)

**Acceptance criteria**: Dummy verify fires for unknown username. Inactive user raises `AccountDisabledError` not `InvalidCredentialsError`. `token_version` mismatch raises `TokenVersionMismatchError`.

---

### Task 3.4 — Delivery use cases

**Deliverables**: `app/application/use_cases/deliveries/get_deliveries.py`, `get_delivery_detail.py`

**`GetDeliveriesUseCase`**: fetches filtered page, derives `lifecycle_group` per delivery (NORM-REQ-004), page beyond total returns empty items (API-REQ-028)  
**`GetDeliveryDetailUseCase`**: fetches delivery + events (seq_num ASC) + history (detected_at ASC), raises `DeliveryNotFoundError` if missing (API-REQ-015)

**Acceptance criteria**: Missing `delivery_id` raises `DeliveryNotFoundError` (not 404 — presentation maps that). `lifecycle_group` derived, not stored.

---

### Task 3.5 — Polling use case (PollAndSyncUseCase)

**Deliverables**: `app/application/use_cases/polling/poll_and_sync.py`

The most complex use case. Four-phase execution — see ARCH-APPLICATION §4.6 for full spec.

**Phase 1**: Create `PollLog` with `outcome='in_progress'` before API call (DM-BR-018). Load snapshot (1 query, POLL-REQ-015).  
**Phase 2**: Call Parcel API. Map exceptions: 429→skip, 401→CRITICAL+skip, 5xx→error+skip. Empty list is valid (POLL-REQ-014).  
**Phase 3**: Sequential processing (POLL-REQ-021). For each delivery: NEW→INSERT delivery + StatusHistory(prev=NULL) + events. EXISTING→diff status, INSERT StatusHistory if changed, INSERT events ON CONFLICT DO NOTHING, always UPDATE `last_seen_at` (POLL-REQ-018). Per-delivery failure: rollback, log ERROR, continue (POLL-REQ-029).  
**Phase 4**: Separate transaction. `outcome='success'` if no errors, `'partial'` otherwise (POLL-REQ-030). `poll_log_repo.complete()`.

**Critical**: This use case NEVER raises. All errors are caught, logged with `poll_id`, and reflected in the PollLog.

**Acceptance criteria**: New delivery → `StatusHistory.previous_*` is `None`. Duplicate event → no error. Per-delivery failure → others continue. Anomalous terminal transition → logged WARNING, delivery still updated (NORM-REQ-005–006).

---

### Task 3.6 — System use cases

**Deliverables**: `app/application/use_cases/system/get_health.py`, `get_carriers.py`

**`GetHealthUseCase`**: aggregates DB health (3s timeout), poll log data, scheduler state. Returns `HealthDTO`. Status rules: `unhealthy` if DB down or scheduler stopped; `degraded` if `consecutive_errors ≥ 3` (POLL-REQ-036); `healthy` otherwise. NEVER raises.

**`GetCarriersUseCase`**: returns `carrier_cache.get_carriers()`. Never makes synchronous outbound call (API-REQ-019). Stale data served without error (API-REQ-020).

**Acceptance criteria**: `unhealthy` DTO returned (not exception) when DB unavailable. Carriers use case is synchronous and side-effect-free.

---

### Task 3.7 — Application exceptions

**Deliverables**: `app/application/exceptions.py`

Hierarchy: `ApplicationError` → `ParcelAPIError` → `ParcelRateLimitError`, `ParcelAuthError`, `ParcelServerError` (retryable), `ParcelResponseError`. Also `DatabaseUnavailableError`.

Presentation mapping documented (but implemented in Phase 5):

| Exception | HTTP Status | Code |
|-----------|:-----------:|------|
| `InvalidCredentialsError` | 401 | `INVALID_CREDENTIALS` |
| `AccountDisabledError` | 403 | `ACCOUNT_DISABLED` |
| `TokenVersionMismatchError` | 401 | `UNAUTHORIZED` |
| `DeliveryNotFoundError` | 404 | `NOT_FOUND` |
| `DatabaseUnavailableError` | 503 | `SERVICE_UNAVAILABLE` |

---

## Phase 4 — Infrastructure Layer

**Goal**: Concrete adapters — the only layer that imports SQLAlchemy, httpx, APScheduler.  
**Arch ref**: ARCH-INFRASTRUCTURE (entire document).  
**Critical**: ORM models are NOT domain entities. Mappers are the only boundary-crossing code.

---

### Task 4.1 — Async database engine and session factory

**Deliverables**: `app/infrastructure/database/engine.py`, `app/infrastructure/database/models/__init__.py` (with `Base`), `app/infrastructure/database/health_checker.py`

```python
engine = create_async_engine(
    settings.database_url,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,         # Detect stale connections after postgres restart
)
async_session_factory = async_sessionmaker(
    engine,
    expire_on_commit=False,     # Prevent lazy-load errors in async context
    autocommit=False,
    autoflush=False,
)
```

**Acceptance criteria**: `pool_pre_ping=True` and `expire_on_commit=False` present. `Base.metadata` defined and importable.

---

### Task 4.2 — SQLAlchemy ORM models (5 models)

**Deliverables**: 5 ORM model files in `app/infrastructure/database/models/`

All use SQLAlchemy 2.0 `mapped_column` / `Mapped` syntax. All datetimes use `TIMESTAMPTZ`. Relationships use `lazy="raise"` to prevent accidental N+1 queries.

| Model | Critical constraints |
|-------|---------------------|
| `DeliveryORM` | `UniqueConstraint(tracking_number, carrier_code)`, `JSONB` for `last_raw_response`, NULLS LAST index on `timestamp_expected` |
| `DeliveryEventORM` | `UniqueConstraint(delivery_id, event_description, event_date_raw)` — deduplication fingerprint |
| `UserORM` | `token_version: Integer NOT NULL DEFAULT 1` (GAP-001) |
| `PollLogORM` | `CheckConstraint("outcome IN ('in_progress','success','partial','error')")` |

**Acceptance criteria**: `Base.metadata.tables` contains all 5 tables when models imported. `token_version` column present on `users`. `uq_event_fingerprint` constraint present.

---

### Task 4.3 — Domain-ORM mappers (5 mappers)

**Deliverables**: 5 mapper files in `app/infrastructure/mappers/`

Each mapper provides `to_domain(orm) → entity` and `to_orm(entity) → orm`. They are the **only** code that crosses the ORM/entity boundary. No DB calls, no business logic.

Key conversions: `SemanticStatus(orm.semantic_status)` (str→enum), `PollOutcome(orm.outcome)` (str→enum), `Optional[SemanticStatus(orm.previous_semantic_status)]`.

**Acceptance criteria**: `DeliveryMapper.to_domain(orm_instance)` returns a `Delivery` dataclass (not SQLAlchemy object). Round-trip `to_domain(to_orm(entity))` produces entity with same field values. No DB session required to run mappers.

---

### Task 4.4 — SQLAlchemy repository implementations (3 repos)

**Deliverables**: 3 repository files in `app/infrastructure/database/repositories/`

Key implementations:

**`SQLAlchemyDeliveryRepository.get_snapshot()`** — single `SELECT tracking_number, carrier_code, id` query (POLL-REQ-015)

**`SQLAlchemyDeliveryRepository.list_filtered()`** — dynamic query builder:
- `include_terminal=False`: exclude TERMINAL statuses (API-REQ-010)
- `search`: parameterised `ilike()` with `bindparam` on description + tracking_number (SEC-REQ-058) — NO string interpolation
- Sort `timestamp_expected`: use `.nullslast()` (API-REQ-012)

**`SQLAlchemyDeliveryRepository.create_event()`** — `INSERT … ON CONFLICT DO NOTHING … RETURNING` — returns `None` if conflict (DM-BR-007)

**`SQLAlchemyUserRepository.increment_token_version()`** — single `UPDATE … RETURNING` (atomic, SEC-REQ-021)

**Acceptance criteria**: `get_snapshot()` issues exactly 1 DB query. `create_event()` called twice with same data → second returns `None`. Search uses parameterised LIKE (no string interpolation).

---

### Task 4.5 — Parcel API client and response schemas

**Deliverables**: `app/infrastructure/parcel_api/client.py`, `app/infrastructure/parcel_api/schemas.py`

**Configuration**: base URL `https://api.parcel.app`, endpoint `GET /external/deliveries/?filter_mode=recent`, header `api-key: <KEY>` (not `Authorization` — POLL-REQ-010), 30s timeout, `verify=True`.

**Retry logic** (POLL-REQ-026):
```
RETRY_DELAYS = [15, 60, 120]  seconds
429 → ParcelRateLimitError (non-retryable, immediate)
401 → ParcelAuthError (non-retryable, immediate)
5xx/network → retry with backoff; log WARNING with attempt number (POLL-REQ-027)
All retries exhausted → raise ParcelServerError
```

API key **never logged** at any level (POLL-REQ-033). `timestamp_expected` Unix epoch → UTC datetime. Raw date strings passed verbatim (DM-BR-025).

**Acceptance criteria**: HTTP 429 raises immediately (no retry). API key absent from all log output. Empty deliveries list returns without error. Timestamp epoch converted to timezone-aware UTC datetime.

---

### Task 4.6 — Carrier cache

**Deliverables**: `app/infrastructure/parcel_api/carrier_cache.py`

In-memory cache with 24h TTL. `get_carriers()` returns `cache_status='unavailable'` before first refresh, `'stale'` after TTL expiry — never raises (API-REQ-020). Failed `refresh()` retains existing data silently.

**Acceptance criteria**: `get_carriers()` makes no synchronous outbound HTTP call. Failed refresh retains previous data. `cache_status='stale'` returned after TTL expires.

---

### Task 4.7 — APScheduler integration

**Deliverables**: `app/infrastructure/scheduler/polling_scheduler.py`

```python
scheduler.add_job(
    func=_run_poll_cycle,
    trigger=IntervalTrigger(
        minutes=settings.poll_interval_minutes,
        jitter=settings.poll_jitter_seconds,   # ±30s — non-negotiable
    ),
    max_instances=1,    # overlapping poll dropped with WARNING (POLL-REQ-032)
    coalesce=True,
    misfire_grace_time=60,
)
```

**`_run_poll_cycle()`**: creates a fresh `AsyncSession` per cycle (separate from HTTP request sessions). **Not** called by the scheduler for cold-start — triggered via `asyncio.create_task()` from lifespan (POLL-REQ-003–004).

**`APSchedulerStateAdapter`**: wraps `AsyncIOScheduler` to implement `AbstractSchedulerState`.

**Shutdown**: `scheduler.shutdown(wait=True)` — allows in-progress poll to complete (POLL-REQ-002).

**Acceptance criteria**: `max_instances=1` present. `jitter` parameter set. Cold-start is `asyncio.create_task` (non-blocking). `APSchedulerStateAdapter.is_running()` delegates to `scheduler.running`.

---

## Phase 5 — Presentation Layer

**Goal**: FastAPI surface — the only layer that imports FastAPI.  
**Arch ref**: ARCH-PRESENTATION (entire document).

---

### Task 5.1 — pydantic-settings config (app/config.py)

**Deliverables**: `app/config.py`

`Settings(BaseSettings)` with all variables validated at import time. Key validators:

| Validator | Rule | Requirement |
|-----------|------|-------------|
| `jwt_secret_key` | `len ≥ 32` | SEC-REQ-010 |
| `access_token_expire_minutes` | `5 ≤ v ≤ 1440` | SEC-REQ-014 |
| `refresh_token_expire_days` | `1 ≤ v ≤ 30` | SEC-REQ-014 |
| `poll_interval_minutes` | `< 5` → clamp to 5 + WARNING | POLL-REQ-005 |
| `bcrypt_rounds` | `10 ≤ v ≤ 15` | SEC-REQ-002 |
| `https_enabled=True, cookie_secure=False` | log WARNING | SEC-REQ-044 |

`sync_database_url` property: replaces `postgresql+psycopg` with `postgresql+psycopg2`.  
`settings = Settings()` — singleton at module level; all layers import this instance.

**Acceptance criteria**: `Settings()` raises `ValidationError` if `JWT_SECRET_KEY < 32 chars` or `PARCEL_API_KEY` absent. `poll_interval_minutes < 5` clamped (not rejected).

---

### Task 5.2 — HTTP request/response schemas

**Deliverables**: `app/presentation/schemas/auth_schemas.py`, `delivery_schemas.py`, `system_schemas.py`

Key requirements:
- **All datetimes serialised as ISO 8601 UTC with `Z` suffix** — `"2025-01-16T14:30:00Z"` (API-REQ-013)
- `page_size: int = Field(20, ge=1, le=100)` (API-REQ-027)
- `DeliveryListQueryParams` usable as `Depends()` in route handlers
- Standard `ErrorResponse(error: ErrorBody)` envelope on all errors (API-REQ-005)

**Acceptance criteria**: All timestamp fields use `Z` suffix. `page_size` max=100 enforced. `ErrorResponse` structure matches standard envelope.

---

### Task 5.3 — JWT authentication (token creation and validation)

**Deliverables**: JWT functions + `get_current_user` dependency

**6-step validation chain** (SEC-REQ-015) — all failures return identical `401` (SEC-REQ-016):
1. Token present in `Authorization: Bearer` header
2. JWT signature valid
3. Not expired
4. `type` claim == `"access"` (rejects refresh tokens used on protected routes — SEC-REQ-012)
5. User exists and `is_active == True`
6. `user.token_version == payload["token_version"]` (SEC-REQ-017, API-REQ-004)

All validation failures logged at `INFO` level server-side with reason (SEC-REQ-059). Reason NOT disclosed in response body (SEC-REQ-016).

`oauth2_scheme = OAuth2PasswordBearer(auto_error=False)` — allows custom error envelope.

**Acceptance criteria**: Each of 6 failure modes returns identical 401 body. Refresh token used as access token → 401. Expired token → 401. `token_version` mismatch → 401.

---

### Task 5.4 — DI providers (dependencies.py)

**Deliverables**: `app/presentation/dependencies.py`

The architectural seam — wires application use cases to concrete infrastructure implementations:

```
get_async_session → get_delivery_repository → get_deliveries_use_case
                  → get_user_repository → get_authenticate_use_case
                  → get_poll_log_repository → get_health_use_case
get_carrier_cache (from app.state) → get_carriers_use_case
get_scheduler_state (APSchedulerStateAdapter) → get_health_use_case
```

Module-level `RateLimiter()` singleton (not created per-request).

**Acceptance criteria**: `app.dependency_overrides` can replace any provider for testing. `get_async_session` commits on success, rolls back on exception.

---

### Task 5.5 — Auth router

**Deliverables**: `app/presentation/routers/auth_router.py`

| Endpoint | Auth | Key behaviour |
|----------|:----:|---------------|
| `POST /api/auth/login` | ❌ | Rate limit check first → use case → httpOnly cookie (SEC-REQ-022–024) |
| `POST /api/auth/refresh` | ❌ (cookie) | Validates refresh cookie → returns new access token |
| `POST /api/auth/logout` | ✅ Bearer | Increments `token_version` → clears cookie → 204 |

Cookie spec: `httponly=True`, `samesite="strict"`, `path="/api/auth"`, `secure=settings.cookie_secure`.  
Rate limit: check before use case, record failure on `InvalidCredentialsError`, reset on success (SEC-REQ-037).

**Acceptance criteria**: Login success sets httpOnly cookie. Login failure and unknown username return identical 401 bodies. Cookie path is `/api/auth` (SEC-REQ-024). Logout returns 204.

---

### Task 5.6 — Deliveries and system routers

**Deliverables**: `app/presentation/routers/deliveries_router.py`, `system_router.py`

| Route | Auth | Notes |
|-------|:----:|-------|
| `GET /api/deliveries` | ✅ | Page beyond total → empty items (API-REQ-028) |
| `GET /api/deliveries/{id}` | ✅ | Not paginated (API-REQ-015); UUID validation → 422 |
| `GET /api/health` | ❌ | 503 only for `unhealthy`; 200 for `healthy` + `degraded` (API-REQ-017) |
| `GET /api/carriers` | ✅ | Cache only; no outbound call (API-REQ-019) |

**Acceptance criteria**: `GET /api/health` returns 200/503 without Bearer token. `GET /api/deliveries` returns 401 without token. Invalid UUID returns 422.

---

### Task 5.7 — Middleware, exception handlers, and app factory

**Deliverables**: `app/presentation/middleware/security_headers.py`, `app/presentation/middleware/rate_limiter.py`, `app/main.py`

**`SecurityHeadersMiddleware`** — adds to ALL responses (API-REQ-021, SEC-REQ-031):
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 0
Referrer-Policy: strict-origin-when-cross-origin
```
Removes `Server` header (SEC-REQ-034).

**`RateLimiter`** — sliding window, `WINDOW_SECONDS=900`, `MAX_FAILURES=10` (SEC-REQ-035). `asyncio.Lock` for thread safety.

**`generic_exception_handler`** — catches all unhandled exceptions, logs full traceback server-side, returns standard `INTERNAL_ERROR` envelope without stack trace (API-REQ-025).

**`create_app()` + `lifespan`** — full startup/shutdown sequence:
1. Create shared `httpx.AsyncClient` (keep-alive — POLL-REQ-012)
2. Initialise `CarrierCache`, background refresh
3. Initialise `ParcelAPIClient`
4. Create `AsyncIOScheduler`, register poll + carrier jobs
5. `scheduler.start()`
6. `asyncio.create_task(_run_poll_cycle(...))` — cold-start (POLL-REQ-003)

OpenAPI disabled in production (API-REQ-023). CORS added only in `development` (SEC-REQ-029–030).

**Acceptance criteria**: `/api/docs` returns 404 when `ENVIRONMENT=production`. Security headers present on all responses. `Server` header absent. 500 response contains standard envelope (no stack trace).

---

## Phase 6 — Database Migrations

**Goal**: Complete Alembic configuration and write the initial schema migration.  
**Arch ref**: ARCH-INFRASTRUCTURE §2.3, §9.

---

### Task 6.1 — Configure Alembic env.py

**Deliverables**: Completed `alembic/env.py`

```python
from app.config import settings
from app.infrastructure.database.models import Base
# Import all ORM models to register with Base.metadata
from app.infrastructure.database.models import (
    delivery_orm, delivery_event_orm, status_history_orm, user_orm, poll_log_orm
)

connectable = create_engine(settings.sync_database_url)  # psycopg2 for Alembic
context.configure(connection=connection, target_metadata=Base.metadata,
                  compare_type=True, compare_server_default=True)
```

**Acceptance criteria**: `alembic check` shows all 5 tables. `alembic current` runs without `ImportError` on fresh DB.

---

### Task 6.2 — Initial Alembic migration (all 5 tables)

**Deliverables**: `alembic/versions/0001_initial_schema.py`

Generated via `alembic revision --autogenerate -m "initial_schema"` then reviewed for:

| Table | Critical item to verify |
|-------|------------------------|
| `deliveries` | `JSONB` for `last_raw_response`; `NULLS LAST` index on `timestamp_expected` |
| `delivery_events` | `UniqueConstraint(delivery_id, event_description, event_date_raw)` = `uq_event_fingerprint` |
| `users` | `token_version INTEGER NOT NULL DEFAULT 1` (GAP-001) |
| `poll_logs` | `CheckConstraint("outcome IN ('in_progress','success','partial','error')")` |
| All | `TIMESTAMPTZ` (not `TIMESTAMP`); `UUID` type |

Downgrade must drop tables in dependency order: `delivery_events`, `status_history` → `deliveries` → `users`, `poll_logs`.

**Acceptance criteria**: `alembic upgrade head` creates all 5 tables on clean DB. `alembic downgrade base` drops all tables. `token_version` column present on `users`. `TIMESTAMPTZ` used throughout.

---

## Phase 7 — Configuration, Seed Script & Nginx

**Goal**: Complete operational configuration for production deployment.  
**Arch ref**: ARCH-PRESENTATION §2, ARCH-INFRASTRUCTURE §9, ARCH-OVERVIEW §6.

---

### Task 7.1 — Complete .env.example with all variables

**Deliverables**: `.env.example` (complete — updates the stub from task 1.7)

All variables from `Settings` with explanatory comments. Security-sensitive fields include warnings:
```
# IMPORTANT: Remove ADMIN_PASSWORD from .env after first container start
ADMIN_PASSWORD=changeme-minimum-12-chars
```
Generate `JWT_SECRET_KEY` guidance: `openssl rand -hex 32`

**Acceptance criteria**: Every `Settings` field has a corresponding variable. `cp .env.example .env` produces a valid starting configuration (operator fills secrets).

---

### Task 7.2 — Seed script (app/seed.py)

**Deliverables**: `app/seed.py`

Idempotent user creation (DM-MIG-004):
1. Count users — if `> 0`: log INFO, return 0 (idempotent)
2. If `admin_username` or `admin_password` absent: log CRITICAL, `sys.exit(1)` (DEPLOY-REQ-028)
3. If `len(password) < 12`: log CRITICAL, `sys.exit(1)` (SEC-REQ-005)
4. Hash with bcrypt at `settings.bcrypt_rounds` (SEC-REQ-001–003)
5. Insert `UserORM` with `token_version=1`
6. Log WARNING: "Remove ADMIN_PASSWORD from .env now" (SEC-REQ-004)

Password NEVER logged at any level (SEC-REQ-061).

**Acceptance criteria**: Empty DB + no creds → exits 1. Empty DB + creds → user created with bcrypt hash. Non-empty DB → no-op. Password not in any log output.

---

### Task 7.3 — Nginx configuration

**Deliverables**: `nginx/nginx.conf`, `nginx/nginx-https.conf`

**`nginx.conf`** (HTTP mode):
- `/` — `try_files` for SPA routing (DEPLOY-REQ-029–030)
- `/api/` — proxy to `api:8000` with `X-Real-IP` + `X-Forwarded-For` (DEPLOY-REQ-032)
- Static assets — `Cache-Control: public, immutable` 1-year expiry (DEPLOY-REQ-031)
- Security headers: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Content-Security-Policy: connect-src 'self'` (SEC-REQ-032–033)
- `server_tokens off` (SEC-REQ-034)

**`nginx-https.conf`** (HTTPS mode — DEPLOY-REQ-034):
- Port 80 → redirect to HTTPS (SEC-REQ-042)
- `ssl_protocols TLSv1.2 TLSv1.3` (SEC-REQ-042)
- `Strict-Transport-Security` header

**Acceptance criteria**: `/api/` requests proxied to `api:8000`. `X-Real-IP` forwarded. Security headers present. `server_tokens off`.

---

## Phase 8 — Testing

**Goal**: Establish test suite covering all layers with appropriate strategies.  
**Arch ref**: ARCH-DOMAIN §7, ARCH-APPLICATION §7, ARCH-INFRASTRUCTURE §10, ARCH-PRESENTATION §9.

---

### Task 8.1 — Test infrastructure setup

**Deliverables**: `tests/` directory tree, pytest config in `pyproject.toml`, root `conftest.py`

```
tests/
  unit/domain/           unit/application/
  integration/           integration/presentation/
```

`pyproject.toml`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "--cov=app --cov-branch --cov-report=term-missing"
```

Root `conftest.py` provides: `test_settings`, `mock_delivery_repo`, `mock_user_repo`, `mock_poll_log_repo`.

**Acceptance criteria**: `pytest tests/unit/` runs with no test database. `--co` shows all test files discoverable.

---

### Task 8.2 — Domain layer unit tests

**Deliverables**: `tests/unit/domain/test_value_objects.py`, `test_entities.py`, `test_exceptions.py`

**`test_value_objects.py`** — CRITICAL (NORM-REQ-012):
```python
@pytest.mark.parametrize("code,expected", [(0, DELIVERED), ..., (8, INFO_RECEIVED)])
def test_normalize_status_known_codes(code, expected): ...

@pytest.mark.parametrize("code", [-1, 9, 99, 1000])
def test_normalize_status_unknown_returns_unknown(code):
    assert normalize_status(code) == SemanticStatus.UNKNOWN

# All 10 SemanticStatus values tested for get_lifecycle_group()
```

**Acceptance criteria**: 100% branch coverage on `normalize_status()` and `get_lifecycle_group()`. `User.__repr__` does not contain `password_hash` value. Tests run with no DB or HTTP server.

---

### Task 8.3 — Application layer unit tests

**Deliverables**: 4 test files in `tests/unit/application/`

Priority scenarios (ARCH-APPLICATION §7):

| Use Case | Key test |
|----------|---------|
| `AuthenticateUserUseCase` | Dummy verify fires for unknown user (SEC-REQ-008) |
| `PollAndSyncUseCase` | New delivery → `StatusHistory.prev` is `None`; per-delivery failure continues; 429 skips cycle |
| `GetDeliveriesUseCase` | Page beyond total → empty list (not error) |
| `GetHealthUseCase` | `consecutive_errors ≥ 3` → `degraded`; DB down → `unhealthy` DTO (not exception) |

**Acceptance criteria**: All tests use mock repos (no real DB). Dummy verify confirmed to fire for unknown username.

---

### Task 8.4 — Infrastructure integration tests

**Deliverables**: `tests/integration/test_repositories.py`, `test_mappers.py`, `test_parcel_client.py`

Key integration tests:
- `get_snapshot()` issues exactly 1 DB query
- `create_event()` called twice → second returns `None`, DB count = 1 (DM-BR-007)
- `list_filtered()` NULL-last sort confirmed (API-REQ-012)
- `list_filtered()` search is parameterised LIKE (SQL injection attempt harmless)
- `increment_token_version()` is atomic
- `ParcelAPIClient`: 429 → no retry; 503 → 3 retries; API key absent from logs
- Mapper round-trips for all 5 entity types

**Acceptance criteria**: Tests pass with `TEST_DATABASE_URL` set. ON CONFLICT DO NOTHING confirmed. API key never in captured log output.

---

### Task 8.5 — Presentation layer integration tests

**Deliverables**: `tests/integration/presentation/` test files

Key tests using `AsyncClient` + `app.dependency_overrides`:
- Login success: verifies httpOnly cookie, `samesite=strict`, `path=/api/auth`
- Login failure (wrong password) vs unknown user: **identical 401 body** (API-REQ-006)
- Rate limit: 10 failures → 429 with `Retry-After` header (SEC-REQ-038–039); reset on success
- 6-step JWT chain: each of 6 failure modes returns identical 401
- Security headers: present on all 7 endpoints
- `ENVIRONMENT=production` → `/api/docs` returns 404 (API-REQ-023)
- 500 response: standard envelope, no stack trace (API-REQ-025)
- Health: 200 for `degraded`; 503 for `unhealthy` only (API-REQ-017)

**Acceptance criteria**: Two different 401 causes have identical response bodies. `/api/docs` returns 404 in production environment. All 7 endpoint responses include security headers.

---

## Requirement Coverage Summary

| Domain | Total Reqs | Phases Covering |
|--------|:-----------:|-----------------|
| Architecture (ADRs) | 6 | 1, 3, 5 |
| Data Model | 30 | 2, 4, 6 |
| Polling Service | 36 | 3.5, 4.5, 4.7 |
| Status Normalisation | 14 | 2.1, 3.4, 8.2 |
| REST API | 28 | 3, 5.5–5.6, 8.5 |
| Web Dashboard | 60 | (Frontend — separate scope) |
| Authentication & Security | 61 | 3.3, 5.3–5.5, 5.7, 7.2 |
| Deployment & Configuration | 48 | 1.3–1.5, 5.1, 7 |
| **Total backend** | **~223** | Phases 1–8 |

---

## Key Implementation Warnings

> **GAP-001**: `token_version` column is required on the `users` table (needed by JWT auth) but is missing from `02-data-model.md`. It must be added to `UserORM` (task 4.2) and the Alembic migration (task 6.2). The requirements document should be updated.

> **APScheduler + workers**: Uvicorn **must** be started with `--workers 1`. APScheduler's `AsyncIOScheduler` is not process-safe. This is non-negotiable (DEPLOY-REQ-023).

> **API Key logging**: The Parcel API key must NEVER appear in any log output at any log level (POLL-REQ-033). Use `SecretStr` in Settings and never call `.get_secret_value()` in logging paths.

> **Dummy verify**: `AuthenticateUserUseCase` **must** call `passlib.verify()` even when the username is not found, to prevent timing attacks that reveal valid usernames (SEC-REQ-008). This is easy to forget and must be covered by a test.

> **Poll jitter**: The `±30s` jitter on the APScheduler `IntervalTrigger` is non-negotiable. Do not remove it (ARCH-INFRASTRUCTURE §8).

---

*Produced from: All 5 architecture documents + `00-master-requirements.md`.*  
*283 requirements across 8 domains informed this plan.*  
*All ADRs ADR-001 through ADR-006 respected throughout.*
