# Architecture Overview
## Delivery Tracking Web Service

**Document ID**: ARCH-OVERVIEW  
**Status**: Draft  
**Addresses**: All requirements documents (`00-master` through `08-deployment`)  
**Layer Mapping**: All four Clean Architecture layers

---

## Summary

This document is the master architecture reference for the Delivery Tracking Web Service. It establishes the four Clean Architecture layers, the inward-only dependency rule, the canonical module structure, and the key design patterns applied throughout the codebase. All layer-specific design documents (`ARCH-DOMAIN`, `ARCH-APPLICATION`, `ARCH-INFRASTRUCTURE`, `ARCH-PRESENTATION`) are subordinate to and consistent with this document.

---

## 1. Architectural Philosophy

The service applies **Clean Architecture** (Robert C. Martin) adapted for a small, containerised FastAPI service. The governing rule is:

> **Dependencies flow inward only.** Outer layers may import from inner layers; inner layers never import from outer ones.

This is not academic ceremony — it produces a specific, concrete benefit for this project: the domain logic and use cases can be unit-tested without a running database, a running Parcel API, or a running FastAPI server. The infrastructure and presentation are swappable concerns.

### Why Clean Architecture for a Small Service?

The service is small today (283 requirements, single user) but has a long operational lifetime and deferred features (notifications, password change UI, multi-user). Clean Architecture's layering makes those future extensions safe: new use cases do not require touching domain entities; new repository implementations do not require touching business logic. The cost is modest — a handful of extra files and explicit interfaces. The benefit is a codebase where every piece has one obvious home.

---

## 2. The Four Layers

```
┌─────────────────────────────────────────────────────────────┐
│  PRESENTATION  (FastAPI routers, schemas, DI wiring)        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │  INFRASTRUCTURE  (SQLAlchemy, httpx, APScheduler)   │   │
│  │                                                     │   │
│  │  ┌───────────────────────────────────────────────┐  │   │
│  │  │  APPLICATION  (Use cases, DTOs, services)     │  │   │
│  │  │                                               │  │   │
│  │  │  ┌─────────────────────────────────────────┐  │  │   │
│  │  │  │  DOMAIN  (Entities, Value Objects,      │  │  │   │
│  │  │  │           Repository ABCs, Exceptions)  │  │  │   │
│  │  │  └─────────────────────────────────────────┘  │  │   │
│  │  └───────────────────────────────────────────────┘  │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘

          Arrows point INWARD only: each layer
          may import from the layer inside it.
```

### Layer Summaries

| Layer | Package | Knows About | Must NOT Import |
|-------|---------|-------------|-----------------|
| **Domain** | `app.domain` | Nothing outside itself | SQLAlchemy, FastAPI, httpx, APScheduler, Pydantic models |
| **Application** | `app.application` | Domain only | SQLAlchemy, FastAPI, httpx, APScheduler |
| **Infrastructure** | `app.infrastructure` | Application + Domain | FastAPI, presentation schemas |
| **Presentation** | `app.presentation` | Application + Domain | SQLAlchemy internals, httpx, APScheduler |

---

## 3. Canonical Module Structure

The following structure supersedes the flat `models/`, `schemas/`, `routers/`, `services/` layout sketched in `01-architecture.md`. That sketch reflected the technology concerns; this structure reflects architectural boundaries. See §8 for the rationale.

