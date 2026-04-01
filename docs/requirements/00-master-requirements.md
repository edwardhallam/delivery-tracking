# Master Requirements Document
## Delivery Tracking Web Service

**Document ID**: MASTER-001  
**Version**: 1.0  
**Status**: Draft — Awaiting Review  
**Project**: Delivery Tracking Web Service (Greenfield)  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Context & Goals](#2-system-context--goals)
3. [Scope](#3-scope)
4. [Architecture Overview](#4-architecture-overview)
5. [Requirements Catalogue](#5-requirements-catalogue)
6. [Traceability Matrix](#6-traceability-matrix)
7. [Key Assumptions](#7-key-assumptions)
8. [Open Questions & Deferred Features](#8-open-questions--deferred-features)
9. [Document Index](#9-document-index)

---

## 1. Executive Summary

The Delivery Tracking Web Service is a **self-hosted, single-user web application** that provides a consolidated dashboard for tracking parcels managed through the [Parcel App](https://parcelapp.net). It wraps the Parcel App's read-only external API, adding persistent history, normalised status reporting, and a purpose-built web interface.

### Why it exists

The Parcel App API provides cached delivery data for integration with platforms like Home Assistant. It has no built-in web dashboard, no persistent history beyond what the app stores, and its status codes are integers requiring interpretation. This service fills those gaps.

### What it does

| Capability | Description |
|-----------|-------------|
| **Background polling** | Calls the Parcel API every 15 minutes, well within the 20 req/hr rate limit |
| **Persistent history** | Retains every delivery, every tracking event, and every status change indefinitely |
| **Status normalisation** | Translates Parcel's integer status codes (0–8) into semantic, human-readable states |
| **REST API** | Exposes a typed, authenticated REST API consumed by the dashboard |
| **Web dashboard** | Delivery list sorted by expected date with filtering, search, and detail views |
| **Single-user auth** | Credential-protected access with JWT tokens and instant session invalidation |
| **Docker deployment** | Starts with a single `docker compose up -d`; no external dependencies |

### Technology Stack at a Glance

| Layer | Technology |
|-------|-----------|
| Backend API + Scheduler | Python 3.12 · FastAPI · APScheduler · SQLAlchemy 2.0 (async) |
| Database | PostgreSQL 16 · Alembic migrations |
| Frontend | React 18 · TypeScript · Vite · TanStack Query · Tailwind CSS · shadcn/ui |
| Web Server / Proxy | Nginx (serves SPA + reverse-proxies `/api/*`) |
| Deployment | Docker Compose v2 · Three services · Single named volume |

### Requirement Counts

| Domain | Total | Must Have | Should Have | Could Have |
|--------|------:|:---------:|:-----------:|:----------:|
| Architecture | 6 | 6 | 0 | 0 |
| Data Model | 30 | 25 | 5 | 0 |
| Polling Service | 36 | 26 | 10 | 0 |
| Status Normalisation | 14 | 9 | 5 | 0 |
| REST API | 28 | 21 | 7 | 0 |
| Web Dashboard | 60 | 26 | 32 | 2 |
| Authentication & Security | 61 | 47 | 14 | 0 |
| Deployment & Configuration | 48 | 26 | 19 | 3 |
| **Total** | **283** | **186** | **92** | **5** |

---

## 2. System Context & Goals

### Inputs

| Input | Description |
|-------|-------------|
| Parcel App API | External read-only REST API. Single endpoint: `GET /external/deliveries/?filter_mode=recent`. Rate limited to 20 req/hr. Responses are server-cached. |
| Operator configuration | Parcel API key, admin credentials, JWT secret — supplied via `.env` file |

### Outputs

| Output | Consumer |
|--------|---------|
| Web dashboard | Human operator (single user) via browser |
| REST API | Web dashboard (the only API consumer) |
| Poll logs | Operator visibility via `docker compose logs api` |

### System Context Diagram

```
                    ┌──────────────────────────────┐
                    │         Operator               │
                    │         (Browser)              │
                    └──────────────┬───────────────┘
                                   │ HTTP :80
                                   ▼
                    ┌──────────────────────────────┐
                    │    Docker Compose Stack        │
                    │                              │
                    │  ┌──────────┐  ┌──────────┐  │
                    │  │frontend  │  │   api    │  │
                    │  │  Nginx   │─▶│ FastAPI  │  │
                    │  └──────────┘  └────┬─────┘  │
                    │                     │        │
                    │              ┌──────▼──────┐  │
                    │              │  postgres   │  │
                    │              │    PG 16    │  │
                    │              └─────────────┘  │
                    └──────────────────┬───────────┘
                                       │ HTTPS (outbound)
                                       ▼
                    ┌──────────────────────────────┐
                    │      api.parcel.app            │
                    │  (External Parcel API)         │
                    └──────────────────────────────┘
```

---

## 3. Scope

### 3.1 In Scope

| Area | What is included |
|------|-----------------|
| Delivery tracking | All deliveries returned by the Parcel API `recent` filter |
| Status normalisation | All 9 Parcel status codes (0–8) plus an `UNKNOWN` sentinel |
| Persistent history | Indefinite retention of deliveries, events, status changes, poll logs |
| Web dashboard | Login, delivery list (filter/sort/search), delivery detail (events + history) |
| REST API | 7 endpoints: auth (login/refresh/logout), deliveries (list/detail), health, carriers |
| Authentication | Single-user credentials; JWT access + httpOnly refresh cookie |
| Docker deployment | Three-service Compose stack; single `.env` configuration |
| HTTPS support | Optional; operator provides certificate via volume mount |

### 3.2 Out of Scope (This Version)

| Area | Decision |
|------|---------|
| Notifications (email, SMS, push, webhooks) | **Explicitly deferred** — user confirmed "no notifications for now" |
| Multi-user / multi-tenancy | Single user only |
| Multiple Parcel accounts | Single API key only |
| Manual delivery entry | Parcel is the sole data source; no CRUD for deliveries |
| Password reset / change | No email service; documented as operational workaround |
| Multi-factor authentication | Out of scope for single-user local deployment |
| Delivery archival / pruning | Full history retained; no deletion or archival policy |
| Mobile native app | Web dashboard only; responsive down to 375px |
| Public API access | API is for dashboard consumption only; no public-facing API keys |
| Outbound webhooks | No notification dispatch mechanism |
| Advanced analytics / reporting | Not requested |

---

## 4. Architecture Overview

Six Architecture Decision Records (ADRs) establish the structural commitments all other requirements are written against.

| ADR | Decision | Rationale Summary |
|-----|---------|-------------------|
| ADR-001 | Monorepo, multi-container | Single git repo; `docker compose up` starts everything |
| ADR-002 | Python 3.12 + FastAPI | Async-native; auto-OpenAPI; APScheduler integration; Pydantic v2 |
| ADR-003 | PostgreSQL 16 | Relational integrity; JSONB; Alembic; Docker-native |
| ADR-004 | React 18 + TypeScript + Vite | Type-safe; component model; Vite hashed assets |
| ADR-005 | Nginx reverse proxy | Same-origin: eliminates CORS; serves SPA; SSL termination point |
| ADR-006 | Docker Compose v2 (3 services) | Zero external dependencies; single-command deployment |

### Data Flow Summary

```
Every 15 min:
  APScheduler → Parcel API → diff against DB snapshot →
    new deliveries: INSERT delivery + StatusHistory(initial) + DeliveryEvents
    existing:       UPDATE delivery + INSERT StatusHistory(if changed) +
                    INSERT DeliveryEvents ON CONFLICT DO NOTHING
  → update PollLog

Dashboard request:
  Browser → Nginx → FastAPI (JWT validated) → SQLAlchemy → PostgreSQL →
  Pydantic serialisation → JSON → Nginx → Browser
```

---

## 5. Requirements Catalogue

Priority: **M** = Must Have · **S** = Should Have · **C** = Could Have  
Source: **UI** = User Input · **API** = Parcel API Docs · **AR** = Architecture Decision · **IN** = Inferred/Best Practice

### 5.1 Architecture Decisions

| Req ID | Title | Priority | Source | Detail Ref |
|--------|-------|:--------:|:------:|-----------|
| ADR-001 | Monorepo, multi-container repository structure | M | UI+AR | [01-architecture §2.1](./01-architecture.md) |
| ADR-002 | Python 3.12 + FastAPI as backend framework | M | AR | [01-architecture §2.2](./01-architecture.md) |
| ADR-003 | PostgreSQL 16 as persistence store | M | UI+AR | [01-architecture §2.3](./01-architecture.md) |
| ADR-004 | React 18 + TypeScript + Vite for frontend | M | AR | [01-architecture §2.4](./01-architecture.md) |
| ADR-005 | Nginx as reverse proxy (same-origin, no CORS) | M | AR | [01-architecture §2.5](./01-architecture.md) |
| ADR-006 | Docker Compose v2, three services | M | UI+AR | [01-architecture §2.6](./01-architecture.md) |

### 5.2 Data Model

| Req ID | Title | Priority | Source | Detail Ref |
|--------|-------|:--------:|:------:|-----------|
| DM-BR-001 | Delivery natural key: (tracking_number, carrier_code) | M | API | [02-data-model §3.1](./02-data-model.md) |
| DM-BR-002 | description field stores user-supplied Parcel label | M | API | [02-data-model §3.1](./02-data-model.md) |
| DM-BR-003 | timestamp_expected preferred over date_expected_raw for ordering | M | API | [02-data-model §3.1](./02-data-model.md) |
| DM-BR-004 | last_raw_response stores only most recent API response | M | IN | [02-data-model §3.1](./02-data-model.md) |
| DM-BR-005 | Delivery records never hard-deleted | M | UI | [02-data-model §3.1](./02-data-model.md) |
| DM-BR-006 | DeliveryEvent records are append-only; no updates or deletes | M | IN | [02-data-model §3.2](./02-data-model.md) |
| DM-BR-007 | Event deduplication via (delivery_id, description, date_raw) fingerprint | M | IN | [02-data-model §3.2](./02-data-model.md) |
| DM-BR-008 | sequence_number reflects API array order (chronological) | S | API | [02-data-model §3.2](./02-data-model.md) |
| DM-BR-009 | event_date_raw stored verbatim; never parsed into timestamp | M | API | [02-data-model §3.2](./02-data-model.md) |
| DM-BR-010 | StatusHistory initial record written at delivery creation (prev=NULL) | M | IN | [02-data-model §3.3](./02-data-model.md) |
| DM-BR-011 | StatusHistory record written before delivery update when status changes | M | IN | [02-data-model §3.3](./02-data-model.md) |
| DM-BR-012 | StatusHistory records are immutable | M | IN | [02-data-model §3.3](./02-data-model.md) |
| DM-BR-013 | detected_at reflects poller detection time, not carrier change time | S | IN | [02-data-model §3.3](./02-data-model.md) |
| DM-BR-014 | Passwords stored only as bcrypt hash (cost ≥ 12) | M | IN | [02-data-model §3.4](./02-data-model.md) |
| DM-BR-015 | Initial user seeded from ADMIN_USERNAME + ADMIN_PASSWORD env vars | M | UI | [02-data-model §3.4](./02-data-model.md) |
| DM-BR-016 | is_active=false prevents login without deleting user | M | IN | [02-data-model §3.4](./02-data-model.md) |
| DM-BR-017 | User records never hard-deleted | S | IN | [02-data-model §3.4](./02-data-model.md) |
| DM-BR-018 | PollLog record created at poll cycle start (before API call) | M | IN | [02-data-model §3.5](./02-data-model.md) |
| DM-BR-019 | completed_at=NULL indicates interrupted poll | S | IN | [02-data-model §3.5](./02-data-model.md) |
| DM-BR-020 | Poll logs retained indefinitely | S | UI | [02-data-model §3.5](./02-data-model.md) |
| DM-BR-021 | semantic_status stored in deliveries table (enables DB-level filtering) | M | IN | [02-data-model §4](./02-data-model.md) |
| DM-BR-022 | Unrecognised status_code stored with semantic_status='UNKNOWN' | M | IN | [02-data-model §4](./02-data-model.md) |
| DM-BR-023 | Historical StatusHistory entries never retroactively updated | M | IN | [02-data-model §4](./02-data-model.md) |
| DM-BR-024 | timestamp_expected takes precedence over date_expected_raw | M | API | [02-data-model §5](./02-data-model.md) |
| DM-BR-025 | date_expected_raw and event_date_raw never parsed into timestamps | M | API | [02-data-model §5](./02-data-model.md) |
| DM-BR-026 | Carrier names not stored in DB; enriched client-side from carriers cache | S | IN | [02-data-model §7](./02-data-model.md) |
| DM-MIG-001 | All schema changes via Alembic revision; no direct ALTER TABLE | M | IN | [02-data-model §6](./02-data-model.md) |
| DM-MIG-002 | Migrations must be non-destructive during normal operation | M | IN | [02-data-model §6](./02-data-model.md) |
| DM-MIG-003 | Initial migration creates all five tables with indexes and constraints | M | IN | [02-data-model §6](./02-data-model.md) |
| DM-MIG-004 | Seed script checks user count; only seeds if count = 0 | M | IN | [02-data-model §6](./02-data-model.md) |

### 5.3 Polling Service

| Req ID | Title | Priority | Source | Detail Ref |
|--------|-------|:--------:|:------:|-----------|
| POLL-REQ-001 | Polling before HTTP requests begin serving | M | UI | [03-polling-service §2.2](./03-polling-service.md) |
| POLL-REQ-002 | In-progress poll allowed to complete on shutdown (30s max) | M | IN | [03-polling-service §2.2](./03-polling-service.md) |
| POLL-REQ-003 | Immediate poll on every app start (cold-start) | M | UI | [03-polling-service §2.3](./03-polling-service.md) |
| POLL-REQ-004 | Cold-start poll doesn't count against 15-min interval | S | IN | [03-polling-service §2.3](./03-polling-service.md) |
| POLL-REQ-005 | POLL_INTERVAL_MINUTES configurable; minimum 5 min enforced | M | UI | [03-polling-service §2.4](./03-polling-service.md) |
| POLL-REQ-006 | 15-min interval uses ~4 of 20 req/hr (80% safety margin) | S | API | [03-polling-service §2.4](./03-polling-service.md) |
| POLL-REQ-007 | PARCEL_API_KEY from env var only; never logged | M | IN | [03-polling-service §3](./03-polling-service.md) |
| POLL-REQ-008 | App refuses to start if PARCEL_API_KEY absent | M | IN | [03-polling-service §3](./03-polling-service.md) |
| POLL-REQ-009 | API key never in logs, responses, or error messages | M | IN | [03-polling-service §3](./03-polling-service.md) |
| POLL-REQ-010 | API key passed as api-key header (not Authorization) | M | API | [03-polling-service §3](./03-polling-service.md) |
| POLL-REQ-011 | Always use filter_mode=recent (not active) | M | API | [03-polling-service §4.1](./03-polling-service.md) |
| POLL-REQ-012 | httpx client shared across poll cycles (keep-alive) | S | IN | [03-polling-service §4.1](./03-polling-service.md) |
| POLL-REQ-013 | Full response validation: HTTP status → JSON → success field | M | API | [03-polling-service §4.2](./03-polling-service.md) |
| POLL-REQ-014 | Empty deliveries array is valid; not treated as error | M | API | [03-polling-service §4.2](./03-polling-service.md) |
| POLL-REQ-015 | Pre-poll DB snapshot loaded in single query (no N+1) | M | IN | [03-polling-service §5.2](./03-polling-service.md) |
| POLL-REQ-016 | New delivery: missing from snapshot by (tracking_number, carrier_code) | M | IN | [03-polling-service §5.3](./03-polling-service.md) |
| POLL-REQ-017 | Existing delivery: diff status, diff events, always update last_seen_at | M | IN | [03-polling-service §5.4](./03-polling-service.md) |
| POLL-REQ-018 | last_seen_at updated on every poll that returns the delivery | M | IN | [03-polling-service §5.4](./03-polling-service.md) |
| POLL-REQ-019 | Per-delivery database operations in single transaction | M | IN | [03-polling-service §5.5](./03-polling-service.md) |
| POLL-REQ-020 | PollLog updated in separate transaction after all deliveries processed | M | IN | [03-polling-service §5.5](./03-polling-service.md) |
| POLL-REQ-021 | Deliveries processed sequentially (not in parallel) | S | IN | [03-polling-service §5.5](./03-polling-service.md) |
| POLL-REQ-022 | semantic_status derived consistently at write time | M | IN | [03-polling-service §5.6](./03-polling-service.md) |
| POLL-REQ-023 | Unrecognised status_code: semantic_status='UNKNOWN'; log WARNING | M | IN | [03-polling-service §5.6](./03-polling-service.md) |
| POLL-REQ-024 | HTTP 429: skip cycle; log WARNING; no retry | M | API | [03-polling-service §6.2](./03-polling-service.md) |
| POLL-REQ-025 | HTTP 401: log CRITICAL; skip cycle; no retry | M | IN | [03-polling-service §6.3](./03-polling-service.md) |
| POLL-REQ-026 | 5xx / network errors: exponential backoff (15s, 60s, 120s, max 3 retries) | M | IN | [03-polling-service §6.4](./03-polling-service.md) |
| POLL-REQ-027 | Retry attempts logged at WARNING with attempt number and delay | S | IN | [03-polling-service §6.4](./03-polling-service.md) |
| POLL-REQ-028 | Total retry time within a cycle must not exceed 10 minutes | S | IN | [03-polling-service §6.4](./03-polling-service.md) |
| POLL-REQ-029 | Individual delivery failure: rollback, log ERROR, continue remaining | M | IN | [03-polling-service §6.5](./03-polling-service.md) |
| POLL-REQ-030 | Partial success yields outcome='partial', not 'success' | M | IN | [03-polling-service §6.5](./03-polling-service.md) |
| POLL-REQ-031 | DB unavailable: abort poll; no Parcel API call made | M | IN | [03-polling-service §6.6](./03-polling-service.md) |
| POLL-REQ-032 | max_instances=1: overlapping polls dropped with WARNING | M | IN | [03-polling-service §7](./03-polling-service.md) |
| POLL-REQ-033 | API key never appears in log output (any level) | M | IN | [03-polling-service §8](./03-polling-service.md) |
| POLL-REQ-034 | Every log entry within a poll cycle includes poll_id | S | IN | [03-polling-service §8](./03-polling-service.md) |
| POLL-REQ-035 | Health endpoint exposes last_poll_at, outcome, consecutive_errors | S | IN | [03-polling-service §9](./03-polling-service.md) |
| POLL-REQ-036 | consecutive_errors ≥ 3 triggers degraded health status | S | IN | [03-polling-service §9](./03-polling-service.md) |

### 5.4 Status Normalisation

| Req ID | Title | Priority | Source | Detail Ref |
|--------|-------|:--------:|:------:|-----------|
| NORM-REQ-001 | Display labels defined in frontend STATUS_DISPLAY map | M | IN | [04-status-normalization §3](./04-status-normalization.md) |
| NORM-REQ-002 | Display labels ≤ 20 characters | S | IN | [04-status-normalization §3](./04-status-normalization.md) |
| NORM-REQ-003 | lifecycle_group included in all delivery API responses | M | IN | [04-status-normalization §4](./04-status-normalization.md) |
| NORM-REQ-004 | LifecycleGroup derived at runtime; never stored in DB | M | IN | [04-status-normalization §4](./04-status-normalization.md) |
| NORM-REQ-005 | Anomalous terminal-state transitions logged WARNING; still persisted | M | IN | [04-status-normalization §5.2](./04-status-normalization.md) |
| NORM-REQ-006 | No transitions rejected or discarded; all persisted | M | IN | [04-status-normalization §5.3](./04-status-normalization.md) |
| NORM-REQ-007 | Both parcel_status_code and semantic_status stored in deliveries | M | IN | [04-status-normalization §6](./04-status-normalization.md) |
| NORM-REQ-008 | StatusHistory stores full status pair (code + semantic) for both states | M | IN | [04-status-normalization §6](./04-status-normalization.md) |
| NORM-REQ-009 | Historical StatusHistory entries never retroactively modified | M | IN | [04-status-normalization §6](./04-status-normalization.md) |
| NORM-REQ-010 | normalize_status() never raises; unknown codes return UNKNOWN | M | IN | [04-status-normalization §7](./04-status-normalization.md) |
| NORM-REQ-011 | get_lifecycle_group() never raises for any SemanticStatus | M | IN | [04-status-normalization §7](./04-status-normalization.md) |
| NORM-REQ-012 | 100% branch coverage required on both normalisation functions | S | IN | [04-status-normalization §7](./04-status-normalization.md) |
| NORM-REQ-013 | Display labels via STATUS_DISPLAY map only; no inline strings in JSX | S | IN | [04-status-normalization §8](./04-status-normalization.md) |
| NORM-REQ-014 | Badge colour driven by LifecycleGroup, not individual status | S | IN | [04-status-normalization §8](./04-status-normalization.md) |

### 5.5 REST API

| Req ID | Title | Priority | Source | Detail Ref |
|--------|-------|:--------:|:------:|-----------|
| API-REQ-001 | All endpoints except login and health require Bearer token | M | IN | [05-rest-api §2](./05-rest-api.md) |
| API-REQ-002 | Invalid/expired/missing token → 401 UNAUTHORIZED | M | IN | [05-rest-api §2](./05-rest-api.md) |
| API-REQ-003 | JWT signed with HS256 using JWT_SECRET_KEY (≥ 32 chars) | M | IN | [05-rest-api §2](./05-rest-api.md) |
| API-REQ-004 | token_version claim validated server-side on every request | M | IN | [05-rest-api §2](./05-rest-api.md) |
| API-REQ-005 | All errors use standard error envelope (code + message + details) | M | IN | [05-rest-api §3](./05-rest-api.md) |
| API-REQ-006 | Login failure: no distinction between bad username and bad password | M | IN | [05-rest-api §4.1](./05-rest-api.md) |
| API-REQ-007 | Successful login updates last_login_at | S | IN | [05-rest-api §4.1](./05-rest-api.md) |
| API-REQ-008 | POST /auth/refresh validates token_version; mismatch → 401 | M | IN | [05-rest-api §4.1](./05-rest-api.md) |
| API-REQ-009 | POST /auth/logout increments token_version; clears cookie | M | IN | [05-rest-api §4.1](./05-rest-api.md) |
| API-REQ-010 | include_terminal=false default excludes TERMINAL from delivery list | M | UI | [05-rest-api §4.2](./05-rest-api.md) |
| API-REQ-011 | search: case-insensitive substring on description + tracking_number | M | UI | [05-rest-api §4.2](./05-rest-api.md) |
| API-REQ-012 | NULL timestamp_expected sorts last in ascending sort | M | API | [05-rest-api §4.2](./05-rest-api.md) |
| API-REQ-013 | All timestamps serialised as ISO 8601 UTC strings (Z suffix) | M | IN | [05-rest-api §4.2](./05-rest-api.md) |
| API-REQ-014 | Events ordered sequence_number ASC; history ordered detected_at ASC | M | IN | [05-rest-api §4.2](./05-rest-api.md) |
| API-REQ-015 | Delivery detail endpoint not paginated | M | IN | [05-rest-api §4.2](./05-rest-api.md) |
| API-REQ-016 | GET /health responds within 5s; DB check timeout 3s | M | IN | [05-rest-api §4.3](./05-rest-api.md) |
| API-REQ-017 | GET /health returns 200 for degraded; 503 only for unhealthy | M | IN | [05-rest-api §4.3](./05-rest-api.md) |
| API-REQ-018 | next_poll_at reflects APScheduler next fire time | S | IN | [05-rest-api §4.3](./05-rest-api.md) |
| API-REQ-019 | GET /carriers never makes synchronous outbound call per request | M | IN | [05-rest-api §4.3](./05-rest-api.md) |
| API-REQ-020 | Stale carrier cache served without error | S | IN | [05-rest-api §4.3](./05-rest-api.md) |
| API-REQ-021 | Security headers on all responses (X-Content-Type-Options, X-Frame-Options) | M | IN | [05-rest-api §5](./05-rest-api.md) |
| API-REQ-022 | CORS restricted; no wildcard origins | M | IN | [05-rest-api §5](./05-rest-api.md) |
| API-REQ-023 | /docs and /redoc disabled in production | M | IN | [05-rest-api §5](./05-rest-api.md) |
| API-REQ-024 | password_hash never included in any API response | M | IN | [05-rest-api §5](./05-rest-api.md) |
| API-REQ-025 | 500 errors use standard envelope; no stack traces exposed | M | IN | [05-rest-api §5](./05-rest-api.md) |
| API-REQ-026 | List endpoints use offset pagination (page + page_size) | M | IN | [05-rest-api §6](./05-rest-api.md) |
| API-REQ-027 | Maximum page_size = 100 | S | IN | [05-rest-api §6](./05-rest-api.md) |
| API-REQ-028 | Page beyond total returns empty items array, not 404 | S | IN | [05-rest-api §6](./05-rest-api.md) |

### 5.6 Web Dashboard

| Req ID | Title | Priority | Source | Detail Ref |
|--------|-------|:--------:|:------:|-----------|
| DASH-REQ-001 | Unauthenticated access redirects to /login with redirect param | M | IN | [06-web-dashboard §2](./06-web-dashboard.md) |
| DASH-REQ-002 | Header on all auth pages: name, poll status, refresh, logout | M | UI | [06-web-dashboard §2.2](./06-web-dashboard.md) |
| DASH-REQ-003 | Poll status indicator: green/amber/red/grey dot by health state | S | IN | [06-web-dashboard §2.2](./06-web-dashboard.md) |
| DASH-REQ-004 | Header health indicator auto-refreshes every 60 seconds | S | IN | [06-web-dashboard §2.2](./06-web-dashboard.md) |
| DASH-REQ-005 | Login form: username, password, submit, error area | M | UI | [06-web-dashboard §3](./06-web-dashboard.md) |
| DASH-REQ-006 | Submit button disabled + spinner during request | S | IN | [06-web-dashboard §3](./06-web-dashboard.md) |
| DASH-REQ-007 | Invalid credentials → single generic error message | M | IN | [06-web-dashboard §3](./06-web-dashboard.md) |
| DASH-REQ-008 | Disabled account → specific error message | S | IN | [06-web-dashboard §3](./06-web-dashboard.md) |
| DASH-REQ-009 | Network/5xx error → "Unable to connect" message | S | IN | [06-web-dashboard §3](./06-web-dashboard.md) |
| DASH-REQ-010 | Successful login: store token in context; navigate to redirect | M | IN | [06-web-dashboard §3](./06-web-dashboard.md) |
| DASH-REQ-011 | Already-authenticated user navigating to /login redirects away | S | IN | [06-web-dashboard §3](./06-web-dashboard.md) |
| DASH-REQ-012 | Login form submits on Enter key | S | IN | [06-web-dashboard §3](./06-web-dashboard.md) |
| DASH-REQ-013 | Filter tabs: All, Active, Needs Attention, Delivered | M | UI | [06-web-dashboard §4.2](./06-web-dashboard.md) |
| DASH-REQ-014 | Needs Attention tab shows live badge count | S | UI | [06-web-dashboard §4.2](./06-web-dashboard.md) |
| DASH-REQ-015 | Default tab = All; tab state in URL query param | S | IN | [06-web-dashboard §4.2](./06-web-dashboard.md) |
| DASH-REQ-016 | Search across description + tracking_number | M | UI | [06-web-dashboard §4.3](./06-web-dashboard.md) |
| DASH-REQ-017 | Search debounced 300ms | S | IN | [06-web-dashboard §4.3](./06-web-dashboard.md) |
| DASH-REQ-018 | Search applies within current tab filter | S | IN | [06-web-dashboard §4.3](./06-web-dashboard.md) |
| DASH-REQ-019 | Active search shows clear (✕) button | C | IN | [06-web-dashboard §4.3](./06-web-dashboard.md) |
| DASH-REQ-020 | Table columns: Description, Carrier, Status, Expected Delivery | M | UI | [06-web-dashboard §4.4](./06-web-dashboard.md) |
| DASH-REQ-021 | Default sort: Expected Delivery ascending; active sort indicated | M | UI | [06-web-dashboard §4.4](./06-web-dashboard.md) |
| DASH-REQ-022 | Column header click toggles sort; sort state in URL | S | IN | [06-web-dashboard §4.4](./06-web-dashboard.md) |
| DASH-REQ-023 | Entire row clickable → /deliveries/:id | M | IN | [06-web-dashboard §4.4](./06-web-dashboard.md) |
| DASH-REQ-024 | Tracking number as secondary text under description | S | UI | [06-web-dashboard §4.4](./06-web-dashboard.md) |
| DASH-REQ-025 | Date display priority: timestamp_expected → date_raw → "—" | M | API | [06-web-dashboard §4.5](./06-web-dashboard.md) |
| DASH-REQ-026 | Relative date labels computed in browser local timezone | M | IN | [06-web-dashboard §4.5](./06-web-dashboard.md) |
| DASH-REQ-027 | Pagination controls when pages > 1 | S | IN | [06-web-dashboard §4.6](./06-web-dashboard.md) |
| DASH-REQ-028 | Default page_size = 25 | S | IN | [06-web-dashboard §4.6](./06-web-dashboard.md) |
| DASH-REQ-029 | Page number in URL query param | S | IN | [06-web-dashboard §4.6](./06-web-dashboard.md) |
| DASH-REQ-030 | Delivery list auto-refreshes every 5 minutes; non-disruptive | M | UI | [06-web-dashboard §4.7](./06-web-dashboard.md) |
| DASH-REQ-031 | Manual refresh button triggers immediate cache invalidation | S | IN | [06-web-dashboard §4.7](./06-web-dashboard.md) |
| DASH-REQ-032 | Initial page load shows skeleton rows; not blank screen | S | IN | [06-web-dashboard §4.7](./06-web-dashboard.md) |
| DASH-REQ-033 | Empty state messages for all list conditions | S | IN | [06-web-dashboard §4.8](./06-web-dashboard.md) |
| DASH-REQ-034 | Detail header: description, tracking, carrier, badge, expected date | M | UI | [06-web-dashboard §5.2](./06-web-dashboard.md) |
| DASH-REQ-035 | Status history as vertical timeline (oldest → newest) | S | IN | [06-web-dashboard §5.3](./06-web-dashboard.md) |
| DASH-REQ-036 | Initial history entry labelled "First seen as:" | S | IN | [06-web-dashboard §5.3](./06-web-dashboard.md) |
| DASH-REQ-037 | Events log ordered by sequence_number ASC | M | API | [06-web-dashboard §5.4](./06-web-dashboard.md) |
| DASH-REQ-038 | Empty events array: "No tracking events recorded yet." | S | IN | [06-web-dashboard §5.4](./06-web-dashboard.md) |
| DASH-REQ-039 | Back link preserves list filter/sort/search state | S | IN | [06-web-dashboard §5.5](./06-web-dashboard.md) |
| DASH-REQ-040 | Detail page auto-refreshes every 5 minutes | M | IN | [06-web-dashboard §5.6](./06-web-dashboard.md) |
| DASH-REQ-041 | Terminal delivery detail: extended 30-min refresh interval | C | IN | [06-web-dashboard §5.6](./06-web-dashboard.md) |
| DASH-REQ-042 | Badge colour by lifecycle_group; DELIVERED = green override | S | IN | [06-web-dashboard §6](./06-web-dashboard.md) |
| DASH-REQ-043 | Badge shows STATUS_DISPLAY label; not raw enum or integer | M | IN | [06-web-dashboard §6](./06-web-dashboard.md) |
| DASH-REQ-044 | ATTENTION badges include warning icon | S | IN | [06-web-dashboard §6](./06-web-dashboard.md) |
| DASH-REQ-045 | AuthContext: accessToken, isAuthenticated, login(), logout() | M | IN | [06-web-dashboard §7.1](./06-web-dashboard.md) |
| DASH-REQ-046 | Access token in-memory only; never in localStorage or cookies | M | IN | [06-web-dashboard §7.1](./06-web-dashboard.md) |
| DASH-REQ-047 | Silent token refresh on app load; success = render, failure = login | M | IN | [06-web-dashboard §7.2](./06-web-dashboard.md) |
| DASH-REQ-048 | Full-screen loading during silent refresh (no login flash) | S | IN | [06-web-dashboard §7.2](./06-web-dashboard.md) |
| DASH-REQ-049 | Axios interceptor attaches Bearer token to all requests | M | IN | [06-web-dashboard §7.3](./06-web-dashboard.md) |
| DASH-REQ-050 | Axios interceptor auto-refreshes on 401; logout on refresh failure | M | IN | [06-web-dashboard §7.3](./06-web-dashboard.md) |
| DASH-REQ-051 | Logout: calls API, clears context, clears query cache, navigates | M | IN | [06-web-dashboard §7.4](./06-web-dashboard.md) |
| DASH-REQ-052 | Data-fetching errors handled with user-friendly messages | S | IN | [06-web-dashboard §8](./06-web-dashboard.md) |
| DASH-REQ-053 | TanStack Query: 2 retries for data; 0 retries for auth | S | IN | [06-web-dashboard §8](./06-web-dashboard.md) |
| DASH-REQ-054 | Global error boundary with fallback UI | S | IN | [06-web-dashboard §8](./06-web-dashboard.md) |
| DASH-REQ-055 | Login form labels properly associated with inputs | S | IN | [06-web-dashboard §9](./06-web-dashboard.md) |
| DASH-REQ-056 | Status badges have screen-reader text (sr-only) | S | IN | [06-web-dashboard §9](./06-web-dashboard.md) |
| DASH-REQ-057 | Table rows keyboard-navigable (role=button, Enter/Space) | S | IN | [06-web-dashboard §9](./06-web-dashboard.md) |
| DASH-REQ-058 | Page title updates on route change | S | IN | [06-web-dashboard §9](./06-web-dashboard.md) |
| DASH-REQ-059 | Primary target: desktop ≥ 1024px | M | UI | [06-web-dashboard §10](./06-web-dashboard.md) |
| DASH-REQ-060 | Card layout for viewport < 768px | S | IN | [06-web-dashboard §10](./06-web-dashboard.md) |

### 5.7 Authentication & Security

| Req ID | Title | Priority | Source | Detail Ref |
|--------|-------|:--------:|:------:|-----------|
| SEC-REQ-001 | bcrypt cost ≥ 12; no plaintext passwords stored | M | IN | [07-auth-security §2.1](./07-auth-security.md) |
| SEC-REQ-002 | BCRYPT_ROUNDS configurable (10–15); validated at startup | S | IN | [07-auth-security §2.1](./07-auth-security.md) |
| SEC-REQ-003 | Use passlib with bcrypt scheme | M | IN | [07-auth-security §2.1](./07-auth-security.md) |
| SEC-REQ-004 | Warn if ADMIN_PASSWORD still set after seeding | S | IN | [07-auth-security §2.1](./07-auth-security.md) |
| SEC-REQ-005 | Initial password minimum 12 characters | M | IN | [07-auth-security §2.2](./07-auth-security.md) |
| SEC-REQ-006 | No password reset mechanism; documented limitation | S | IN | [07-auth-security §2.2](./07-auth-security.md) |
| SEC-REQ-007 | Usernames are case-sensitive | M | IN | [07-auth-security §2.3](./07-auth-security.md) |
| SEC-REQ-008 | Constant-time comparison; dummy verify on unknown username | M | IN | [07-auth-security §2.3](./07-auth-security.md) |
| SEC-REQ-009 | JWT signed with HS256 using JWT_SECRET_KEY | M | IN | [07-auth-security §3.1](./07-auth-security.md) |
| SEC-REQ-010 | JWT_SECRET_KEY ≥ 32 chars; startup fails if absent or short | M | IN | [07-auth-security §3.1](./07-auth-security.md) |
| SEC-REQ-011 | Rotating JWT_SECRET_KEY invalidates all tokens | S | IN | [07-auth-security §3.1](./07-auth-security.md) |
| SEC-REQ-012 | type claim validated; access token ≠ refresh token | M | IN | [07-auth-security §3.2](./07-auth-security.md) |
| SEC-REQ-013 | Access token TTL default 60 min; refresh token default 7 days | M | UI | [07-auth-security §3.3](./07-auth-security.md) |
| SEC-REQ-014 | TTL values outside permitted range rejected at startup | M | IN | [07-auth-security §3.3](./07-auth-security.md) |
| SEC-REQ-015 | 6-step token validation chain on every protected request | M | IN | [07-auth-security §3.4](./07-auth-security.md) |
| SEC-REQ-016 | All token validation failures return same 401; reason not disclosed | M | IN | [07-auth-security §3.4](./07-auth-security.md) |
| SEC-REQ-017 | token_version DB check required on every request | M | IN | [07-auth-security §3.4](./07-auth-security.md) |
| SEC-REQ-018 | Access + refresh tokens issued together at login | M | IN | [07-auth-security §4.1](./07-auth-security.md) |
| SEC-REQ-019 | Refresh only issues new access token; refresh token not rotated | S | IN | [07-auth-security §4.1](./07-auth-security.md) |
| SEC-REQ-020 | token_version incremented on logout | M | IN | [07-auth-security §4.2](./07-auth-security.md) |
| SEC-REQ-021 | token_version increments are atomic DB operations | M | IN | [07-auth-security §4.2](./07-auth-security.md) |
| SEC-REQ-022 | Refresh cookie: HttpOnly, SameSite=Strict, Path=/api/auth | M | IN | [07-auth-security §4.3](./07-auth-security.md) |
| SEC-REQ-023 | Secure cookie attribute controlled by COOKIE_SECURE env var | M | IN | [07-auth-security §4.3](./07-auth-security.md) |
| SEC-REQ-024 | Refresh token cookie scoped to /api/auth only | M | IN | [07-auth-security §4.3](./07-auth-security.md) |
| SEC-REQ-025 | Auth implemented as reusable FastAPI dependency | M | IN | [07-auth-security §5.1](./07-auth-security.md) |
| SEC-REQ-026 | Routes protected by explicit dependency inclusion | M | IN | [07-auth-security §5.1](./07-auth-security.md) |
| SEC-REQ-027 | User identity from auth dependency only; never from request body | M | IN | [07-auth-security §5.1](./07-auth-security.md) |
| SEC-REQ-028 | CORS not required in production (same origin via Nginx) | M | AR | [07-auth-security §6](./07-auth-security.md) |
| SEC-REQ-029 | CORSMiddleware in development only; specific origins only | M | IN | [07-auth-security §6](./07-auth-security.md) |
| SEC-REQ-030 | CORSMiddleware not added in production | M | IN | [07-auth-security §6](./07-auth-security.md) |
| SEC-REQ-031 | Security headers on all FastAPI responses | M | IN | [07-auth-security §7](./07-auth-security.md) |
| SEC-REQ-032 | Nginx adds security headers including Content-Security-Policy | M | IN | [07-auth-security §7](./07-auth-security.md) |
| SEC-REQ-033 | CSP: connect-src 'self'; no external resources | M | IN | [07-auth-security §7](./07-auth-security.md) |
| SEC-REQ-034 | Server header suppressed (no framework/version disclosure) | S | IN | [07-auth-security §7](./07-auth-security.md) |
| SEC-REQ-035 | Login rate limit: 10 failed attempts / 15 min / IP | M | IN | [07-auth-security §8](./07-auth-security.md) |
| SEC-REQ-036 | Rate limit state in application memory | M | IN | [07-auth-security §8](./07-auth-security.md) |
| SEC-REQ-037 | Rate limit counts failed attempts only; success resets counter | M | IN | [07-auth-security §8](./07-auth-security.md) |
| SEC-REQ-038 | Rate limit exceeded: 429 with RATE_LIMITED code | M | IN | [07-auth-security §8](./07-auth-security.md) |
| SEC-REQ-039 | Retry-After header on rate-limited login responses | S | IN | [07-auth-security §8](./07-auth-security.md) |
| SEC-REQ-040 | Rate limit keyed by source IP; X-Forwarded-For when TRUST_PROXY_HEADERS=true | M | IN | [07-auth-security §8](./07-auth-security.md) |
| SEC-REQ-041 | Nginx optional HTTPS via HTTPS_ENABLED + cert volume mounts | S | IN | [07-auth-security §9](./07-auth-security.md) |
| SEC-REQ-042 | HTTPS: TLS 1.2+ only; HTTP redirects to HTTPS | S | IN | [07-auth-security §9](./07-auth-security.md) |
| SEC-REQ-043 | HTTP-only mode acceptable for local network use | M | UI | [07-auth-security §9](./07-auth-security.md) |
| SEC-REQ-044 | COOKIE_SECURE=true required when HTTPS_ENABLED=true | M | IN | [07-auth-security §9](./07-auth-security.md) |
| SEC-REQ-045 | All secrets via env vars; never in code or images | M | IN | [07-auth-security §10](./07-auth-security.md) |
| SEC-REQ-046 | .env.example committed; .env in .gitignore | M | IN | [07-auth-security §10](./07-auth-security.md) |
| SEC-REQ-047 | Startup fails if required secret missing | M | IN | [07-auth-security §10](./07-auth-security.md) |
| SEC-REQ-048 | Startup fails if JWT_SECRET_KEY < 32 chars or ADMIN_PASSWORD < 12 | M | IN | [07-auth-security §10](./07-auth-security.md) |
| SEC-REQ-049 | api container runs as non-root user | M | IN | [07-auth-security §11](./07-auth-security.md) |
| SEC-REQ-050 | Nginx worker runs as non-root | M | IN | [07-auth-security §11](./07-auth-security.md) |
| SEC-REQ-051 | api container filesystem treated as read-only | S | IN | [07-auth-security §11](./07-auth-security.md) |
| SEC-REQ-052 | Secrets passed via env_file; not hardcoded in compose or Dockerfiles | M | IN | [07-auth-security §11](./07-auth-security.md) |
| SEC-REQ-053 | postgres port not exposed on host in production | M | IN | [07-auth-security §11](./07-auth-security.md) |
| SEC-REQ-054 | Docker image versions pinned; no latest tag | S | IN | [07-auth-security §11](./07-auth-security.md) |
| SEC-REQ-055 | All inputs validated by Pydantic before handler logic | M | IN | [07-auth-security §12](./07-auth-security.md) |
| SEC-REQ-056 | All DB queries via SQLAlchemy ORM or parameterised SQL | M | IN | [07-auth-security §12](./07-auth-security.md) |
| SEC-REQ-057 | Field length limits at Pydantic and DB levels | M | IN | [07-auth-security §12](./07-auth-security.md) |
| SEC-REQ-058 | Search: parameterised LIKE; no string interpolation | M | IN | [07-auth-security §12](./07-auth-security.md) |
| SEC-REQ-059 | Security audit events logged at INFO level | S | IN | [07-auth-security §13](./07-auth-security.md) |
| SEC-REQ-060 | Source IP included in security log entries | S | IN | [07-auth-security §13](./07-auth-security.md) |
| SEC-REQ-061 | No secrets in log output at any level | M | IN | [07-auth-security §13](./07-auth-security.md) |

### 5.8 Deployment & Configuration

| Req ID | Title | Priority | Source | Detail Ref |
|--------|-------|:--------:|:------:|-----------|
| DEPLOY-REQ-001 | All services on shared Docker bridge network delivery_network | M | AR | [08-deployment §2](./08-deployment.md) |
| DEPLOY-REQ-002 | postgres and api ports NOT exposed on host | M | IN | [08-deployment §2](./08-deployment.md) |
| DEPLOY-REQ-003 | frontend exposes port 80; FRONTEND_HTTP_PORT configurable | M | UI | [08-deployment §2](./08-deployment.md) |
| DEPLOY-REQ-004 | api depends_on postgres with condition: service_healthy | M | IN | [08-deployment §3](./08-deployment.md) |
| DEPLOY-REQ-005 | restart: unless-stopped on all three services | M | IN | [08-deployment §3](./08-deployment.md) |
| DEPLOY-REQ-006 | api Dockerfile: two-stage build | S | IN | [08-deployment §4.1](./08-deployment.md) |
| DEPLOY-REQ-007 | api runtime image: python:3.12-slim | M | AR | [08-deployment §4.1](./08-deployment.md) |
| DEPLOY-REQ-008 | api container runs as non-root appuser | M | IN | [08-deployment §4.1](./08-deployment.md) |
| DEPLOY-REQ-009 | .env never copied into api image | M | IN | [08-deployment §4.1](./08-deployment.md) |
| DEPLOY-REQ-010 | api container uses entrypoint.sh shell script | M | IN | [08-deployment §4.1](./08-deployment.md) |
| DEPLOY-REQ-011 | frontend Dockerfile: multi-stage (node:20-alpine + nginx:alpine) | S | IN | [08-deployment §4.2](./08-deployment.md) |
| DEPLOY-REQ-012 | npm ci in frontend build stage | S | IN | [08-deployment §4.2](./08-deployment.md) |
| DEPLOY-REQ-013 | frontend runtime: only static assets + Nginx | M | IN | [08-deployment §4.2](./08-deployment.md) |
| DEPLOY-REQ-014 | postgres: official postgres:16.3-alpine; no customisation | M | AR | [08-deployment §4.3](./08-deployment.md) |
| DEPLOY-REQ-015 | postgres_data named volume at /var/lib/postgresql/data | M | UI | [08-deployment §5.1](./08-deployment.md) |
| DEPLOY-REQ-016 | postgres_data uses local driver | M | IN | [08-deployment §5.1](./08-deployment.md) |
| DEPLOY-REQ-017 | postgres_data persists across restarts and rebuilds | M | UI | [08-deployment §5.1](./08-deployment.md) |
| DEPLOY-REQ-018 | Volume destruction requires --volumes; documented as destructive | M | IN | [08-deployment §5.1](./08-deployment.md) |
| DEPLOY-REQ-019 | SSL certs via read-only bind mounts when HTTPS enabled | S | IN | [08-deployment §5.2](./08-deployment.md) |
| DEPLOY-REQ-020 | api and frontend containers: no persistent volumes | M | IN | [08-deployment §5.3](./08-deployment.md) |
| DEPLOY-REQ-021 | entrypoint.sh: migrations → seed → uvicorn in strict order | M | IN | [08-deployment §6.2](./08-deployment.md) |
| DEPLOY-REQ-022 | set -e in entrypoint; migration/seed failure stops container | M | IN | [08-deployment §6.2](./08-deployment.md) |
| DEPLOY-REQ-023 | Uvicorn --workers 1 (APScheduler incompatible with >1 worker) | M | AR | [08-deployment §6.2](./08-deployment.md) |
| DEPLOY-REQ-024 | Uvicorn binds to 0.0.0.0 | M | IN | [08-deployment §6.2](./08-deployment.md) |
| DEPLOY-REQ-025 | Uvicorn --no-access-log recommended | C | IN | [08-deployment §6.2](./08-deployment.md) |
| DEPLOY-REQ-026 | Seed script: create user if users table is empty | M | UI | [08-deployment §6.3](./08-deployment.md) |
| DEPLOY-REQ-027 | Seed script is idempotent | M | IN | [08-deployment §6.3](./08-deployment.md) |
| DEPLOY-REQ-028 | Seed exits non-zero if DB empty and credentials not set | M | IN | [08-deployment §6.3](./08-deployment.md) |
| DEPLOY-REQ-029 | Nginx: /api/* proxy to api:8000; SPA fallback to index.html | M | AR | [08-deployment §7.1](./08-deployment.md) |
| DEPLOY-REQ-030 | try_files directive enables client-side SPA routing | M | IN | [08-deployment §7.1](./08-deployment.md) |
| DEPLOY-REQ-031 | Static assets: Cache-Control public, immutable, 1-year expires | S | IN | [08-deployment §7.1](./08-deployment.md) |
| DEPLOY-REQ-032 | Nginx sets X-Real-IP and X-Forwarded-For on proxy requests | M | IN | [08-deployment §7.1](./08-deployment.md) |
| DEPLOY-REQ-033 | HTTPS Nginx: HTTP→HTTPS redirect; TLS 1.2+ only | S | IN | [08-deployment §7.2](./08-deployment.md) |
| DEPLOY-REQ-034 | HTTPS config in separate nginx-https.conf | S | IN | [08-deployment §7.2](./08-deployment.md) |
| DEPLOY-REQ-035 | postgres healthcheck: pg_isready; 10s interval; 30s start_period | M | IN | [08-deployment §9](./08-deployment.md) |
| DEPLOY-REQ-036 | api healthcheck: GET /api/health; 30s interval; 60s start_period | M | IN | [08-deployment §9](./08-deployment.md) |
| DEPLOY-REQ-037 | frontend healthcheck: GET /; 30s interval | S | IN | [08-deployment §9](./08-deployment.md) |
| DEPLOY-REQ-038 | json-file logging: max-size 50m, max-file 5 on api and frontend | S | IN | [08-deployment §10](./08-deployment.md) |
| DEPLOY-REQ-039 | postgres log rotation managed internally | C | IN | [08-deployment §10](./08-deployment.md) |
| DEPLOY-REQ-040 | api logs to stdout/stderr only | M | IN | [08-deployment §10](./08-deployment.md) |
| DEPLOY-REQ-041 | Upgrade: docker compose build + docker compose up -d | S | IN | [08-deployment §11](./08-deployment.md) |
| DEPLOY-REQ-042 | Migrations run automatically on api container start | M | IN | [08-deployment §11](./08-deployment.md) |
| DEPLOY-REQ-043 | Downgrade requires manual alembic downgrade procedure | S | IN | [08-deployment §11](./08-deployment.md) |
| DEPLOY-REQ-044 | Backup via pg_dump documented in operator guide | S | IN | [08-deployment §12](./08-deployment.md) |
| DEPLOY-REQ-045 | No automated backup; operator's responsibility | S | IN | [08-deployment §12](./08-deployment.md) |
| DEPLOY-REQ-046 | Minimum: 1 CPU core, 512 MB RAM, 1 GB storage | S | IN | [08-deployment §13](./08-deployment.md) |
| DEPLOY-REQ-047 | Optional resource limits documented; commented out by default | C | IN | [08-deployment §13](./08-deployment.md) |
| DEPLOY-REQ-048 | .env.example with all variables, placeholders, and comments | M | IN | [08-deployment §14](./08-deployment.md) |

---

## 6. Traceability Matrix

### 6.1 Requirement Source Distribution

| Source | Count | % | Meaning |
|--------|------:|:-:|---------|
| **IN** — Inferred / Best Practice | 216 | 76% | Standard engineering practice; implied by context |
| **UI** — Explicit User Input | 38 | 13% | Directly from scoping conversation |
| **AR** — Architecture Decision | 16 | 6% | Structural commitments (ADRs) |
| **API** — Parcel API Documentation | 13 | 5% | Derived from API constraints or data shapes |
| **Total** | **283** | **100%** | |

### 6.2 User Input Traceability

Every explicit scoping answer maps to one or more requirements:

| User Statement | Derived Requirements |
|----------------|---------------------|
| *"Poll Parcel for active deliveries every 15 minutes"* | POLL-REQ-003, POLL-REQ-005, POLL-REQ-006 |
| *"No notifications for now"* | Out of scope; deferred |
| *"Single user with credentials to access"* | SEC-REQ-001–061 (auth domain), DM-BR-014–017 |
| *"Web dashboard that lists upcoming deliveries"* | DASH-REQ-013, DASH-REQ-020, DASH-REQ-021 |
| *"Who they are from"* | DASH-REQ-020 (description column), DM-BR-002 |
| *"Current status"* | DASH-REQ-020, DASH-REQ-043, NORM-REQ-001–014 |
| *"When they will be delivered"* | DASH-REQ-020, DASH-REQ-025, DASH-REQ-026 |
| *"Docker self-hosted"* | ADR-006, DEPLOY-REQ-001–048 |
| *"Retain all history for every delivery item"* | DM-BR-005, DM-BR-006, DM-BR-012, DM-BR-020 |
| *"Poll every 15 minutes"* | POLL-REQ-005 (`POLL_INTERVAL_MINUTES=15`) |

### 6.3 Parcel API Constraint Traceability

| API Constraint | Derived Requirements |
|----------------|---------------------|
| Rate limit: 20 req/hr | POLL-REQ-005 (min 5-min interval), POLL-REQ-006 (margin calc), POLL-REQ-024 (429 handling) |
| Cached responses | POLL-REQ-011 (filter_mode=recent justification) |
| `api-key` header (non-standard) | POLL-REQ-010 |
| Integer status codes 0–8 | NORM-REQ-001–014 (full normalisation layer) |
| Timezone-naive date strings | DM-BR-009, DM-BR-025, DASH-REQ-025, DASH-REQ-026 |
| No event IDs (deduplication needed) | DM-BR-007, POLL-REQ-017 |
| No webhooks (polling-only) | POLL-REQ-001–036 (entire polling service) |

---

## 7. Key Assumptions

The following assumptions were made during requirements definition. If any are incorrect, the affected requirements should be revisited.

| # | Assumption | Impact if Wrong | Requirements Affected |
|---|-----------|-----------------|----------------------|
| A-01 | The `description` field in the Parcel API response represents the user's label for the package (i.e. "who it's from / what it is") | Dashboard "sender" column would need a different data source | DM-BR-002, DASH-REQ-020 |
| A-02 | A single Parcel API key covers all deliveries the operator wants to track | Multi-account tracking would require multi-tenancy | All polling requirements |
| A-03 | The `filter_mode=recent` response includes all deliveries the operator cares about, including recently completed ones | Some deliveries may be missed if they age out of Parcel's "recent" window before being polled | POLL-REQ-011 |
| A-04 | Parcel API events are returned in chronological order (oldest first) in the `events` array | Event display order would be incorrect | DM-BR-008, DASH-REQ-037 |
| A-05 | A (tracking_number, carrier_code) pair uniquely identifies a delivery | The same tracking number could theoretically be reused | DM-BR-001, POLL-REQ-016 |
| A-06 | The service runs on a trusted local or private network | Relaxed security posture (HTTP allowed, single-user, no MFA) | SEC-REQ-041–044 |
| A-07 | "Full history" means indefinite retention with no archival or pruning | Storage grows unboundedly (slowly) | DM-BR-005, DM-BR-006 |
| A-08 | The single operator is the sole browser-based user; no concurrent sessions from multiple devices are a concern | token_version invalidation affects all devices simultaneously on logout | SEC-REQ-020 |
| A-09 | The Parcel API's supported_carriers.json endpoint is publicly accessible without authentication | Carrier name enrichment would fail silently | API-REQ-019, API-REQ-020 |
| A-10 | Python 3.12, Node 20, PostgreSQL 16, and Nginx alpine are the appropriate versions at the time of implementation | Dependency versions may be superseded | ADR-002, ADR-003, ADR-004 |

---

## 8. Open Questions & Deferred Features

### 8.1 Open Questions (Require Operator Answer Before Implementation)

| # | Question | Impact | Default Assumption |
|---|---------|--------|-------------------|
| OQ-01 | Will the service be exposed on the public internet, or only on a local/VPN network? | Determines urgency of HTTPS (SEC-REQ-041/042) and whether stronger brute-force protections are needed | Local network only |
| OQ-02 | Should a manual "refresh now" button in the dashboard trigger a new Parcel API poll, or just re-fetch cached data from the database? | Currently: re-fetches from DB only. A live poll trigger would require a new API endpoint and careful rate-limit accounting | Re-fetch from DB only |
| OQ-03 | Are there deliveries currently tracked in Parcel that should appear in the dashboard immediately on first run? | The first poll (cold start) will capture whatever Parcel returns as "recent" — deliveries that completed long ago will not appear | Only deliveries in Parcel's "recent" window are captured |
| OQ-04 | Is 25 the right default page size for the delivery list? | UX preference only | 25 (configurable in future) |

### 8.2 Deferred Features (Explicitly Out of Scope — Future Versions)

| Feature | Notes | Requirements to Add When Scoped |
|---------|-------|--------------------------------|
| **Status change notifications** | User confirmed "no notifications for now". Foundation is in place: `StatusHistory` records every transition and includes all data needed for notification dispatch. | Notification channel requirements, delivery/carrier preferences, quiet hours |
| **Password change UI** | Currently requires direct DB access. Low risk for single-user deployment. | New endpoint `POST /api/auth/change-password`; SEC-REQ-020 (token_version increment) already handles invalidation |
| **Manual poll trigger** | Button in dashboard to force an immediate Parcel API poll. Rate-limit accounting required. | New endpoint `POST /api/polls/trigger`; rate-limit guard (max 1 manual trigger per 5 min) |
| **Delivery notes / annotations** | Allow operator to add private notes to a delivery | New `delivery_notes` column or separate entity |
| **Multi-user support** | Additional users with the same or restricted access | Schema changes minor (users table already supports multiple rows); auth scope changes significant |
| **Delivery archival / hiding** | Option to hide delivered packages after N days | `is_archived` flag on deliveries; filter in API |
| **Dark mode** | Dashboard colour scheme | Frontend-only; no API changes |
| **Carrier-specific tracking URLs** | Link from dashboard to carrier's tracking page | Requires carrier→URL mapping; Parcel API does not provide tracking URLs |

---

## 9. Document Index

All supporting requirements documents are located in `docs/requirements/`:

| Doc | Title | Key Contents | Req Count |
|-----|-------|-------------|:---------:|
| **This document** | Master Requirements | Executive summary, catalogue, traceability, assumptions | 283 total |
| [01-architecture.md](./01-architecture.md) | Architecture & Technology Stack | 6 ADRs, component diagram, data flows, env var schema | 6 |
| [02-data-model.md](./02-data-model.md) | Data Model Requirements | 5 entities, ERD, field specs, 26 business rules, 4 migration rules | 30 |
| [03-polling-service.md](./03-polling-service.md) | Polling Service Requirements | Scheduler, change detection, error handling, sequence diagrams | 36 |
| [04-status-normalization.md](./04-status-normalization.md) | Status Normalisation Requirements | SemanticStatus enum, LifecycleGroup, transition matrix, function spec | 14 |
| [05-rest-api.md](./05-rest-api.md) | REST API Requirements | 7 endpoints, request/response schemas, auth, pagination | 28 |
| [06-web-dashboard.md](./06-web-dashboard.md) | Web Dashboard Requirements | Login, list, detail views; session management; accessibility | 60 |
| [07-auth-security.md](./07-auth-security.md) | Authentication & Security Requirements | bcrypt, JWT, CORS, brute force, HTTPS, Docker hardening | 61 |
| [08-deployment.md](./08-deployment.md) | Deployment & Configuration Requirements | Docker Compose, Nginx, env vars, health checks, backup | 48 |

---

*Generated from user scoping input, Parcel API documentation (//delivery-tracking/api-reference.md), and engineering best practices.*  
*All 283 requirements traceable to source. Full detail in phase documents linked above.*
