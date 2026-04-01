# REST API Requirements

**Document ID**: API-001  
**Plan Phase**: Phase 5  
**Status**: Draft — Awaiting Review  
**Project**: Delivery Tracking Web Service  
**Dependencies**: [01-architecture.md](./01-architecture.md), [02-data-model.md](./02-data-model.md), [04-status-normalization.md](./04-status-normalization.md)

---

## 1. Overview

The REST API is served by the FastAPI backend at path prefix `/api/`. All routes except `POST /api/auth/login` and `GET /api/health` require a valid JWT access token.

FastAPI automatically generates an OpenAPI 3.1 specification and interactive Swagger UI at `/api/docs` (development only — disabled in production).

### Base URL
```
http://<host>/api
```
All paths in this document are relative to this base.

### Content Type
All request and response bodies use `application/json` unless otherwise specified.

---

## 2. Authentication Overview

**API-REQ-001**: All endpoints except `POST /auth/login` and `GET /health` MUST require a valid JWT access token, provided in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

**API-REQ-002**: A missing, malformed, expired, or invalidated token MUST return `401 Unauthorized` with error code `UNAUTHORIZED`.

**API-REQ-003**: JWT tokens are signed with `HS256` using the `JWT_SECRET_KEY` environment variable. The key MUST be at least 32 characters.

### Token Design

| Token | TTL | Purpose | Storage (client) |
|-------|-----|---------|-----------------|
| Access token | 60 min (configurable) | Authorise API calls | In-memory (React state) |
| Refresh token | 7 days (configurable) | Obtain new access tokens | `httpOnly` cookie |

**Access token claims**:
```json
{
  "sub": "username",
  "type": "access",
  "token_version": 1,
  "iat": 1736942400,
  "exp": 1736946000
}
```

**Refresh token claims**:
```json
{
  "sub": "username",
  "type": "refresh",
  "token_version": 1,
  "iat": 1736942400,
  "exp": 1737547200
}
```

**API-REQ-004**: Both token types MUST include a `token_version` claim matching the `token_version` field stored in the `users` table. On validation, the server MUST verify the claim matches the stored version. This enables instant invalidation of all outstanding tokens for a user by incrementing `token_version` — for example, on password change or forced logout.

> **Data model addition**: The `users` table requires a `token_version INTEGER NOT NULL DEFAULT 1` column. This was not included in Phase 2 and must be added via migration.

---

## 3. Standard Response Envelopes

### 3.1 Success — Single Resource
```json
{
  "data": { ... }
}
```

### 3.2 Success — Collection
```json
{
  "data": {
    "items": [ ... ],
    "total": 42,
    "page": 1,
    "page_size": 20,
    "pages": 3
  }
}
```

### 3.3 Error Envelope
All error responses use a consistent shape regardless of HTTP status code:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": null
  }
}
```

**API-REQ-005**: All error responses MUST use the envelope above. The `code` field is a machine-readable SCREAMING_SNAKE_CASE string. The `message` field is suitable for developer logging but MUST NOT expose internal stack traces, file paths, or database query details. `details` may be an object or array for validation errors (see §3.4).

### 3.4 Validation Error Detail
For `422 Unprocessable Entity` (invalid request body/query params):
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Request validation failed",
    "details": [
      {
        "field": "page_size",
        "message": "Must be between 1 and 100"
      }
    ]
  }
}
```

### 3.5 Standard Error Codes

| HTTP Status | Error Code | Meaning |
|-------------|-----------|---------|
| `400` | `BAD_REQUEST` | Malformed request |
| `401` | `UNAUTHORIZED` | Missing, invalid, or expired token |
| `403` | `FORBIDDEN` | Token valid but insufficient permission |
| `404` | `NOT_FOUND` | Resource does not exist |
| `422` | `VALIDATION_ERROR` | Request body/params failed validation |
| `429` | `RATE_LIMITED` | Too many requests |
| `500` | `INTERNAL_ERROR` | Unexpected server error |
| `503` | `SERVICE_UNAVAILABLE` | Database or critical dependency unavailable |

---

## 4. Endpoint Catalogue

