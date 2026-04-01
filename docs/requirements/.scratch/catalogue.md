### Architecture Decisions

| Req ID | Title (≤60 chars) | Priority | Source |
|--------|-------------------|:--------:|--------|
| ADR-001 | Monorepo, multi-container Git repo structure | M | AR |
| ADR-002 | Backend: Python 3.12 + FastAPI + Uvicorn | M | AR |
| ADR-003 | Database: PostgreSQL 16 with Alembic migrations | M | AR |
| ADR-004 | Frontend: React 18 + TypeScript + Vite | M | AR |
| ADR-005 | Reverse proxy: Nginx serves SPA and proxies API | M | AR |
| ADR-006 | Orchestration: Docker Compose v2, three services | M | AR |

---

### Data Model

| Req ID | Title (≤60 chars) | Priority | Source |
|--------|-------------------|:--------:|--------|
| DM-BR-001 | Composite key (tracking_number, carrier_code) unique | M | API |
| DM-BR-002 | description stores user-supplied Parcel label as-is | M | API |
| DM-BR-003 | timestamp_expected preferred over date_expected_raw | M | IN |
| DM-BR-004 | last_raw_response overwritten per poll (not history) | S | IN |
| DM-BR-005 | Delivery records never hard-deleted | M | UI |
| DM-BR-006 | DeliveryEvent records append-only and immutable | M | IN |
| DM-BR-007 | Event deduplication via (delivery_id, desc, date) key | M | IN |
| DM-BR-008 | sequence_number reflects Parcel API response array order | M | API |
| DM-BR-009 | event_date_raw stored as string; never parsed | M | IN |
| DM-BR-010 | StatusHistory written at delivery creation (NULL prev) | M | IN |
| DM-BR-011 | New StatusHistory record on every status change | M | IN |
| DM-BR-012 | StatusHistory records immutable (no update or delete) | M | IN |
| DM-BR-013 | detected_at is system detection time, not carrier time | S | IN |
| DM-BR-014 | Passwords stored as bcrypt hash only (cost ≥ 12) | M | IN |
| DM-BR-015 | Initial user seeded from ADMIN_USERNAME/PASSWORD env | M | UI |
| DM-BR-016 | is_active=false blocks login without deleting user | M | IN |
| DM-BR-017 | User records never deleted; deactivation only | S | IN |
| DM-BR-018 | PollLog created at poll cycle start | M | IN |
| DM-BR-019 | completed_at null indicates interrupted poll cycle | M | IN |
| DM-BR-020 | Poll logs retained indefinitely | S | IN |
| DM-BR-021 | semantic_status stored to enable DB-level filtering | M | IN |
| DM-BR-022 | Unrecognised status code stored as UNKNOWN, not error | M | IN |
| DM-BR-023 | StatusHistory semantic_status frozen at write time | M | IN |
| DM-BR-024 | timestamp_expected takes precedence for date sorting | M | IN |
| DM-BR-025 | Raw date strings must not be parsed to timestamps | M | IN |
| DM-BR-026 | Carrier names not stored; enriched client-side | S | IN |
| DM-MIG-001 | Every schema change requires an Alembic revision | M | IN |
| DM-MIG-002 | Migrations must be non-destructive during operation | M | IN |
| DM-MIG-003 | Initial migration creates all tables and constraints | M | IN |
| DM-MIG-004 | Seed script checks user count before running | M | IN |

---

### Polling Service