```
api/
├── Dockerfile
├── entrypoint.sh
├── requirements.txt
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 0001_initial_schema.py
└── app/
    ├── main.py                          # App factory + lifespan
    ├── config.py                        # pydantic-settings environment config
    │
    ├── domain/                          # Layer 1 — innermost; zero framework deps
    │   ├── __init__.py
    │   ├── entities/
    │   │   ├── __init__.py
    │   │   ├── delivery.py              # Delivery dataclass / Pydantic base model
    │   │   ├── delivery_event.py        # DeliveryEvent
    │   │   ├── status_history.py        # StatusHistory
    │   │   ├── user.py                  # User
    │   │   └── poll_log.py              # PollLog
    │   ├── value_objects/
    │   │   ├── __init__.py
    │   │   ├── semantic_status.py       # SemanticStatus enum + normalize_status()
    │   │   └── lifecycle_group.py       # LifecycleGroup enum + get_lifecycle_group()
    │   ├── repositories/
    │   │   ├── __init__.py
    │   │   ├── abstract_delivery_repository.py
    │   │   ├── abstract_user_repository.py
    │   │   └── abstract_poll_log_repository.py
    │   └── exceptions.py                # Domain exceptions
    │
    ├── application/                     # Layer 2 — use cases; depends on domain only
    │   ├── __init__.py
    │   ├── use_cases/
    │   │   ├── __init__.py
    │   │   ├── auth/
    │   │   │   ├── authenticate_user.py
    │   │   │   ├── refresh_token.py
    │   │   │   └── logout_user.py
    │   │   ├── deliveries/
    │   │   │   ├── get_deliveries.py
    │   │   │   └── get_delivery_detail.py
    │   │   ├── polling/
    │   │   │   └── poll_and_sync.py
    │   │   └── system/
    │   │       ├── get_health.py
    │   │       └── get_carriers.py
    │   ├── dtos/
    │   │   ├── __init__.py
    │   │   ├── auth_dtos.py
    │   │   ├── delivery_dtos.py
    │   │   └── system_dtos.py
    │   └── exceptions.py                # Application exceptions
    │
    ├── infrastructure/                  # Layer 3 — concrete adapters
    │   ├── __init__.py
    │   ├── database/
    │   │   ├── __init__.py
    │   │   ├── engine.py                # Async SQLAlchemy engine + session factory
    │   │   ├── models/
    │   │   │   ├── __init__.py
    │   │   │   ├── delivery_orm.py      # DeliveryORM (SQLAlchemy mapped class)
    │   │   │   ├── delivery_event_orm.py
    │   │   │   ├── status_history_orm.py
    │   │   │   ├── user_orm.py
    │   │   │   └── poll_log_orm.py
    │   │   └── repositories/
    │   │       ├── __init__.py
    │   │       ├── sqlalchemy_delivery_repository.py
    │   │       ├── sqlalchemy_user_repository.py
    │   │       └── sqlalchemy_poll_log_repository.py
    │   ├── mappers/
    │   │   ├── __init__.py
    │   │   ├── delivery_mapper.py       # DeliveryORM ↔ Delivery domain entity
    │   │   ├── delivery_event_mapper.py
    │   │   ├── status_history_mapper.py
    │   │   ├── user_mapper.py
    │   │   └── poll_log_mapper.py
    │   ├── parcel_api/
    │   │   ├── __init__.py
    │   │   ├── client.py                # ParcelAPIClient (httpx-based)
    │   │   ├── schemas.py               # Pydantic models for Parcel API responses
    │   │   └── carrier_cache.py         # CarrierCache — in-memory, 24h TTL
    │   └── scheduler/
    │       ├── __init__.py
    │       └── polling_scheduler.py     # APScheduler setup + lifespan integration
    │
    └── presentation/                    # Layer 4 — outermost; FastAPI
        ├── __init__.py
        ├── routers/
        │   ├── __init__.py
        │   ├── auth_router.py
        │   ├── deliveries_router.py
        │   └── system_router.py
        ├── schemas/
        │   ├── __init__.py
        │   ├── auth_schemas.py          # HTTP request/response models
        │   ├── delivery_schemas.py
        │   └── system_schemas.py
        ├── middleware/
        │   ├── __init__.py
        │   ├── security_headers.py      # X-Content-Type-Options, X-Frame-Options, etc.
        │   └── rate_limiter.py          # In-memory login rate limiter
        └── dependencies.py             # FastAPI Depends() DI providers
```

---

