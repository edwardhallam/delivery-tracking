# Authentication & Security Requirements

**Document ID**: SEC-001  
**Plan Phase**: Phase 7  
**Status**: Draft — Awaiting Review  
**Project**: Delivery Tracking Web Service  
**Dependencies**: [01-architecture.md](./01-architecture.md), [02-data-model.md](./02-data-model.md), [05-rest-api.md](./05-rest-api.md), [06-web-dashboard.md](./06-web-dashboard.md)

---

## 1. Overview

This document defines security requirements for the Delivery Tracking Service in its self-hosted, single-user, Docker-deployed context. Security decisions are calibrated for this threat model: a service exposed on a home or private network, accessed by one trusted user, wrapping a read-only third-party API.

**Threat model:**

| Threat | Likelihood | Mitigation Priority |
|--------|-----------|-------------------|
| Credential brute force from local network | Medium | High |
| XSS token theft | Low–Medium | High |
| CSRF attack | Low (SameSite=Strict) | Medium |
| Exposed secrets in environment/logs | Medium | High |
| Container breakout | Low | Medium |
| Man-in-the-middle (no HTTPS) | Low–Medium (local) | Medium |
| SQL injection | Low (ORM) | Maintained |
| Parcel API key leakage | Medium | High |

---

## 2. Credential Security

### 2.1 Password Hashing

**SEC-REQ-001**: All passwords MUST be hashed using **bcrypt** with a minimum work factor (cost) of **12**. Plaintext passwords MUST never be stored, logged, or transmitted after the initial login request.

**SEC-REQ-002**: The bcrypt cost factor MUST be configurable via the `BCRYPT_ROUNDS` environment variable (default: `12`, minimum: `10`, maximum: `15`). Values outside this range MUST be rejected at startup.

> **Rationale**: Cost factor 12 requires approximately 250ms per hash verification on modern hardware — sufficient to make brute-force infeasible without meaningfully impacting the single-user login experience.

**SEC-REQ-003**: Password hashing and verification MUST be performed using the `passlib` library with the `bcrypt` scheme. Direct use of the `bcrypt` library without `passlib`'s wrapper is not permitted (passlib handles constant-time comparison and future algorithm migration).

**SEC-REQ-004**: The `ADMIN_PASSWORD` environment variable used for initial user seeding MUST be consumed (read once, hashed, stored) during the database seed step. After seeding, the application MUST log a `WARNING` if `ADMIN_PASSWORD` remains set:

```
WARNING: ADMIN_PASSWORD environment variable is still set. 
Remove it from your .env file after initial setup.
```

The application does NOT automatically unset env vars — it is the operator's responsibility to remove the variable after seeding.

### 2.2 Password Requirements

**SEC-REQ-005**: The initial admin password (supplied via `ADMIN_PASSWORD`) MUST meet the following minimum requirements, validated at seed time:

| Requirement | Rule |
|-------------|------|
| Minimum length | 12 characters |
| Maximum length | 200 characters (bcrypt input truncation above 72 bytes is handled by passlib) |

> No character class requirements (uppercase, numbers, symbols) are enforced — length is the primary driver of password entropy. The operator is responsible for choosing a strong password.

**SEC-REQ-006**: There is no password change or reset mechanism in this version. Password changes require manually updating the `password_hash` in the database or re-running the seed process with a new `ADMIN_PASSWORD`. This is documented as a known operational limitation for a self-hosted single-user service.

### 2.3 Username Security

**SEC-REQ-007**: Usernames are stored and compared case-sensitively. The seed process stores the username exactly as supplied in `ADMIN_USERNAME`.

**SEC-REQ-008**: The login endpoint MUST use **constant-time comparison** for password verification via `passlib.verify`. On failed login (username not found), a dummy `passlib.verify` call MUST still be executed against a hardcoded hash to prevent timing-based username enumeration:

```python
# Pseudocode — prevents timing oracle
user = db.get_user_by_username(username)
if user is None:
    passlib.verify("dummy", DUMMY_HASH)  # same time as real verify
    raise InvalidCredentialsError()
if not passlib.verify(password, user.password_hash):
    raise InvalidCredentialsError()
```

---

## 3. JWT Token Security

### 3.1 Signing Configuration

**SEC-REQ-009**: JWT tokens MUST be signed with the **HS256** algorithm (HMAC-SHA256) using the `JWT_SECRET_KEY` environment variable as the signing secret.