| Req ID | Title (≤60 chars) | Priority | Source |
|--------|-------------------|:--------:|--------|
| POLL-REQ-001 | Scheduler starts before app serves HTTP requests | M | IN |
| POLL-REQ-002 | Shutdown waits up to 30s for in-progress poll | M | IN |
| POLL-REQ-003 | Immediate cold-start poll on every application start | M | UI |
| POLL-REQ-004 | Cold-start poll does not count against interval timer | S | IN |
| POLL-REQ-005 | Poll interval configurable via env var; minimum 5 min | S | UI |
| POLL-REQ-006 | 15-min interval uses ~4 req/hr (80% rate limit margin) | M | API |
| POLL-REQ-007 | API key from env only; never hardcoded or logged | M | IN |
| POLL-REQ-008 | Startup fails if PARCEL_API_KEY absent or empty | M | IN |
| POLL-REQ-009 | API key never in logs, responses, or error messages | M | IN |
| POLL-REQ-010 | API key transmitted as api-key HTTP request header | M | API |
| POLL-REQ-011 | Use filter_mode=recent (not active) for all polls | M | API |
| POLL-REQ-012 | HTTP client instance reused across poll cycles | S | IN |
| POLL-REQ-013 | Validate response: HTTP status, JSON body, success flag | M | IN |
| POLL-REQ-014 | Empty deliveries array is valid, not an error | M | API |
| POLL-REQ-015 | Pre-poll DB snapshot loaded in single query | S | IN |
| POLL-REQ-016 | New delivery: insert delivery, status history, events | M | IN |
| POLL-REQ-017 | Existing delivery: diff status + events, update record | M | IN |
| POLL-REQ-018 | Delivery record updated even when no changes detected | M | IN |
| POLL-REQ-019 | Each delivery's DB operations in a single transaction | M | IN |
| POLL-REQ-020 | PollLog updated in separate post-processing transaction | M | IN |
| POLL-REQ-021 | Deliveries processed sequentially, not in parallel | S | IN |
| POLL-REQ-022 | semantic_status derived consistently via normalization.py | M | IN |
| POLL-REQ-023 | Unrecognised status code yields UNKNOWN + WARNING log | M | IN |
| POLL-REQ-024 | HTTP 429: log warning, mark error, skip cycle | M | API |
| POLL-REQ-025 | HTTP 401: log CRITICAL, skip cycle, no retry | M | IN |
| POLL-REQ-026 | 5xx/network errors: exponential backoff (15s/60s/120s) | M | IN |
| POLL-REQ-027 | Retry attempts logged at WARNING with attempt number | S | IN |
| POLL-REQ-028 | Total retry time per poll cycle capped at 10 minutes | S | IN |
| POLL-REQ-029 | Per-delivery failure: rollback, log error, continue | M | IN |
| POLL-REQ-030 | Partial success outcome distinct from full success | M | IN |
| POLL-REQ-031 | DB unavailable: abort poll, no Parcel API call made | M | IN |
| POLL-REQ-032 | max_instances=1; overlapping polls dropped with warning | M | IN |
| POLL-REQ-033 | API key must not appear in any log output | M | IN |
| POLL-REQ-034 | Each poll cycle assigned unique poll_id for correlation | S | IN |
| POLL-REQ-035 | Health endpoint exposes polling service indicators | S | IN |
| POLL-REQ-036 | Three or more consecutive errors flags degraded health | S | IN |

---

### Status Normalization

| Req ID | Title (≤60 chars) | Priority | Source |
|--------|-------------------|:--------:|--------|
| NORM-REQ-001 | Display labels defined in frontend, not backend API | M | IN |
| NORM-REQ-002 | Display labels must be 20 characters or fewer | S | IN |
| NORM-REQ-003 | lifecycle_group included in all delivery API responses | M | IN |
| NORM-REQ-004 | LifecycleGroup derived at runtime; never stored in DB | S | IN |
| NORM-REQ-005 | Anomalous terminal-state transitions: warn + persist | M | IN |
| NORM-REQ-006 | No transitions rejected or discarded; all persisted | M | IN |
| NORM-REQ-007 | Both parcel_status_code and semantic_status stored | M | IN |
| NORM-REQ-008 | StatusHistory stores full status pair for both states | M | IN |
| NORM-REQ-009 | Historical StatusHistory never retroactively modified | M | IN |
| NORM-REQ-010 | normalize_status() never raises; unknown codes → UNKNOWN | M | IN |
| NORM-REQ-011 | get_lifecycle_group() never raises for any input | M | IN |
| NORM-REQ-012 | 100% branch coverage required on normalization functions | S | IN |
| NORM-REQ-013 | STATUS_DISPLAY map only for labels; no inline strings | S | IN |
| NORM-REQ-014 | Badge colour by LifecycleGroup, not individual status | S | IN |