## 4. The Dependency Rule in Practice

### What "inward only" means in Python imports

```python
# ✅ ALLOWED — presentation imports application use case
# app/presentation/routers/deliveries_router.py
from app.application.use_cases.deliveries.get_deliveries import GetDeliveriesUseCase

# ✅ ALLOWED — infrastructure imports domain interface
# app/infrastructure/database/repositories/sqlalchemy_delivery_repository.py
from app.domain.repositories.abstract_delivery_repository import AbstractDeliveryRepository

# ✅ ALLOWED — application imports domain entity
# app/application/use_cases/deliveries/get_deliveries.py
from app.domain.entities.delivery import Delivery

# ❌ FORBIDDEN — domain imports infrastructure (ORM)
# app/domain/entities/delivery.py
from sqlalchemy import Column  # NEVER

# ❌ FORBIDDEN — application imports presentation
# app/application/use_cases/deliveries/get_deliveries.py
from fastapi import HTTPException  # NEVER

# ❌ FORBIDDEN — domain imports application
# app/domain/repositories/abstract_delivery_repository.py
from app.application.dtos.delivery_dtos import DeliveryFilterDTO  # NEVER
```

### The test payoff

Because the domain and application layers have no framework dependencies, their unit tests require no test client, no database fixture, and no mock HTTP server — only pure Python mocks of the repository interfaces:

```python
# Testing PollAndSyncUseCase with no database or Parcel API
async def test_poll_detects_new_delivery():
    mock_repo = MockDeliveryRepository()  # in-memory implementation of the ABC
    mock_poll_log_repo = MockPollLogRepository()
    mock_parcel_client = MockParcelClient(returns=[fake_delivery_data()])

    use_case = PollAndSyncUseCase(
        delivery_repo=mock_repo,
        poll_log_repo=mock_poll_log_repo,
        parcel_client=mock_parcel_client,
    )
    await use_case.execute()

    assert len(mock_repo.deliveries) == 1
```

---

## 5. Key Design Patterns

### 5.1 Repository Pattern (Domain → Infrastructure boundary)

Domain repository interfaces are **abstract base classes** (`abc.ABC` + `@abstractmethod`). They define the persistence contract in domain terms — no SQLAlchemy, no SQL, no connection strings.

Infrastructure provides the concrete implementations. The application layer uses only the abstract interface. The presentation layer wires the concrete to the abstract via `Depends()`.

```
Domain ABC  ←  Application uses  ←  Presentation wires
    ↑                                       ↓
Infrastructure implements          Concrete injected via Depends()
```

### 5.2 Use Case Pattern (Application layer)

Each use case is a single class with a single `execute()` (or `async execute()`) method. It:
- Receives its dependencies (repositories, external clients) via constructor injection
- Contains all orchestration logic for one business operation
- Returns a DTO, not a domain entity or an ORM object
- Raises application exceptions (not HTTP exceptions) on failure

This keeps the application layer testable and the presentation layer thin (routers translate HTTP → use case input, use case output → HTTP response).

### 5.3 Entity / ORM Separation (Infrastructure boundary)

Domain entities are **not** SQLAlchemy models. SQLAlchemy ORM classes live exclusively in `infrastructure/database/models/`. Mapper functions translate between the two at the infrastructure boundary.

```
Domain Entity (pure Python)  ←→  Mapper  ←→  ORM Model (SQLAlchemy)
```

This is critical: SQLAlchemy column metadata, relationships, and `__tablename__` declarations must never bleed into the domain layer. Domain entities remain independently importable and testable.

### 5.4 FastAPI Dependency Injection

Presentation owns the wiring. No layer below presentation knows that FastAPI exists. Use cases receive repository interfaces via constructor injection; `Depends()` provides the concrete infrastructure implementations.