**SEC-REQ-010**: `JWT_SECRET_KEY` MUST:
- Be at least **32 characters** (256 bits) in length
- Be randomly generated (not a dictionary word or phrase)
- Be validated at application startup — startup MUST fail with a `CRITICAL` log if the key is absent or shorter than 32 characters

**Recommended generation command** (documented in `.env.example`):
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**SEC-REQ-011**: If `JWT_SECRET_KEY` changes (e.g. rotated by the operator), all previously issued tokens become immediately invalid because they cannot be verified against the new key. This is the expected behaviour — users must re-login after a key rotation.

### 3.2 Token Claims

**Access token payload** (non-negotiable claims):

| Claim | Type | Value | Purpose |
|-------|------|-------|---------|
| `sub` | string | username | Subject (identifies the user) |
| `type` | string | `"access"` | Token type discriminator |
| `token_version` | integer | `users.token_version` | Invalidation version (see §4.2) |
| `iat` | integer | Unix timestamp | Issued-at time |
| `exp` | integer | Unix timestamp | Expiry time |

**Refresh token payload** (non-negotiable claims):

| Claim | Type | Value | Purpose |
|-------|------|-------|---------|
| `sub` | string | username | Subject |
| `type` | string | `"refresh"` | Token type discriminator |
| `token_version` | integer | `users.token_version` | Invalidation version |
| `iat` | integer | Unix timestamp | Issued-at time |
| `exp` | integer | Unix timestamp | Expiry time |

**SEC-REQ-012**: The `type` claim MUST be validated on every token use. An access token presented to the refresh endpoint, or a refresh token presented as a Bearer token, MUST be rejected with `401 UNAUTHORIZED`. This prevents token type confusion attacks.

### 3.3 Token Lifetimes

| Token | Default TTL | Environment Variable | Minimum | Maximum |
|-------|------------|---------------------|---------|---------|
| Access token | 60 minutes | `ACCESS_TOKEN_EXPIRE_MINUTES` | 5 min | 1440 min (24h) |
| Refresh token | 7 days | `REFRESH_TOKEN_EXPIRE_DAYS` | 1 day | 30 days |

**SEC-REQ-013**: Access token TTL MUST default to 60 minutes. A short TTL limits the window of exposure if an access token is somehow compromised. The refresh token automatically renews the session without requiring re-login.

**SEC-REQ-014**: Configured TTL values outside the permitted range (min/max above) MUST be rejected at startup with a `CRITICAL` log message and the application MUST NOT start with invalid security configuration.

### 3.4 Token Validation (Per Request)

**SEC-REQ-015**: Every protected API endpoint MUST validate the Bearer token by performing ALL of the following checks in order:

```
1. Authorization header present and format is "Bearer <token>"
   → Fail: 401 UNAUTHORIZED (no token)

2. Token is valid JWT — signature verifiable against JWT_SECRET_KEY
   → Fail: 401 UNAUTHORIZED (tampered/invalid token)

3. Token has not expired (exp claim > current UTC time)
   → Fail: 401 UNAUTHORIZED (expired token)

4. Token type == "access"
   → Fail: 401 UNAUTHORIZED (wrong token type)

5. User identified by `sub` exists in database and is_active == true
   → Fail: 401 UNAUTHORIZED (user not found or deactivated)

6. Token's token_version == users.token_version in database
   → Fail: 401 UNAUTHORIZED (token invalidated — user logged out or key rotated)
```

**SEC-REQ-016**: All validation failures MUST return the same `401 UNAUTHORIZED` response with error code `UNAUTHORIZED`. The specific reason for rejection MUST NOT be disclosed in the response body (prevents token oracle attacks). The reason MUST be logged server-side at `INFO` level.

**SEC-REQ-017**: The `token_version` database check (step 6) requires a database query on every authenticated request. This is an acceptable trade-off for a single-user service. The query MUST use the `sub` claim from the token — never trust the claim alone without verifying against the database record.

---

## 4. Token Lifecycle Management

### 4.1 Token Issuance

**SEC-REQ-018**: Access and refresh tokens are issued together on `POST /api/auth/login`. Both tokens are generated from the same `token_version` value read from the database at login time.