### 4.1 Authentication Endpoints

---

#### `POST /auth/login`

Authenticate with username and password. Returns an access token in the response body and sets a `refresh_token` httpOnly cookie.

**Authentication required**: No

**Request body**:
```json
{
  "username": "string",
  "password": "string"
}
```

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `username` | string | ✅ | 1–100 characters |
| `password` | string | ✅ | 1–200 characters |

**Response `200 OK`**:
```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 3600
  }
}
```

**Response headers** (on success):
```
Set-Cookie: refresh_token=<jwt>; HttpOnly; SameSite=Strict; Path=/api/auth; Max-Age=604800
```

**Error responses**:

| HTTP | Code | Condition |
|------|------|-----------|
| `401` | `INVALID_CREDENTIALS` | Username not found or password incorrect |
| `403` | `ACCOUNT_DISABLED` | User exists but `is_active = false` |
| `422` | `VALIDATION_ERROR` | Missing or malformed fields |

**API-REQ-006**: On authentication failure, the response MUST NOT distinguish between "username not found" and "incorrect password". Both MUST return `401 INVALID_CREDENTIALS`. This prevents username enumeration.

**API-REQ-007**: On successful login, `last_login_at` on the `users` record MUST be updated.

---

#### `POST /auth/refresh`

Exchange a valid refresh token for a new access token. The refresh token is read from the `refresh_token` httpOnly cookie.

**Authentication required**: No (uses cookie)

**Request body**: None

**Response `200 OK`**:
```json
{
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
    "token_type": "bearer",
    "expires_in": 3600
  }
}
```

**Error responses**:

| HTTP | Code | Condition |
|------|------|-----------|
| `401` | `UNAUTHORIZED` | Cookie absent, token invalid, token expired, or `token_version` mismatch |

**API-REQ-008**: The refresh endpoint MUST validate the `token_version` claim in the refresh token against the current `users.token_version`. A mismatch (e.g. after a forced logout or password change) MUST return `401 UNAUTHORIZED`.

---

#### `POST /auth/logout`

Invalidate the current session by incrementing the user's `token_version`, immediately invalidating all outstanding access and refresh tokens.

**Authentication required**: Yes (Bearer token)

**Request body**: None

**Response `204 No Content`**: (no body)

**Response headers**:
```
Set-Cookie: refresh_token=; HttpOnly; SameSite=Strict; Path=/api/auth; Max-Age=0
```

**API-REQ-009**: On logout, `users.token_version` MUST be incremented. This immediately invalidates all tokens (both access and refresh) issued under the previous version. The response MUST also clear the `refresh_token` cookie.

---

### 4.2 Delivery Endpoints

---

#### `GET /deliveries`

List deliveries with filtering, sorting, and pagination. This is the primary endpoint for the dashboard delivery list view.

**Authentication required**: Yes

**Query parameters**:

| Parameter | Type | Default | Constraints | Description |
|-----------|------|---------|-------------|-------------|
| `page` | integer | `1` | ≥ 1 | Page number (1-based) |
| `page_size` | integer | `20` | 1–100 | Items per page |
| `lifecycle_group` | string | — | `ACTIVE`, `ATTENTION`, `TERMINAL` | Filter by lifecycle group |
| `semantic_status` | string | — | Any `SemanticStatus` value | Filter by specific status (overrides `lifecycle_group`) |
| `carrier_code` | string | — | Max 50 chars | Filter by carrier |
| `search` | string | — | Max 200 chars | Free-text search across `description` and `tracking_number` (case-insensitive, substring match) |
| `sort_by` | string | `timestamp_expected` | See sort fields below | Field to sort by |
| `sort_dir` | string | `asc` | `asc`, `desc` | Sort direction |
| `include_terminal` | boolean | `false` | — | When `false`, `TERMINAL` deliveries are excluded unless `lifecycle_group=TERMINAL` or `semantic_status` targets a terminal status |

**Allowed `sort_by` values**:

| Value | Sorts By | NULL handling |
|-------|---------|---------------|
| `timestamp_expected` | `deliveries.timestamp_expected` | NULLs last |
| `updated_at` | `deliveries.updated_at` | — |
| `carrier_code` | `deliveries.carrier_code` | — |
| `description` | `deliveries.description` | — |
| `semantic_status` | `deliveries.semantic_status` | — |
| `first_seen_at` | `deliveries.first_seen_at` | — |

**API-REQ-010**: When `include_terminal` is `false` (the default), deliveries with `lifecycle_group = TERMINAL` MUST be excluded from results. This represents the dashboard's default "active + attention" view. The total count in the response MUST reflect the filtered set, not the full dataset.

**API-REQ-011**: `search` performs a case-insensitive substring match against both `description` and `tracking_number`. A delivery is included if either field matches.

**API-REQ-012**: When `sort_by=timestamp_expected`, deliveries with a NULL `timestamp_expected` MUST sort last regardless of `sort_dir`. This ensures deliveries with no expected date don't crowd the top of an ascending sort.

**Response `200 OK`**:
```json
{
  "data": {
    "items": [
      {
        "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "tracking_number": "1Z999AA10123456784",
        "carrier_code": "ups",
        "description": "Amazon - MacBook Pro",
        "semantic_status": "IN_TRANSIT",
        "lifecycle_group": "ACTIVE",
        "parcel_status_code": 2,
        "date_expected_raw": "2025-01-16 12:00",
        "date_expected_end_raw": "2025-01-16 18:00",
        "timestamp_expected": "2025-01-16T12:00:00Z",
        "timestamp_expected_end": "2025-01-16T18:00:00Z",
        "first_seen_at": "2025-01-10T09:00:00Z",
        "last_seen_at": "2025-01-15T14:30:00Z",
        "updated_at": "2025-01-15T14:30:00Z"
      }
    ],
    "total": 8,
    "page": 1,
    "page_size": 20,
    "pages": 1
  }
}
```

**Delivery summary schema**:

| Field | Type | Always Present | Description |
|-------|------|:--------------:|-------------|
| `id` | UUID string | ✅ | Internal delivery ID |
| `tracking_number` | string | ✅ | Carrier tracking number |
| `carrier_code` | string | ✅ | Parcel internal carrier code |
| `description` | string | ✅ | User-supplied delivery label (sender/description) |
| `semantic_status` | string | ✅ | Normalized status enum value |
| `lifecycle_group` | string | ✅ | `ACTIVE`, `ATTENTION`, or `TERMINAL` |
| `parcel_status_code` | integer | ✅ | Raw Parcel status code (0–8) |
| `date_expected_raw` | string \| null | — | Timezone-naive expected delivery string |
| `date_expected_end_raw` | string \| null | — | Timezone-naive end of delivery window |
| `timestamp_expected` | ISO8601 string \| null | — | UTC timestamp for expected delivery |
| `timestamp_expected_end` | ISO8601 string \| null | — | UTC timestamp for end of delivery window |
| `first_seen_at` | ISO8601 string | ✅ | When the service first discovered this delivery |
| `last_seen_at` | ISO8601 string | ✅ | Most recent poll that returned this delivery |
| `updated_at` | ISO8601 string | ✅ | Most recent change to this record |

**API-REQ-013**: Timestamps stored as `TIMESTAMPTZ` in PostgreSQL MUST be serialised as ISO 8601 strings in UTC with `Z` suffix (e.g. `"2025-01-16T12:00:00Z"`), never as Unix integers, in all API responses.

---

#### `GET /deliveries/{delivery_id}`

Retrieve full detail for a single delivery, including its complete event history and status change timeline.

**Authentication required**: Yes

**Path parameters**:

| Parameter | Type | Description |
|-----------|------|-------------|
| `delivery_id` | UUID | Internal delivery ID |