---

### REST API

| Req ID | Title (≤60 chars) | Priority | Source |
|--------|-------------------|:--------:|--------|
| API-REQ-001 | All endpoints except login/health require Bearer JWT | M | UI |
| API-REQ-002 | Invalid, expired, or missing token returns 401 | M | IN |
| API-REQ-003 | JWT signed HS256; JWT_SECRET_KEY minimum 32 chars | M | IN |
| API-REQ-004 | token_version claim validated on every request | M | IN |
| API-REQ-005 | All error responses use standard error envelope | S | IN |
| API-REQ-006 | Login failure never reveals username vs password | M | IN |
| API-REQ-007 | Successful login updates user's last_login_at | S | IN |
| API-REQ-008 | Refresh endpoint validates token_version claim | M | IN |
| API-REQ-009 | Logout increments token_version; clears refresh cookie | M | IN |
| API-REQ-010 | TERMINAL deliveries excluded from list by default | M | UI |
| API-REQ-011 | Search: case-insensitive substring on desc + tracking# | M | UI |
| API-REQ-012 | NULL timestamp_expected sorts last in ascending order | M | IN |
| API-REQ-013 | All timestamps serialised as ISO 8601 UTC strings | M | IN |
| API-REQ-014 | Events ordered seq ASC; status history by detected_at | M | IN |
| API-REQ-015 | Delivery detail endpoint is not paginated | S | IN |
| API-REQ-016 | /health responds in ≤5s; DB liveness timeout 3s | M | IN |
| API-REQ-017 | /health returns 200 for degraded, 503 for unhealthy | M | IN |
| API-REQ-018 | next_poll_at reflects scheduler's next fire time | S | IN |
| API-REQ-019 | /carriers never makes synchronous outbound API call | M | IN |
| API-REQ-020 | Stale carrier cache served without error to client | S | IN |
| API-REQ-021 | Security headers on all API responses | M | IN |
| API-REQ-022 | CORS restricted; no wildcard origins permitted | M | IN |
| API-REQ-023 | Swagger UI (/docs, /redoc) disabled in production | M | IN |
| API-REQ-024 | password_hash excluded from all API responses | M | IN |
| API-REQ-025 | Unhandled 500 errors use standard envelope; no traces | M | IN |
| API-REQ-026 | List endpoints use offset pagination (page + page_size) | M | UI |
| API-REQ-027 | Maximum page_size is 100 | S | IN |
| API-REQ-028 | Page beyond total returns empty items array, not 404 | S | IN |

---

### Web Dashboard