**SEC-REQ-019**: On `POST /api/auth/refresh`, only a new **access token** is issued. The refresh token is not rotated (it retains the same expiry and `token_version`). If a new refresh token is needed, the user must log in again.

> **Rationale**: Refresh token rotation adds complexity (handling race conditions between concurrent requests) with minimal security benefit for a single-user, low-concurrency service.

### 4.2 Token Invalidation via `token_version`

The `token_version` mechanism provides immediate invalidation of all outstanding tokens without maintaining a server-side blocklist.

**SEC-REQ-020**: `users.token_version` MUST be incremented in the following events:

| Event | Action |
|-------|--------|
| `POST /api/auth/logout` | Increment `token_version` |
| (Future) Password change | Increment `token_version` |
| (Future) Admin-forced logout | Increment `token_version` |

After incrementing, all previously issued tokens (both access and refresh) with the old `token_version` value are immediately invalid — they will fail step 6 of token validation.

**SEC-REQ-021**: `token_version` increments MUST be atomic database operations (`UPDATE users SET token_version = token_version + 1 WHERE id = :id`). Race conditions on this field are not a concern for a single-user service but the atomic update is good practice.

### 4.3 Refresh Token Cookie

**SEC-REQ-022**: The refresh token MUST be delivered to the browser as an httpOnly cookie with the following attributes:

| Attribute | Value | Purpose |
|-----------|-------|---------|
| `HttpOnly` | Set | Prevents JavaScript access — protects against XSS |
| `SameSite` | `Strict` | Prevents cookie from being sent in cross-site requests — CSRF protection |
| `Path` | `/api/auth` | Scoped to auth endpoints only — not sent with delivery API requests |
| `Max-Age` | `604800` (7 days, matching refresh token TTL) | Browser expiry |
| `Secure` | Set when `HTTPS=true` env var | Only transmitted over HTTPS |

**SEC-REQ-023**: The `Secure` cookie attribute MUST be conditionally applied based on the `COOKIE_SECURE` environment variable (default: `false` for local HTTP; `true` for HTTPS deployments). This allows the service to function over plain HTTP on a local network while supporting secure deployment.

**SEC-REQ-024**: The refresh token cookie path MUST be scoped to `/api/auth` (not `/` or `/api`). This ensures the refresh token cookie is only sent to auth endpoints and is not included in delivery API requests, reducing its exposure surface.

---

## 5. FastAPI Authentication Implementation

### 5.1 Auth Dependency

**SEC-REQ-025**: Authentication MUST be implemented as a reusable **FastAPI dependency** (`get_current_user`) that can be injected into any route handler requiring authentication. This prevents accidental omission of auth checks on new endpoints.

```python
# Conceptual specification
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Validates Bearer token, returns authenticated User.
    Raises HTTPException(401) on any validation failure.
    """
    ...
```

**SEC-REQ-026**: Routes are protected by **inclusion** of the dependency, not by exclusion. Every new route MUST explicitly declare `Depends(get_current_user)` to be protected. There is no global "all routes are protected" default — explicit declaration is required to keep the public routes (`/health`, `/auth/login`, `/auth/refresh`) clearly identifiable in code.

**SEC-REQ-027**: The auth dependency MUST return the `User` ORM object to the route handler. Route handlers MUST use this object (specifically `user.id` and `user.username`) for any user-contextual operations. They MUST NOT accept user identity from request body parameters.

### 5.2 Public Routes

The following routes are explicitly public (no auth required):

| Route | Reason |
|-------|--------|
| `POST /api/auth/login` | Credentials not yet validated |
| `POST /api/auth/refresh` | Uses httpOnly cookie, not Bearer token |
| `GET /api/health` | Required for Docker health checks without credentials |

All other routes MUST use `get_current_user`.

---

## 6. CORS Policy

**SEC-REQ-028**: CORS is effectively **not required** in production because the Nginx reverse proxy serves both the frontend SPA and the API on the same origin. The browser sees a single origin; there are no cross-origin API calls.

**SEC-REQ-029**: FastAPI's `CORSMiddleware` MUST be configured only when `ENVIRONMENT=development`. In development, it MUST allow only specific local origins (e.g. `http://localhost:5173` for the Vite dev server). Wildcard origins (`*`) are prohibited in all configurations.

```python
# Development-only CORS configuration
if settings.environment == "development":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,  # ["http://localhost:5173"]
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )
```