**Response `200 OK`**:
```json
{
  "data": {
    "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "tracking_number": "1Z999AA10123456784",
    "carrier_code": "ups",
    "description": "Amazon - MacBook Pro",
    "extra_information": "SW1A 1AA",
    "semantic_status": "IN_TRANSIT",
    "lifecycle_group": "ACTIVE",
    "parcel_status_code": 2,
    "date_expected_raw": "2025-01-16 12:00",
    "date_expected_end_raw": "2025-01-16 18:00",
    "timestamp_expected": "2025-01-16T12:00:00Z",
    "timestamp_expected_end": "2025-01-16T18:00:00Z",
    "first_seen_at": "2025-01-10T09:00:00Z",
    "last_seen_at": "2025-01-15T14:30:00Z",
    "updated_at": "2025-01-15T14:30:00Z",
    "events": [
      {
        "id": "9b2e4f11-3c18-4e9a-a7d2-1b3f4e5c6d7e",
        "event_description": "Package arrived at facility",
        "event_date_raw": "2025-01-15 14:30",
        "location": "London, UK",
        "additional_info": "Sorted for next-day delivery",
        "sequence_number": 0,
        "recorded_at": "2025-01-15T14:35:00Z"
      }
    ],
    "status_history": [
      {
        "id": "1a2b3c4d-5e6f-7a8b-9c0d-1e2f3a4b5c6d",
        "previous_status_code": null,
        "previous_semantic_status": null,
        "new_status_code": 8,
        "new_semantic_status": "INFO_RECEIVED",
        "detected_at": "2025-01-10T09:00:00Z"
      },
      {
        "id": "2b3c4d5e-6f7a-8b9c-0d1e-2f3a4b5c6d7e",
        "previous_status_code": 8,
        "previous_semantic_status": "INFO_RECEIVED",
        "new_status_code": 2,
        "new_semantic_status": "IN_TRANSIT",
        "detected_at": "2025-01-12T08:15:00Z"
      }
    ]
  }
}
```

**Additional fields in detail response** (beyond the summary schema):

| Field | Type | Always Present | Description |
|-------|------|:--------------:|-------------|
| `extra_information` | string \| null | — | Auxiliary carrier tracking info (postcode, email) |
| `events` | Event[] | ✅ | All tracking events, ordered by `sequence_number ASC`. May be empty `[]`. |
| `status_history` | StatusHistoryEntry[] | ✅ | Full status change log, ordered by `detected_at ASC`. Always contains at least one entry (the initial status). |

**Event schema**:

| Field | Type | Always Present | Description |
|-------|------|:--------------:|-------------|
| `id` | UUID string | ✅ | Event ID |
| `event_description` | string | ✅ | Event description text |
| `event_date_raw` | string | ✅ | Raw date/time string (display as-is) |
| `location` | string \| null | — | Location of the event |
| `additional_info` | string \| null | — | Supplementary carrier info |
| `sequence_number` | integer | ✅ | Position in the carrier's event sequence |
| `recorded_at` | ISO8601 string | ✅ | When the service first recorded this event |

**StatusHistoryEntry schema**:

| Field | Type | Always Present | Description |
|-------|------|:--------------:|-------------|
| `id` | UUID string | ✅ | History entry ID |
| `previous_status_code` | integer \| null | — | Raw code before change; null for initial entry |
| `previous_semantic_status` | string \| null | — | Semantic status before change; null for initial entry |
| `new_status_code` | integer | ✅ | Raw code after change |
| `new_semantic_status` | string | ✅ | Semantic status after change |
| `detected_at` | ISO8601 string | ✅ | When the polling service detected this transition |

**Error responses**:

| HTTP | Code | Condition |
|------|------|-----------|
| `404` | `NOT_FOUND` | No delivery with this ID exists |

**API-REQ-014**: Events MUST be ordered by `sequence_number ASC` in the response. Status history MUST be ordered by `detected_at ASC`. Neither is paginated — all records are returned in full.

**API-REQ-015**: The delivery detail endpoint MUST NOT be paginated. The data volume per delivery is bounded (events and history grow slowly) and pagination would complicate dashboard timeline rendering.

---

### 4.3 System Endpoints

---

#### `GET /health`

Returns the operational health of the service. Intended for Docker health checks, monitoring, and the dashboard's "last updated" indicator.

**Authentication required**: No