| Req ID | Title (≤60 chars) | Priority | Source |
|--------|-------------------|:--------:|--------|
| DASH-REQ-001 | Unauthenticated route access redirects to /login | M | UI |
| DASH-REQ-002 | Header present on all authenticated pages | M | UI |
| DASH-REQ-003 | Poll status indicator uses colour to signal health | S | UI |
| DASH-REQ-004 | Header health indicator auto-refreshes every 60 seconds | S | IN |
| DASH-REQ-005 | Login form: username, password, submit, error area | M | UI |
| DASH-REQ-006 | Submit button disabled and spinner shown during login | S | IN |
| DASH-REQ-007 | Invalid credentials show single generic error message | M | IN |
| DASH-REQ-008 | Disabled account shows specific error message | S | IN |
| DASH-REQ-009 | Network or 5xx error shows "Unable to connect" message | S | IN |
| DASH-REQ-010 | Login stores access token in context; navigates | M | UI |
| DASH-REQ-011 | Authenticated user at /login redirected to /deliveries | S | IN |
| DASH-REQ-012 | Login form submits on Enter key from any input | S | IN |
| DASH-REQ-013 | Filter tabs: All, Active, Needs Attention, Delivered | M | UI |
| DASH-REQ-014 | Needs Attention tab shows live badge count | S | UI |
| DASH-REQ-015 | Default tab is All; tab state persists in URL | S | IN |
| DASH-REQ-016 | Search across description and tracking number fields | M | UI |
| DASH-REQ-017 | Search debounced 300ms; no per-keystroke API calls | S | IN |
| DASH-REQ-018 | Search applies within the currently active tab filter | M | UI |
| DASH-REQ-019 | Active search shows a clear (✕) reset button | C | IN |
| DASH-REQ-020 | Table columns: Description, Carrier, Status, Expected | M | UI |
| DASH-REQ-021 | Default sort: Expected Delivery asc; indicator shown | S | IN |
| DASH-REQ-022 | Column click toggles sort direction; sort persists in URL | S | IN |
| DASH-REQ-023 | Entire table row is clickable to delivery detail page | M | UI |
| DASH-REQ-024 | Tracking number shown as secondary text in table row | S | UI |
| DASH-REQ-025 | Expected date: timestamp first, raw string, then dash | M | API |
| DASH-REQ-026 | Relative date labels computed in browser local timezone | M | IN |
| DASH-REQ-027 | Pagination controls shown when total pages exceeds one | M | IN |
| DASH-REQ-028 | Default page_size = 25 (not user-configurable) | S | UI |
| DASH-REQ-029 | Page number persists in URL as query parameter | S | IN |
| DASH-REQ-030 | Delivery list auto-refreshes every 5 minutes | M | UI |
| DASH-REQ-031 | Manual refresh button invalidates TanStack Query cache | S | UI |
| DASH-REQ-032 | Initial page load shows skeleton rows, not blank screen | S | IN |
| DASH-REQ-033 | Empty states defined for all conditions | S | IN |
| DASH-REQ-034 | Detail header: description, tracking, carrier, badge | M | UI |
| DASH-REQ-035 | Status history rendered as vertical timeline | S | UI |
| DASH-REQ-036 | Initial history entry labelled "First seen as:" | S | IN |
| DASH-REQ-037 | Events ordered by sequence_number ascending | M | IN |
| DASH-REQ-038 | Empty events array shows "No tracking events" message | S | IN |
| DASH-REQ-039 | Back link preserves list filter, sort, and search state | S | IN |
| DASH-REQ-040 | Detail page auto-refreshes every 5 minutes | S | UI |
| DASH-REQ-041 | Terminal delivery detail refresh extended to 30 minutes | C | IN |
| DASH-REQ-042 | Badge colour by lifecycle group; DELIVERED overrides green | S | IN |
| DASH-REQ-043 | Status badge shows display label, not enum or integer | M | IN |
| DASH-REQ-044 | ATTENTION lifecycle badges include warning icon | S | IN |
| DASH-REQ-045 | AuthContext holds token, isAuthenticated, login/logout | M | IN |
| DASH-REQ-046 | Access token in-memory only; never in storage or cookies | M | IN |
| DASH-REQ-047 | Silent token refresh attempted on application load | M | IN |
| DASH-REQ-048 | Full-screen spinner during silent refresh (no flash) | S | IN |
| DASH-REQ-049 | Axios interceptor attaches Bearer token to all requests | M | IN |
| DASH-REQ-050 | Axios interceptor auto-refreshes on 401; logout on fail | M | IN |
| DASH-REQ-051 | Logout: calls API, clears context and cache, → /login | M | UI |
| DASH-REQ-052 | All data-fetch errors handled with user-friendly messages | S | IN |
| DASH-REQ-053 | TanStack Query: 2 retries for data, 0 for auth endpoints | S | IN |
| DASH-REQ-054 | Global error boundary with fallback UI | S | IN |
| DASH-REQ-055 | Login form inputs have properly associated labels | M | IN |
| DASH-REQ-056 | Status badges include screen-reader text alternative | M | IN |
| DASH-REQ-057 | Table rows keyboard-navigable (role=button, Enter/Space) | M | IN |
| DASH-REQ-058 | Page title updates on every route change | S | IN |
| DASH-REQ-059 | Primary target: desktop viewport ≥ 1024px | S | UI |
| DASH-REQ-060 | Card layout for viewport width below 768px | S | UI |