**SEC-REQ-030**: In production (`ENVIRONMENT=production`), the `CORSMiddleware` MUST NOT be added to the FastAPI application. Any cross-origin request will receive no CORS headers and the browser will block it — the intended behaviour, since all legitimate traffic routes through Nginx.

---

## 7. HTTP Security Headers

**SEC-REQ-031**: The FastAPI application MUST add the following security headers to **all responses** via a middleware:

| Header | Value | Purpose |
|--------|-------|---------|
| `X-Content-Type-Options` | `nosniff` | Prevents MIME-type sniffing |
| `X-Frame-Options` | `DENY` | Prevents clickjacking in iframes |
| `X-XSS-Protection` | `0` | Disables legacy XSS filter (modern browsers ignore it; CSP replaces it) |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limits referrer leakage |

**SEC-REQ-032**: The Nginx configuration serving the frontend MUST add the following headers to all static asset and proxied responses:

```nginx
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self';" always;
```

**SEC-REQ-033**: The Content Security Policy (CSP) defined above:
- `default-src 'self'` — blocks all external resource loads by default
- `script-src 'self'` — no inline scripts, no CDN scripts
- `style-src 'self' 'unsafe-inline'` — `unsafe-inline` required for Tailwind CSS utility classes injected by the React build
- `img-src 'self' data:` — allows inline base64 images (used by some UI components)
- `connect-src 'self'` — API calls allowed only to same origin

> If `unsafe-inline` for styles is unacceptable, Tailwind CSS can be configured to output hashed styles. This is an implementation decision.

**SEC-REQ-034**: The FastAPI application MUST NOT return a `Server` header that identifies the framework or version. Uvicorn's default `Server: uvicorn` header MUST be suppressed.

---

## 8. Brute Force Protection

**SEC-REQ-035**: The `POST /api/auth/login` endpoint MUST implement **rate limiting** to prevent credential brute-forcing:

| Limit | Scope | Action on Exceeded |
|-------|-------|-------------------|
| 10 failed attempts per 15 minutes | Per source IP address | Return `429 Too Many Requests` |

**SEC-REQ-036**: Rate limiting state MUST be stored **in application memory** (a simple sliding-window counter). Redis or an external store is not required for a single-user self-hosted service.

**SEC-REQ-037**: The rate limit counter MUST count only **failed** login attempts. Successful logins reset the counter for that IP. This prevents a malicious actor from locking out the legitimate user by exhausting their own counter through repeated logins.

**SEC-REQ-038**: When the rate limit is exceeded, the response MUST be `429 Too Many Requests` with error code `RATE_LIMITED` and the message: *"Too many failed login attempts. Please wait before trying again."*

**SEC-REQ-039**: A `Retry-After` header MUST be included in rate-limited responses indicating the number of seconds until the window resets.

**SEC-REQ-040**: The brute force counter MUST be keyed by **source IP address**. The application MUST respect the `X-Forwarded-For` header only if `TRUST_PROXY_HEADERS=true` is set in configuration (defaults to `false`). When running behind the Nginx reverse proxy on the same Docker network, set this to `true` and Nginx MUST set `X-Real-IP` or `X-Forwarded-For` appropriately.

---

## 9. HTTPS Configuration for Self-Hosted

HTTPS is strongly recommended but not enforced at the application level, as self-hosted scenarios vary (local network only, VPN, reverse proxy in front of Docker, etc.).

**SEC-REQ-041**: The Nginx service MUST support an **optional HTTPS configuration** activated by providing SSL certificate files via volume mounts. The following env vars control HTTPS mode:

| Variable | Default | Description |
|----------|---------|-------------|
| `HTTPS_ENABLED` | `false` | Set to `true` to enable HTTPS in Nginx |
| `SSL_CERT_PATH` | — | Path inside the Nginx container to the certificate file |
| `SSL_KEY_PATH` | — | Path inside the Nginx container to the private key file |