**Response `200 OK`** (healthy or degraded):
```json
{
  "data": {
    "status": "healthy",
    "database": {
      "status": "connected",
      "latency_ms": 3
    },
    "polling": {
      "scheduler_running": true,
      "last_poll_at": "2025-01-15T14:30:00Z",
      "last_poll_outcome": "success",
      "last_successful_poll_at": "2025-01-15T14:30:00Z",
      "consecutive_errors": 0,
      "next_poll_at": "2025-01-15T14:45:00Z"
    },
    "version": "1.0.0"
  }
}
```

**Response `503 Service Unavailable`** (unhealthy — database unreachable):
```json
{
  "data": {
    "status": "unhealthy",
    "database": {
      "status": "disconnected",
      "latency_ms": null
    },
    "polling": {
      "scheduler_running": false,
      ...
    },
    "version": "1.0.0"
  }
}
```

**Health status rules**:

| `status` | HTTP | Conditions |
|----------|------|-----------|
| `healthy` | `200` | DB connected, scheduler running, `consecutive_errors < 3` |
| `degraded` | `200` | DB connected, scheduler running, `consecutive_errors >= 3` |
| `unhealthy` | `503` | DB unreachable OR scheduler not running |

**API-REQ-016**: The `/health` endpoint MUST respond within 5 seconds regardless of database state. A DB liveness check timeout MUST be set to 3 seconds. If the timeout expires, `database.status = "disconnected"`.

**API-REQ-017**: `/health` MUST return `200` for both `healthy` and `degraded` states, and `503` only for `unhealthy`. This allows the dashboard to display a warning without the Docker health check marking the container as failed on polling hiccups.

**API-REQ-018**: The `next_poll_at` field MUST reflect the APScheduler's next scheduled fire time. If the scheduler is not running, this field MUST be `null`.

---

#### `GET /carriers`

Returns the list of supported carrier codes and display names, sourced from the Parcel API's carrier codes JSON file. This response is cached in application memory to avoid unnecessary outbound requests.

**Authentication required**: Yes

**Query parameters**: None

**Caching behaviour**:
- On first request (or after cache expiry), fetch `https://api.parcel.app/external/supported_carriers.json`
- Cache in application memory for 24 hours
- If the Parcel carrier endpoint is unavailable and no cache exists, return an empty list with `cache_status: "unavailable"`

**Response `200 OK`**:
```json
{
  "data": {
    "carriers": [
      { "code": "ups", "name": "UPS" },
      { "code": "royalmail", "name": "Royal Mail" },
      { "code": "fedex", "name": "FedEx" }
    ],
    "cached_at": "2025-01-15T00:00:00Z",
    "cache_status": "fresh"
  }
}
```

**Carrier schema**:

| Field | Type | Description |
|-------|------|-------------|
| `code` | string | Parcel internal carrier code (matches `carrier_code` on deliveries) |
| `name` | string | Human-readable carrier name |

**`cache_status` values**: `fresh` (within TTL), `stale` (TTL expired, still serving cached), `unavailable` (never successfully fetched)

**API-REQ-019**: The `/carriers` endpoint MUST NOT make a synchronous outbound call on every request. The carrier list is fetched at application startup and refreshed every 24 hours by a low-priority background task (separate from the polling scheduler).

**API-REQ-020**: If the Parcel carrier endpoint is unreachable during a refresh attempt, the existing cached data MUST continue to be served with `cache_status: "stale"`. The service MUST NOT return an error to the client when carrier data is merely stale.

---

## 5. API Security Requirements

**API-REQ-021**: All API responses MUST include the following security headers:

```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
```

**API-REQ-022**: CORS is not required because Nginx serves the frontend on the same origin as the API. FastAPI's CORS middleware MUST NOT allow wildcard origins (`*`). If CORS is configured (e.g. for local development), it MUST be restricted to specific allowed origins.

**API-REQ-023**: The FastAPI application MUST NOT expose the auto-generated `/api/docs` (Swagger UI) or `/api/redoc` endpoints in production (i.e. when `ENVIRONMENT=production`). These endpoints may be enabled in development mode.

**API-REQ-024**: Passwords MUST never appear in any API response, including the user object if one is ever returned. The `users` table's `password_hash` column is permanently excluded from all serialization paths.

