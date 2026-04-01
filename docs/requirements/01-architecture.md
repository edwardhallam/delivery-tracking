# Architecture & Technology Stack

**Document ID**: ARCH-001  
**Plan Phase**: Phase 1  
**Status**: Approved  
**Project**: Delivery Tracking Web Service  

---

## 1. System Overview

The Delivery Tracking Web Service is a self-hosted, single-user web application that:

1. **Polls** the Parcel App API every 15 minutes for delivery updates
2. **Persists** full delivery history and event timelines to a relational database
3. **Normalizes** Parcel's integer status codes into semantic, human-readable states
4. **Exposes** a REST API consumed by a web dashboard
5. **Serves** a web dashboard showing upcoming deliveries, sender information, status, and expected delivery dates
6. **Protects** all access behind single-user credential authentication

---

## 2. Architecture Decisions

### ADR-001: Monorepo, Multi-Container

**Decision**: A single Git repository containing backend API, frontend dashboard, and Docker Compose configuration as separate top-level directories.

**Rationale**: Simplifies self-hosted deployment (one `docker compose up`), keeps configuration co-located, suitable for single-developer/single-user scope.

---

### ADR-002: Backend — Python 3.12 + FastAPI

**Decision**: Python 3.12 with FastAPI as the backend API framework.

**Rationale**:
- FastAPI provides automatic OpenAPI/Swagger documentation with zero overhead
- Native async support aligns with background polling without a separate worker process
- APScheduler integrates cleanly with FastAPI's lifespan for scheduled polling
- Pydantic v2 (bundled with FastAPI) enforces strict request/response schema validation
- Excellent Docker image availability (`python:3.12-slim`)
- Type annotations throughout improve maintainability

**Key Libraries**:
| Library | Version | Purpose |
|---------|---------|---------|
| `fastapi` | ≥0.111 | API framework |
| `uvicorn` | ≥0.29 | ASGI server |
| `sqlalchemy` | ≥2.0 | ORM (async) |
| `alembic` | ≥1.13 | Database migrations |
| `apscheduler` | ≥3.10 | Background polling scheduler |
| `httpx` | ≥0.27 | Async HTTP client (Parcel API calls) |
| `pydantic` | ≥2.0 | Schema validation |
| `pydantic-settings` | ≥2.0 | Environment-based configuration |
| `passlib[bcrypt]` | ≥1.7 | Password hashing |
| `python-jose[cryptography]` | ≥3.3 | JWT token creation/validation |
| `psycopg` | ≥3.1 | Async PostgreSQL driver |

---

### ADR-003: Database — PostgreSQL 16

**Decision**: PostgreSQL 16 as the primary persistence store.

**Rationale**:
- Full relational integrity for delivery → event → history relationships
- JSONB support for storing raw Parcel API responses alongside normalized data
- Excellent Docker support (`postgres:16-alpine`)
- Alembic migrations provide safe schema evolution
- Persistent volume mount ensures history survives container restarts

---

### ADR-004: Frontend — React 18 + TypeScript + Vite

**Decision**: React 18 with TypeScript, bundled by Vite, served by Nginx.

**Rationale**:
- TypeScript enforces API contract alignment with backend schemas
- Vite produces optimised static assets for Nginx serving
- React's component model suits the delivery list + detail view pattern
- Nginx serves the built SPA and reverse-proxies API requests (avoids CORS complexity)

**Key Libraries**:
| Library | Purpose |
|---------|---------|
| `react` + `react-dom` | UI framework |
| `typescript` | Type safety |
| `vite` | Build tool |
| `react-query` (TanStack Query) | API data fetching + caching |
| `react-router-dom` | Client-side routing |
| `axios` | HTTP client |

---

### ADR-005: Reverse Proxy — Nginx

**Decision**: Nginx serves the static React build and reverse-proxies `/api/*` to the FastAPI backend.

**Rationale**:
- Eliminates CORS entirely (same origin for UI and API)
- Single external port exposed (`80`, optionally `443`)
- Efficient static asset serving with caching headers
- Trivial SSL termination point when a certificate is available

---

### ADR-006: Orchestration — Docker Compose v2

**Decision**: Docker Compose v2 with three services.

**Rationale**: Minimal operational overhead for self-hosted deployment. Single command (`docker compose up -d`) to run the full stack.

---

## 3. Component Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Host Machine                         │
│                                                         │
│  ┌──────────────────────────────────────────────────┐   │
│  │              Docker Compose Stack                │   │
│  │                                                  │   │
│  │  ┌─────────────┐     ┌──────────────────────┐   │   │
│  │  │   frontend   │     │        api            │   │   │
│  │  │   (Nginx)    │────▶│   (FastAPI/Uvicorn)   │   │   │
│  │  │              │     │                      │   │   │
│  │  │ :80 (ext)    │     │ :8000 (internal)     │   │   │
│  │  │              │     │                      │   │   │
│  │  │ Serves SPA   │     │  ┌────────────────┐  │   │   │
│  │  │ Proxies /api │     │  │  APScheduler   │  │   │   │
│  │  └─────────────┘     │  │  (15-min poll) │  │   │   │
│  │                       │  └───────┬────────┘  │   │   │
│  │                       │          │           │   │   │
│  │                       └──────────┼───────────┘   │   │
│  │                                  │               │   │
│  │  ┌──────────────────┐            │               │   │
│  │  │      postgres     │◀───────────┘               │   │
│  │  │  (PostgreSQL 16)  │                            │   │
│  │  │                  │                            │   │
│  │  │  :5432 (int)     │                            │   │
│  │  │  /var/lib/data   │                            │   │
│  │  │  (volume mount)  │                            │   │
│  │  └──────────────────┘                            │   │
│  └──────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
                              │
                              ▼ (outbound HTTPS)
                   ┌──────────────────────┐
                   │  api.parcel.app       │
                   │  (External Parcel API)│
                   └──────────────────────┘