---

### Authentication & Security

| Req ID | Title (≤60 chars) | Priority | Source |
|--------|-------------------|:--------:|--------|
| SEC-REQ-001 | bcrypt cost factor ≥ 12; no plaintext passwords stored | M | IN |
| SEC-REQ-002 | BCRYPT_ROUNDS configurable (10–15); validated at startup | S | IN |
| SEC-REQ-003 | Use passlib with bcrypt scheme for all password hashing | M | IN |
| SEC-REQ-004 | Warn if ADMIN_PASSWORD env var still set after seeding | M | IN |
| SEC-REQ-005 | Initial admin password minimum 12 characters | M | IN |
| SEC-REQ-006 | No password reset mechanism (documented limitation) | S | IN |
| SEC-REQ-007 | Usernames stored and compared case-sensitively | M | IN |
| SEC-REQ-008 | Constant-time verify; dummy hash check on unknown user | M | IN |
| SEC-REQ-009 | JWT tokens signed with HS256 using JWT_SECRET_KEY | M | IN |
| SEC-REQ-010 | JWT_SECRET_KEY ≥ 32 chars; startup fails if absent | M | IN |
| SEC-REQ-011 | JWT_SECRET_KEY rotation invalidates all active tokens | S | IN |
| SEC-REQ-012 | Token type claim validated; type confusion rejected | M | IN |
| SEC-REQ-013 | Access token TTL 60 min; refresh token TTL 7 days | M | UI |
| SEC-REQ-014 | TTL values outside permitted range rejected at startup | M | IN |
| SEC-REQ-015 | Six-step token validation on every protected request | M | IN |
| SEC-REQ-016 | All token failures return same 401; reason not disclosed | M | IN |
| SEC-REQ-017 | token_version DB lookup required on every request | M | IN |
| SEC-REQ-018 | Access + refresh tokens issued from same token_version | M | IN |
| SEC-REQ-019 | Refresh issues new access token only; no token rotation | S | IN |
| SEC-REQ-020 | token_version incremented on logout | M | IN |
| SEC-REQ-021 | token_version increment is an atomic DB operation | M | IN |
| SEC-REQ-022 | Refresh cookie: HttpOnly, SameSite=Strict, /api/auth | M | IN |
| SEC-REQ-023 | Secure cookie attribute controlled by COOKIE_SECURE env | M | IN |
| SEC-REQ-024 | Refresh token cookie scoped to /api/auth path only | M | IN |
| SEC-REQ-025 | Auth implemented as reusable FastAPI dependency | M | IN |
| SEC-REQ-026 | Routes protected by explicit dependency inclusion | M | IN |
| SEC-REQ-027 | User identity from auth dependency only, not request body | M | IN |
| SEC-REQ-028 | CORS not required in production (same Nginx origin) | S | IN |
| SEC-REQ-029 | CORSMiddleware dev-only; specific allowed origins only | M | IN |
| SEC-REQ-030 | CORSMiddleware not added in production environment | M | IN |
| SEC-REQ-031 | FastAPI middleware adds security headers to all responses | M | IN |
| SEC-REQ-032 | Nginx adds security headers including full CSP policy | M | IN |
| SEC-REQ-033 | CSP restricts all resources to self; no external loads | M | IN |
| SEC-REQ-034 | Server response header suppressed (no framework disclosure) | S | IN |
| SEC-REQ-035 | Login rate limit: 10 failed attempts per 15 min per IP | M | IN |
| SEC-REQ-036 | Rate limit state stored in application memory | S | IN |
| SEC-REQ-037 | Rate limit counts failed attempts only; success resets | M | IN |
| SEC-REQ-038 | Rate limit exceeded returns 429 RATE_LIMITED response | M | IN |
| SEC-REQ-039 | Retry-After header included in rate-limited responses | S | IN |
| SEC-REQ-040 | Rate limit by source IP; X-Forwarded-For when trusted | M | IN |
| SEC-REQ-041 | Nginx optional HTTPS via HTTPS_ENABLED + cert volumes | S | UI |
| SEC-REQ-042 | HTTPS mode: TLS 1.2+ only; HTTP redirects to HTTPS | M | IN |
| SEC-REQ-043 | HTTP-only mode acceptable for local/private network use | S | UI |
| SEC-REQ-044 | COOKIE_SECURE required when HTTPS_ENABLED=true | M | IN |
| SEC-REQ-045 | All secrets via env vars; never in source code or images | M | IN |
| SEC-REQ-046 | .env.example committed to source control; .env ignored | M | IN |
| SEC-REQ-047 | Startup fails if any required secret is absent | M | IN |
| SEC-REQ-048 | Startup fails if JWT key < 32 chars or password < 12 | M | IN |
| SEC-REQ-049 | api container runs as dedicated non-root system user | M | IN |
| SEC-REQ-050 | Nginx worker process runs as non-root user | M | IN |
| SEC-REQ-051 | api container filesystem treated as read-only at runtime | S | IN |
| SEC-REQ-052 | Secrets via env_file; not hardcoded in compose/Dockerfiles | M | IN |
| SEC-REQ-053 | postgres port not exposed on host in production | M | IN |
| SEC-REQ-054 | Docker image versions pinned to specific tags; no latest | S | IN |
| SEC-REQ-055 | All API inputs validated by Pydantic before handler logic | M | IN |
| SEC-REQ-056 | All DB queries use ORM or parameterised SQL expressions | M | IN |
| SEC-REQ-057 | Field lengths enforced at Pydantic and DB schema levels | M | IN |
| SEC-REQ-058 | Search uses parameterised LIKE expression; no interpolation | M | IN |
| SEC-REQ-059 | Security events logged at INFO level for audit trail | S | IN |
| SEC-REQ-060 | Source IP included in all security audit log entries | S | IN |
| SEC-REQ-061 | No secret values in log output at any log level | M | IN |