**API-REQ-025**: FastAPI's default exception handler for unhandled `500` errors MUST be overridden to return the standard error envelope (§3.3) with `code: "INTERNAL_ERROR"` and a generic message, never exposing internal stack traces.

---

## 6. Pagination Requirements

**API-REQ-026**: All list endpoints that may return more than one page of results MUST use **offset-based pagination** with `page` (1-based) and `page_size` parameters.

**API-REQ-027**: The maximum `page_size` is `100`. Requests with `page_size > 100` MUST return `422 VALIDATION_ERROR`.

**API-REQ-028**: When the requested `page` exceeds the total number of pages, the response MUST return an empty `items` array with the correct `total` and `pages` values — NOT a `404` error.

---

## 7. Route Summary

| Method | Path | Auth | Description |
|--------|------|:----:|-------------|
| `POST` | `/auth/login` | ❌ | Authenticate; receive access token + refresh cookie |
| `POST` | `/auth/refresh` | ❌ (cookie) | Exchange refresh cookie for new access token |
| `POST` | `/auth/logout` | ✅ | Invalidate all tokens; clear refresh cookie |
| `GET` | `/deliveries` | ✅ | List deliveries (filtered, sorted, paginated) |
| `GET` | `/deliveries/{id}` | ✅ | Full delivery detail with events and history |
| `GET` | `/health` | ❌ | Service health (DB, polling, scheduler) |
| `GET` | `/carriers` | ✅ | Carrier code → name mapping (cached) |

---

## 8. OpenAPI Tags

FastAPI route groups for Swagger documentation:

| Tag | Routes | Description |
|-----|--------|-------------|
| `auth` | `/auth/*` | Authentication and session management |
| `deliveries` | `/deliveries/*` | Delivery tracking resources |
| `system` | `/health`, `/carriers` | Operational and reference data |

---

## 9. Requirements Summary

| ID | Requirement |
|----|-------------|
| API-REQ-001 | All endpoints except login and health require Bearer token |
| API-REQ-002 | Invalid/expired token → 401 UNAUTHORIZED |
| API-REQ-003 | JWT signed with HS256 using JWT_SECRET_KEY (min 32 chars) |
| API-REQ-004 | token_version claim validated server-side on every request |
| API-REQ-005 | All errors use standard error envelope |
| API-REQ-006 | Login failure never distinguishes username vs password |
| API-REQ-007 | Successful login updates last_login_at |
| API-REQ-008 | Refresh validates token_version; mismatch → 401 |
| API-REQ-009 | Logout increments token_version, clears cookie |
| API-REQ-010 | include_terminal=false excludes TERMINAL by default |
| API-REQ-011 | search is case-insensitive substring on description + tracking_number |
| API-REQ-012 | NULL timestamp_expected sorts last in ascending sort |
| API-REQ-013 | All timestamps serialised as ISO 8601 UTC strings |
| API-REQ-014 | Events ordered by sequence_number ASC; history by detected_at ASC |
| API-REQ-015 | Delivery detail not paginated |
| API-REQ-016 | /health responds within 5s; DB check timeout 3s |
| API-REQ-017 | /health returns 200 for degraded, 503 only for unhealthy |
| API-REQ-018 | next_poll_at reflects scheduler's next fire time |
| API-REQ-019 | /carriers never makes synchronous outbound call per request |
| API-REQ-020 | Stale carrier cache served without error |
| API-REQ-021 | Security headers on all responses |
| API-REQ-022 | CORS restricted; no wildcard origins |
| API-REQ-023 | /docs and /redoc disabled in production |
| API-REQ-024 | password_hash never in any API response |
| API-REQ-025 | 500 errors use standard envelope, no stack traces |
| API-REQ-026 | List endpoints use offset pagination (page + page_size) |
| API-REQ-027 | Max page_size = 100 |
| API-REQ-028 | Page beyond total returns empty items, not 404 |

---

*Source: User scoping input, data model (02-data-model.md), status normalization (04-status-normalization.md), architecture (01-architecture.md)*  
*Traceability: API-REQ-001 through API-REQ-028*  
*Data model note: users table requires `token_version INTEGER NOT NULL DEFAULT 1` column (migration required)*