```python
# app/presentation/dependencies.py
async def get_delivery_repository(
    session: AsyncSession = Depends(get_async_session)
) -> AbstractDeliveryRepository:
    return SQLAlchemyDeliveryRepository(session)

async def get_deliveries_use_case(
    repo: AbstractDeliveryRepository = Depends(get_delivery_repository),
    user_repo: AbstractUserRepository = Depends(get_user_repository),
) -> GetDeliveriesUseCase:
    return GetDeliveriesUseCase(delivery_repo=repo)
```

### 5.5 Status Normalisation (Domain layer)

`SemanticStatus` and `LifecycleGroup` are **domain value objects** — pure Python enums with no external dependencies. The `normalize_status()` and `get_lifecycle_group()` functions are pure domain functions: deterministic, side-effect-free, and independently testable. They live in `app.domain.value_objects`, not in a `services/` directory.

`LifecycleGroup` is **never stored** in the database (NORM-REQ-004). It is derived at serialisation time in the presentation layer by calling `get_lifecycle_group(delivery.semantic_status)`.

---

## 6. Application Startup Sequence

The startup sequence is implemented in `main.py` via the FastAPI `lifespan` async context manager. The strict ordering is required by multiple requirements (DEPLOY-REQ-021, DEPLOY-REQ-022, POLL-REQ-001).

```
Container starts
│
├─ entrypoint.sh (set -e — any failure aborts)
│   ├─ alembic upgrade head          (schema migrations)
│   └─ python seed.py                (create user if users count == 0)
│
└─ uvicorn app.main:app --workers 1  (DEPLOY-REQ-023: single worker for APScheduler)
    │
    └─ FastAPI lifespan startup:
        ├─ 1. Validate all required secrets and config ranges
        │      (fails CRITICAL + exit if JWT_SECRET_KEY < 32 chars, etc.)
        ├─ 2. Initialise async SQLAlchemy engine + session factory
        ├─ 3. Initialise httpx AsyncClient (shared across poll cycles)
        ├─ 4. Initialise CarrierCache; fetch carriers from Parcel API (best-effort)
        ├─ 5. Initialise APScheduler with IntervalTrigger (15 min ± 30s jitter)
        ├─ 6. Start APScheduler
        ├─ 7. Trigger immediate cold-start poll (POLL-REQ-003)
        │      (runs in background; HTTP serving begins in parallel)
        └─ 8. Yield → application serves HTTP requests
```

**Shutdown** (reverse):
```
└─ FastAPI lifespan teardown:
    ├─ 1. Shut down APScheduler gracefully (wait up to 30s for in-progress poll)
    ├─ 2. Close httpx AsyncClient
    └─ 3. Dispose SQLAlchemy engine (close all connections)
```

---

## 7. Data Flow Narratives

### 7.1 Polling Flow (every 15 minutes ± 30s jitter)

```
APScheduler trigger (POLL-REQ-032: max_instances=1; overlapping poll dropped)
  │
  ├─ PollAndSyncUseCase.execute()
  │   ├─ poll_log_repo.create_in_progress() → poll_id
  │   ├─ parcel_client.get_deliveries()      [httpx; 30s timeout]
  │   │   ├─ HTTP 429 → skip cycle, log WARNING                (POLL-REQ-024)
  │   │   ├─ HTTP 401 → log CRITICAL, skip cycle               (POLL-REQ-025)
  │   │   ├─ HTTP 5xx → exponential backoff (15s/60s/120s/×3)  (POLL-REQ-026)
  │   │   └─ HTTP 200, success=true → list[ParcelDeliveryDTO]
  │   ├─ delivery_repo.get_snapshot()        [single query, no N+1]
  │   ├─ For each delivery in response (sequential, POLL-REQ-021):
  │   │   ├─ NEW (not in snapshot):
  │   │   │   └─ [transaction] INSERT delivery + StatusHistory(prev=NULL) + events
  │   │   └─ EXISTING (in snapshot):
  │   │       └─ [transaction] diff status → INSERT StatusHistory if changed
  │   │                        INSERT events ON CONFLICT DO NOTHING
  │   │                        UPDATE delivery (always, incl. last_seen_at)
  │   └─ poll_log_repo.complete(poll_id, outcome, counters)
  │       [separate transaction, POLL-REQ-020]
```