```

---

## 4. Service Definitions

### 4.1 `api` Service (FastAPI)

| Property | Value |
|----------|-------|
| Base Image | `python:3.12-slim` |
| Internal Port | `8000` |
| Responsibilities | REST API, JWT auth, polling scheduler, DB access |
| Depends On | `postgres` (health-check gated) |
| Environment | Via `.env` file / env vars |
| Volumes | None (stateless; DB handles persistence) |

**Internal Modules**:
```
api/
├── main.py              # FastAPI app factory, lifespan, scheduler startup
├── config.py            # Pydantic settings (env-based configuration)
├── database.py          # SQLAlchemy engine + session factory
├── models/              # SQLAlchemy ORM models
│   ├── delivery.py
│   ├── event.py
│   ├── status_history.py
│   └── user.py
├── schemas/             # Pydantic request/response schemas
├── routers/             # FastAPI route handlers
│   ├── auth.py
│   └── deliveries.py
├── services/            # Business logic
│   ├── parcel_client.py # Parcel API HTTP client
│   ├── polling.py       # Poll + diff + persist logic
│   └── normalization.py # Status code → SemanticStatus mapping
└── alembic/             # Database migration scripts
```

---

### 4.2 `postgres` Service (PostgreSQL 16)

| Property | Value |
|----------|-------|
| Base Image | `postgres:16-alpine` |
| Internal Port | `5432` |
| Responsibilities | Persistent data storage |
| Volumes | Named volume `postgres_data` → `/var/lib/postgresql/data` |
| Health Check | `pg_isready` |

---

### 4.3 `frontend` Service (Nginx + React SPA)

| Property | Value |
|----------|-------|
| Base Image | `nginx:alpine` (multi-stage build from `node:20-alpine`) |
| External Port | `80` (configurable) |
| Responsibilities | Serve React SPA, reverse-proxy `/api/*` to `api:8000` |
| Volumes | None (static assets baked into image) |

**Nginx Routing**:
```
GET /api/*        → proxy_pass http://api:8000
GET /*            → serve /usr/share/nginx/html (React SPA)
```

---

## 5. Data Flow

### 5.1 Polling Flow (Background, every 15 minutes)
```
APScheduler trigger
  → parcel_client.get_deliveries(filter_mode="recent")
  → Compare response to persisted state
  → For each changed delivery:
      → Upsert Delivery record
      → Append new DeliveryEvents
      → Record StatusHistory entry if status changed
  → Log poll result (success / error)
```

### 5.2 Dashboard Request Flow
```
Browser → Nginx (:80)
  → Static assets:  served directly from /usr/share/nginx/html
  → API requests:   proxied to FastAPI (:8000)
      → JWT validation middleware
      → Route handler
      → SQLAlchemy query → PostgreSQL
      → Pydantic response serialization
      → JSON response → Browser
```

### 5.3 Authentication Flow
```
Browser POST /api/auth/login {username, password}
  → bcrypt verify against stored hash
  → Issue JWT access token (short-lived, e.g. 60 min)
  → Issue JWT refresh token (long-lived, e.g. 7 days)
  → Client stores tokens (httpOnly cookie recommended)
  → All subsequent /api/* requests include Bearer token
  → FastAPI dependency validates token on every request
```

---

## 6. Environment Configuration

All runtime configuration via environment variables, managed via `.env` file (not committed to source control):

| Variable | Required | Description |
|----------|----------|-------------|
| `PARCEL_API_KEY` | ✅ | Parcel App API key from web.parcelapp.net |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `JWT_SECRET_KEY` | ✅ | Secret for JWT signing (min 32 chars, random) |
| `JWT_ALGORITHM` | No | JWT algorithm (default: `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | JWT access token TTL (default: `60`) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | JWT refresh token TTL (default: `7`) |
| `POLL_INTERVAL_MINUTES` | No | Polling interval (default: `15`) |
| `ADMIN_USERNAME` | ✅ (first run) | Initial admin username |
| `ADMIN_PASSWORD` | ✅ (first run) | Initial admin password (plaintext, hashed on first run) |

---

## 7. Repository Structure

```
delivery-tracking/
├── docker-compose.yml
├── .env.example
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── alembic.ini
│   └── app/
│       └── (see module layout above)
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   └── src/
└── docs/
    └── requirements/
        ├── 00-master-requirements.md
        ├── 01-architecture.md   ← this document
        └── ...
```

---

## 8. Non-Functional Constraints

| Constraint | Value |
|------------|-------|
| Parcel API rate limit | 20 req/hr → max 1 req/3 min; 15-min polling uses ~4 req/hr (safe) |
| Polling jitter | ±30s random jitter recommended to avoid exact-minute hammering |
| Database availability | Must be healthy before API starts (depends_on + healthcheck) |
| Response caching | Parcel API responses are server-cached; no benefit to polling faster |
| Cold start | On first start with no data, immediately poll and seed initial state |

---

*Source: User scoping input + Parcel API reference (//delivery-tracking/api-reference.md)*  
*Traceability: ADR-001 through ADR-006, all user scoping answers*