**SEC-REQ-042**: When `HTTPS_ENABLED=true`, Nginx MUST:
- Listen on port `443` with SSL
- Redirect all HTTP (`80`) traffic to HTTPS (`443`) with `301 Moved Permanently`
- Use `ssl_protocols TLSv1.2 TLSv1.3` (TLS 1.0 and 1.1 disabled)
- Use a strong cipher suite (Mozilla's Intermediate profile or equivalent)

**SEC-REQ-043**: When `HTTPS_ENABLED=false` (default), Nginx listens on port `80` only. The application functions over plain HTTP. This is acceptable for use on a trusted local network or behind a VPN.

**SEC-REQ-044**: The `Secure` attribute on the refresh token cookie (SEC-REQ-023) MUST be enabled when `HTTPS_ENABLED=true`. The application configuration and cookie settings MUST be consistent — enabling HTTPS without setting `COOKIE_SECURE=true` MUST produce a startup warning.

**Operator guidance** (to be documented in README):
- For a Let's Encrypt certificate: use Certbot with a volume mount to `/etc/letsencrypt`
- For a self-signed certificate: `openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365`
- For Tailscale / Cloudflare Tunnel users: disable HTTPS at the Docker layer and let the tunnel handle TLS termination

---

## 10. Secrets Management

**SEC-REQ-045**: All secrets MUST be provided via environment variables. The following values are classified as secrets and MUST NEVER appear in source code, Docker images, or log output:

| Secret | Variable | Classification |
|--------|----------|---------------|
| Parcel API key | `PARCEL_API_KEY` | External API credential |
| JWT signing key | `JWT_SECRET_KEY` | Cryptographic secret |
| Initial admin password | `ADMIN_PASSWORD` | Credential (temporary) |
| Database password | `POSTGRES_PASSWORD` | Database credential |

**SEC-REQ-046**: A `.env.example` file MUST be committed to source control containing all environment variable names with placeholder values and comments. The actual `.env` file MUST be listed in `.gitignore` and MUST NEVER be committed.

```bash
# .env.example (committed to source control)
PARCEL_API_KEY=your_parcel_api_key_here
JWT_SECRET_KEY=generate_with__python_-c_"import secrets; print(secrets.token_hex(32))"
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_me_immediately
POSTGRES_PASSWORD=change_this_database_password
```

**SEC-REQ-047**: The application MUST perform a **secrets presence check** at startup and refuse to start if any required secret is absent. The startup check MUST log which variable is missing (by name, not value) and exit with a non-zero code.

**SEC-REQ-048**: The application MUST perform a **weak secrets check** at startup for `JWT_SECRET_KEY` (minimum 32 chars) and `ADMIN_PASSWORD` (minimum 12 chars, if still set). If either fails the check, the application MUST refuse to start.

---

## 11. Docker Security Hardening

**SEC-REQ-049**: The `api` container MUST run as a **non-root user**. The Dockerfile MUST create and switch to a dedicated non-privileged user:

```dockerfile
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser
```

**SEC-REQ-050**: The `frontend` (Nginx) container's Nginx process MUST run as a non-root user. The base `nginx:alpine` image supports this via `nginx.conf` configuration (`worker_processes` run as `nginx` user by default in the official image).

**SEC-REQ-051**: The `api` container's filesystem MUST be treated as read-only where possible. No files are written to the container filesystem during runtime — all persistence goes through the database.

**SEC-REQ-052**: Secrets MUST be passed to containers via environment variables in `docker-compose.yml` referencing the `.env` file. They MUST NOT be hardcoded in `docker-compose.yml`, `Dockerfile`, or any source-controlled file.

```yaml
# docker-compose.yml pattern (correct)
services:
  api:
    env_file: .env
    environment:
      - DATABASE_URL=postgresql+psycopg://postgres:${POSTGRES_PASSWORD}@postgres:5432/delivery_tracker
```

**SEC-REQ-053**: The `postgres` service MUST NOT expose its port (`5432`) on the host machine in the production Docker Compose configuration. Database access from the host is available only via `docker exec` for administration purposes.

**SEC-REQ-054**: Docker image versions MUST be pinned to specific versions (e.g. `python:3.12.4-slim`, `postgres:16.3-alpine`) in production Dockerfiles. The `latest` tag MUST NOT be used, as it may introduce breaking changes or vulnerabilities on rebuild.

---

## 12. Input Validation & Injection Prevention

**SEC-REQ-055**: All API request bodies and query parameters MUST be validated by Pydantic v2 models before reaching route handler logic. FastAPI's automatic Pydantic validation provides this by default. No manual input parsing is permitted.

**SEC-REQ-056**: All database interactions MUST use SQLAlchemy ORM query methods or parameterised SQL expressions (`text()` with bound parameters). Raw string-interpolated SQL queries are prohibited. This prevents SQL injection.

**SEC-REQ-057**: Field length limits MUST be enforced at both the Pydantic schema level (request validation) and the database level (column length constraints). The limits defined in the data model (§3 of 02-data-model.md) are authoritative.

**SEC-REQ-058**: The search parameter on `GET /api/deliveries` MUST be passed as a parameterised SQL LIKE expression, never string-interpolated into a query.

---

## 13. Logging & Audit Security

**SEC-REQ-059**: The following events MUST be logged at `INFO` level as a security audit trail:

| Event | Log Fields |
|-------|-----------|
| Successful login | `username`, `source_ip`, `timestamp` |
| Failed login attempt | `username_attempted`, `source_ip`, `timestamp`, `reason` |
| Rate limit triggered | `source_ip`, `timestamp`, `attempt_count` |
| Logout | `username`, `timestamp` |
| Token refresh | `username`, `timestamp` |
| Token validation failure | `source_ip`, `timestamp`, `failure_reason` (generic) |

**SEC-REQ-060**: Security-relevant log entries MUST include the source IP address. For accurate IP capture behind the Nginx proxy, the `X-Real-IP` header MUST be forwarded by Nginx and read by the FastAPI application when `TRUST_PROXY_HEADERS=true`.

**SEC-REQ-061**: No secret values (passwords, tokens, API keys) MUST appear in log output at any log level, including DEBUG. Structured log fields must be audited to ensure no secret leakage.

---

## 14. Security Checklist (Pre-Deployment)

The following checklist MUST be verified before exposing the service on any network:

| # | Check | How to Verify |
|---|-------|--------------|
| 1 | `ADMIN_PASSWORD` removed from `.env` after first run | `grep ADMIN_PASSWORD .env` returns nothing |
| 2 | `JWT_SECRET_KEY` is ≥ 32 random characters | `echo -n "$JWT_SECRET_KEY" \| wc -c` |
| 3 | `POSTGRES_PASSWORD` changed from default | Not `change_this_database_password` |
| 4 | Database port NOT exposed on host | `docker compose ps` shows no `0.0.0.0:5432` binding |
| 5 | `.env` not tracked by git | `git status .env` shows untracked or ignored |
| 6 | Containers running as non-root | `docker exec delivery-api whoami` → not `root` |
| 7 | HTTPS configured (if exposed beyond local network) | `curl https://...` succeeds |
| 8 | `COOKIE_SECURE=true` if HTTPS enabled | Config review |

---

## 15. Out of Scope

The following security features are explicitly **out of scope** for this version:

| Feature | Reason |
|---------|--------|
| Multi-factor authentication (MFA) | Single-user, local-network deployment |
| Password reset / forgot password flow | No email service; documented operational workaround exists |
| Account lockout (permanent) | Rate limiting (temporary) is sufficient; permanent lockout risks self-lockout |
| OAuth2 / SSO integration | Out of scope for single-user self-hosted |
| Audit log persistence to database | Log files suffice; no compliance requirement |
| Token revocation list (blocklist) | `token_version` mechanism covers invalidation requirements |
| HSTS (HTTP Strict Transport Security) | Recommended if HTTPS enabled; not enforced by application |

---

## 16. Requirements Summary

| ID | Requirement |
|----|-------------|
| SEC-REQ-001 | bcrypt with cost factor ≥ 12; no plaintext passwords stored |
| SEC-REQ-002 | BCRYPT_ROUNDS configurable (10–15); validated at startup |
| SEC-REQ-003 | Use passlib with bcrypt scheme |
| SEC-REQ-004 | ADMIN_PASSWORD env var: warn if still set after seeding |
| SEC-REQ-005 | Initial password minimum 12 characters |
| SEC-REQ-006 | No password reset mechanism; documented as known limitation |
| SEC-REQ-007 | Usernames are case-sensitive |
| SEC-REQ-008 | Constant-time password check; dummy verify on unknown username |
| SEC-REQ-009 | JWT signed with HS256 using JWT_SECRET_KEY |
| SEC-REQ-010 | JWT_SECRET_KEY ≥ 32 chars, random; startup fails if absent or short |
| SEC-REQ-011 | Rotating JWT_SECRET_KEY invalidates all tokens |
| SEC-REQ-012 | `type` claim validated; token type confusion rejected |
| SEC-REQ-013 | Access token TTL default 60 min; refresh token default 7 days |
| SEC-REQ-014 | TTL values outside permitted range rejected at startup |
| SEC-REQ-015 | 6-step token validation on every protected request |
| SEC-REQ-016 | All token validation failures return same 401; reason not disclosed |
| SEC-REQ-017 | token_version DB check required on every request |
| SEC-REQ-018 | Access + refresh tokens issued together at login from same token_version |
| SEC-REQ-019 | Refresh only issues new access token; refresh token not rotated |
| SEC-REQ-020 | token_version incremented on logout (and future password change) |
| SEC-REQ-021 | token_version increments are atomic DB operations |
| SEC-REQ-022 | Refresh token cookie: HttpOnly, SameSite=Strict, Path=/api/auth |
| SEC-REQ-023 | Secure cookie attribute controlled by COOKIE_SECURE env var |
| SEC-REQ-024 | Refresh token cookie scoped to /api/auth only |
| SEC-REQ-025 | Auth implemented as reusable FastAPI dependency |
| SEC-REQ-026 | Routes protected by explicit dependency inclusion |
| SEC-REQ-027 | User identity from auth dependency only; never from request body |
| SEC-REQ-028 | CORS not required in production (same origin via Nginx) |
| SEC-REQ-029 | CORSMiddleware in development only; specific origins only |
| SEC-REQ-030 | CORSMiddleware not added in production |
| SEC-REQ-031 | Security headers on all FastAPI responses |
| SEC-REQ-032 | Nginx adds security headers including CSP |
| SEC-REQ-033 | CSP defined with connect-src 'self' and no external resources |
| SEC-REQ-034 | Server header suppressed (no framework/version disclosure) |
| SEC-REQ-035 | Login rate limit: 10 failed attempts per 15 min per IP |
| SEC-REQ-036 | Rate limit state in application memory |
| SEC-REQ-037 | Rate limit counts failed attempts only; success resets counter |
| SEC-REQ-038 | Rate limit exceeded: 429 with RATE_LIMITED code |
| SEC-REQ-039 | Retry-After header on rate-limited responses |
| SEC-REQ-040 | Rate limit keyed by source IP; X-Forwarded-For respected when TRUST_PROXY_HEADERS=true |
| SEC-REQ-041 | Nginx optional HTTPS via HTTPS_ENABLED env var + cert volume mounts |
| SEC-REQ-042 | HTTPS: TLS 1.2+ only; HTTP redirects to HTTPS |
| SEC-REQ-043 | HTTP-only mode acceptable for local network use |
| SEC-REQ-044 | COOKIE_SECURE=true required when HTTPS_ENABLED=true; startup warning if inconsistent |
| SEC-REQ-045 | All secrets via env vars; never in code or images |
| SEC-REQ-046 | .env.example committed; .env in .gitignore |
| SEC-REQ-047 | Startup fails if required secret missing |
| SEC-REQ-048 | Startup fails if JWT_SECRET_KEY < 32 chars or ADMIN_PASSWORD < 12 chars |
| SEC-REQ-049 | api container runs as non-root user |
| SEC-REQ-050 | Nginx worker runs as non-root |
| SEC-REQ-051 | api container filesystem treated as read-only |
| SEC-REQ-052 | Secrets passed via env_file; not hardcoded in compose or Dockerfiles |
| SEC-REQ-053 | postgres port not exposed on host in production |
| SEC-REQ-054 | Docker image versions pinned; no `latest` tag |
| SEC-REQ-055 | All inputs validated by Pydantic before handler logic |
| SEC-REQ-056 | All DB queries via SQLAlchemy ORM or parameterised SQL |
| SEC-REQ-057 | Field length limits enforced at Pydantic and DB levels |
| SEC-REQ-058 | Search parameter as parameterised LIKE; no string interpolation |
| SEC-REQ-059 | Security audit events logged at INFO level |
| SEC-REQ-060 | Source IP included in security log entries |
| SEC-REQ-061 | No secrets in log output at any level |

---

*Source: User scoping input, architecture (01-architecture.md), data model (02-data-model.md), REST API (05-rest-api.md), dashboard (06-web-dashboard.md)*  
*Traceability: SEC-REQ-001 through SEC-REQ-061*