### 7.2 Dashboard API Request Flow

```
Browser → Nginx (:80) → FastAPI (:8000)
  │
  ├─ SecurityHeadersMiddleware (adds X-Content-Type-Options, X-Frame-Options, etc.)
  ├─ Route matched → router handler called
  ├─ Depends(get_current_user):
  │   ├─ Extract Bearer token from Authorization header
  │   ├─ Validate 6-step chain (SEC-REQ-015):
  │   │   1. Header format valid
  │   │   2. JWT signature valid
  │   │   3. Not expired
  │   │   4. type == "access"
  │   │   5. User exists + is_active == true
  │   │   6. token_version matches DB
  │   └─ Returns User domain entity
  ├─ Route handler calls use case:
  │   GetDeliveriesUseCase.execute(filter_dto)
  │     → delivery_repo.list_filtered(filter_dto)  [parameterised SQL LIKE for search]
  │     → returns list[DeliveryDTO]
  ├─ Router maps DTO → HTTP response schema
  └─ JSON response → Nginx → Browser
```

### 7.3 Authentication Flow

```
POST /api/auth/login {username, password}
  │
  ├─ RateLimiterMiddleware: check IP failed-attempt counter (SEC-REQ-035)
  │   └─ ≥ 10 failures in 15 min → 429 RATE_LIMITED (with Retry-After header)
  ├─ AuthenticateUserUseCase.execute(credentials_dto):
  │   ├─ user_repo.get_by_username(username)
  │   │   └─ Not found: dummy bcrypt verify (constant-time) → 401 INVALID_CREDENTIALS
  │   ├─ passlib.verify(password, user.password_hash)
  │   │   └─ Fail → 401 INVALID_CREDENTIALS; increment IP failure counter
  │   ├─ user.is_active check → 403 ACCOUNT_DISABLED
  │   ├─ user_repo.update_last_login(user.id)
  │   └─ returns TokenPairDTO(access_token, refresh_token, token_version)
  ├─ Router issues JWT access token + refresh token
  └─ Sets httpOnly SameSite=Strict cookie at Path=/api/auth; returns access token in body
```

---

## 8. Cross-Cutting Concerns

### 8.1 Configuration (`config.py`)

`pydantic-settings` `Settings` class reads all environment variables and validates them at import time. Startup validation logic (key length checks, range checks) is encoded as Pydantic validators:

| Variable Group | Validated At Startup |
|----------------|---------------------|
| `PARCEL_API_KEY` (required, non-empty) | ✅ |
| `DATABASE_URL` (required) | ✅ |
| `JWT_SECRET_KEY` (required, ≥ 32 chars) | ✅ |
| `ACCESS_TOKEN_EXPIRE_MINUTES` (5–1440) | ✅ |
| `REFRESH_TOKEN_EXPIRE_DAYS` (1–30) | ✅ |
| `POLL_INTERVAL_MINUTES` (≥ 5; enforces minimum) | ✅ |
| `BCRYPT_ROUNDS` (10–15) | ✅ |
| `HTTPS_ENABLED` / `COOKIE_SECURE` consistency | ✅ (warning if HTTPS=true, COOKIE_SECURE=false) |
| `ENVIRONMENT` (`development` | `production`) | ✅ |

A `Settings` instance is created once at module import. All layers receive it via constructor injection or `Depends()` — never via a global import (this keeps tests able to substitute a test config).

### 8.2 Logging

Structured logging via Python's `logging` module (JSON formatter recommended for production). Every poll cycle log entry includes `poll_id` (the `PollLog.id` UUID) for correlation. The API key **never** appears in logs at any level (POLL-REQ-033).