---

### Deployment & Configuration

| Req ID | Title (≤60 chars) | Priority | Source |
|--------|-------------------|:--------:|--------|
| DEPLOY-REQ-001 | All services on shared Docker bridge network | M | UI |
| DEPLOY-REQ-002 | postgres and api ports not exposed on host machine | M | UI |
| DEPLOY-REQ-003 | frontend exposes port 80; configurable via env var | M | UI |
| DEPLOY-REQ-004 | api depends on postgres with service_healthy condition | M | IN |
| DEPLOY-REQ-005 | restart: unless-stopped applied to all three services | M | IN |
| DEPLOY-REQ-006 | api Dockerfile uses two-stage build | S | IN |
| DEPLOY-REQ-007 | api runtime image based on python:3.12-slim | S | IN |
| DEPLOY-REQ-008 | api container runs as non-root appuser | M | IN |
| DEPLOY-REQ-009 | .env file never copied into api Docker image | M | IN |
| DEPLOY-REQ-010 | api container startup managed by entrypoint.sh script | M | IN |
| DEPLOY-REQ-011 | frontend Dockerfile uses multi-stage build | S | IN |
| DEPLOY-REQ-012 | npm ci used in frontend build (not npm install) | S | IN |
| DEPLOY-REQ-013 | frontend runtime image: static assets and Nginx only | S | IN |
| DEPLOY-REQ-014 | postgres uses official postgres:16.3-alpine unchanged | S | IN |
| DEPLOY-REQ-015 | postgres_data named volume at /var/lib/postgresql/data | M | IN |
| DEPLOY-REQ-016 | postgres_data uses local volume driver | S | IN |
| DEPLOY-REQ-017 | postgres_data persists across restarts and rebuilds | M | UI |
| DEPLOY-REQ-018 | Volume destruction requires --volumes flag; documented | M | IN |
| DEPLOY-REQ-019 | SSL certs provided via read-only bind mounts | S | IN |
| DEPLOY-REQ-020 | api and frontend containers stateless (no data volumes) | S | IN |
| DEPLOY-REQ-021 | entrypoint.sh: run migrations, seed, start uvicorn | M | IN |
| DEPLOY-REQ-022 | set -e in entrypoint; migration or seed failure stops | M | IN |
| DEPLOY-REQ-023 | Uvicorn started with --workers 1 (single worker) | M | IN |
| DEPLOY-REQ-024 | Uvicorn binds to 0.0.0.0 for Docker network reachability | M | IN |
| DEPLOY-REQ-025 | Uvicorn started with --no-access-log | C | IN |
| DEPLOY-REQ-026 | Seed script creates admin user when users table is empty | M | IN |
| DEPLOY-REQ-027 | Seed script is idempotent (safe to re-run) | M | IN |
| DEPLOY-REQ-028 | Seed exits non-zero if DB empty and credentials not set | M | IN |
| DEPLOY-REQ-029 | Nginx: /api/* proxied to api:8000; SPA fallback | M | IN |
| DEPLOY-REQ-030 | try_files directive enables React Router SPA routing | M | IN |
| DEPLOY-REQ-031 | Static assets served with Cache-Control immutable, 1yr | S | IN |
| DEPLOY-REQ-032 | Nginx sets X-Real-IP and X-Forwarded-For on proxied reqs | M | IN |
| DEPLOY-REQ-033 | HTTPS: HTTP→HTTPS redirect; TLS 1.2+ ciphers only | S | IN |
| DEPLOY-REQ-034 | HTTPS Nginx config in separate nginx-https.conf file | S | IN |
| DEPLOY-REQ-035 | postgres healthcheck: pg_isready, 10s interval, 30s start | M | IN |
| DEPLOY-REQ-036 | api healthcheck: GET /api/health, 30s interval, 60s start | M | IN |
| DEPLOY-REQ-037 | frontend healthcheck: GET /, 30s interval | S | IN |
| DEPLOY-REQ-038 | Log rotation: max-size 50m, max-file 5 on api/frontend | S | IN |
| DEPLOY-REQ-039 | postgres log rotation managed internally by PostgreSQL | C | IN |
| DEPLOY-REQ-040 | api service logs to stdout/stderr only (not files) | M | IN |
| DEPLOY-REQ-041 | Upgrade procedure: docker compose build + up -d | S | IN |
| DEPLOY-REQ-042 | Alembic migrations run automatically on api container start | M | IN |
| DEPLOY-REQ-043 | Schema downgrade requires manual alembic procedure | S | IN |
| DEPLOY-REQ-044 | pg_dump backup procedure documented in operator guide | S | IN |
| DEPLOY-REQ-045 | No automated backup; operator's responsibility | S | IN |
| DEPLOY-REQ-046 | Minimum resources: 1 CPU core, 512 MB RAM, 1 GB storage | S | UI |
| DEPLOY-REQ-047 | Optional resource limits in compose (commented by default) | C | IN |
| DEPLOY-REQ-048 | .env.example with all variables, placeholders, comments | M | IN |

---

### Summary Counts

| Domain | Total Reqs | Must Have | Should Have | Could Have |
|--------|:----------:|:---------:|:-----------:|:----------:|
| Architecture Decisions | 6 | 6 | 0 | 0 |
| Data Model | 30 | 25 | 5 | 0 |
| Polling Service | 36 | 26 | 10 | 0 |
| Status Normalization | 14 | 9 | 5 | 0 |
| REST API | 28 | 21 | 7 | 0 |
| Web Dashboard | 60 | 26 | 32 | 2 |
| Authentication & Security | 61 | 47 | 14 | 0 |
| Deployment & Configuration | 48 | 26 | 19 | 3 |
| **Totals** | **283** | **186** | **92** | **5** |