Log levels:
- `DEBUG` — Parcel API call details, SQL queries
- `INFO` — Poll cycle start/end, new deliveries found, auth events, security audit trail
- `WARNING` — Retryable errors, rate limit hits, anomalous status transitions, overlapping poll skip
- `ERROR` — Individual delivery processing failures, DB unavailability during poll
- `CRITICAL` — Auth failure (401 from Parcel), missing required secrets, JWT secret too short

### 8.3 Error Handling

A global FastAPI exception handler converts all unhandled exceptions to the standard error envelope (API-REQ-025):

```json
{
  "error": { "code": "INTERNAL_ERROR", "message": "An unexpected error occurred", "details": null }
}
```

Application exceptions are mapped to HTTP status codes in the presentation layer (routers or a dedicated exception handler). Domain exceptions bubble up through the application layer and are caught by presentation. No stack traces are ever serialised to responses.

### 8.4 Database Sessions

SQLAlchemy async sessions are created per-request (not per-application) via a dependency:

```python
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
```

Each request gets a fresh session; the session is closed (and connection returned to the pool) after the response is sent. This is safe for the single-worker deployment (DEPLOY-REQ-023).

For the polling service, the `PollAndSyncUseCase` receives its own session injected via the scheduler integration — not from the per-request factory. This is handled in `infrastructure/scheduler/polling_scheduler.py`.

---

## 9. Known Gaps and Conflicts

### GAP-001: `token_version` Column Missing from Data Model

**Source**: `05-rest-api.md` §2 documents `token_version INTEGER NOT NULL DEFAULT 1` as a required claim in JWT tokens, with a server-side validation step that reads `users.token_version` from the database on every authenticated request (SEC-REQ-017, API-REQ-004).

**Problem**: `02-data-model.md` does not include this column in the `users` table specification.

**Resolution**: The architecture treats `token_version` as a required field on the `User` entity and `users` ORM model. It must be added to the initial Alembic migration. The data model requirements document should be updated to include this field.

**Impact**: `DM-MIG-003` (initial migration creates all tables) must include `token_version INTEGER NOT NULL DEFAULT 1` on the `users` table.

### GAP-002: Module Structure Departure from `01-architecture.md`

**Source**: `01-architecture.md` §4.1 suggests a flat `models/`, `schemas/`, `routers/`, `services/` layout.

**Resolution**: This architecture adopts the four-layer Clean Architecture structure (`domain/`, `application/`, `infrastructure/`, `presentation/`) instead. The flat structure conflates infrastructure concerns (`models/` = ORM) with domain concerns (entities), and conflates all business logic into `services/` without separation of concerns. The Clean Architecture structure produces testable layers with explicit dependency boundaries. No requirements are violated by this choice — the requirements are technology-level, not directory-level.

---

## 10. Document Index

| Document | Contents | Status |
|----------|----------|--------|
| **This document** | System overview, layers, patterns, data flows, gaps | Draft |
| [`ARCH-DOMAIN.md`](./ARCH-DOMAIN.md) | Domain entities, value objects, repository ABCs, domain exceptions | Draft |
| [`ARCH-APPLICATION.md`](./ARCH-APPLICATION.md) | Use cases, DTOs, application exceptions | Draft |
| [`ARCH-INFRASTRUCTURE.md`](./ARCH-INFRASTRUCTURE.md) | ORM models, repositories, mappers, Parcel client, scheduler | Draft |
| [`ARCH-PRESENTATION.md`](./ARCH-PRESENTATION.md) | Routers, schemas, DI providers, middleware, app factory | Draft |

---

*Requirements traceability: All 283 requirements across 8 domains informed this document.*  
*ADRs ADR-001 through ADR-006 are respected throughout. No ADR is revisited.*  
*Produced from: `00-master-requirements.md`, `01-architecture.md`, `02-data-model.md`, `03-polling-service.md`, `04-status-normalization.md`, `05-rest-api.md`, `07-auth-security.md`, `08-deployment.md`*
