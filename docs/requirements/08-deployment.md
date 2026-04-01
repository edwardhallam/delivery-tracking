# Deployment & Configuration Requirements

**Document ID**: DEPLOY-001  
**Plan Phase**: Phase 8  
**Status**: Draft — Awaiting Review  
**Project**: Delivery Tracking Web Service  
**Dependencies**: [01-architecture.md](./01-architecture.md), [07-auth-security.md](./07-auth-security.md)

---

## 1. Overview

The Delivery Tracking Service is deployed as a **Docker Compose stack** of three services. A single `docker compose up -d` command from the project root starts the complete application. No external dependencies (cloud services, external databases, message queues) are required.

**Design goals:**
- Zero-dependency self-hosted deployment
- Single command to start, stop, and update
- No data loss on container restart or image rebuild
- Deterministic startup ordering with health-gated dependencies
- Operator-friendly configuration via a single `.env` file

---

## 2. Service Topology

### 2.1 Services

| Service Name | Image | Role | Host Port |
|-------------|-------|------|-----------|
| `postgres` | `postgres:16.3-alpine` | Persistent data store | None (internal only) |
| `api` | Built from `./api/Dockerfile` | FastAPI backend + scheduler | None (internal only) |
| `frontend` | Built from `./frontend/Dockerfile` | Nginx: React SPA + API reverse proxy | `80` (and optionally `443`) |

### 2.2 Network Topology

```
Host Machine
│
│   Port 80 (HTTP) / 443 (HTTPS)
│
├── [frontend] nginx:alpine
│       │  Static SPA files served directly
│       │
│       │  /api/* proxied to →
│       │
├── [api] python:3.12-slim              (internal network only)
│       │  FastAPI + APScheduler
│       │  Port 8000
│       │
│       │  SQL over TCP →
│       │
└── [postgres] postgres:16.3-alpine     (internal network only)
        │  Port 5432
        │
        └── [Volume: postgres_data]
               /var/lib/postgresql/data
```

**DEPLOY-REQ-001**: All three services MUST be connected to a shared Docker bridge network named `delivery_network`. This provides DNS resolution between services (e.g. the API connects to `postgres:5432`, Nginx proxies to `api:8000`).

**DEPLOY-REQ-002**: The `postgres` and `api` services MUST NOT expose any ports on the host machine. All traffic enters through the `frontend` service. Direct database access from the host is available only via `docker exec` for administrative purposes.

**DEPLOY-REQ-003**: The `frontend` service MUST expose port `80` on the host. The host-side port MUST be configurable via the `FRONTEND_HTTP_PORT` environment variable (default: `80`). This allows the service to run on a non-standard port if port 80 is occupied.

---

## 3. Docker Compose Specification

### 3.1 Canonical `docker-compose.yml` Structure

```yaml
# docker-compose.yml (canonical structure — not implementation-prescriptive)

services:

  postgres:
    image: postgres:16.3-alpine
    restart: unless-stopped
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    networks:
      - delivery_network
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "${POSTGRES_USER}", "-d", "${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  api:
    build:
      context: ./api
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - delivery_network
    # No ports: section — internal only

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    restart: unless-stopped
    ports:
      - "${FRONTEND_HTTP_PORT:-80}:80"
    depends_on:
      - api
    networks:
      - delivery_network

networks:
  delivery_network:
    driver: bridge

volumes:
  postgres_data:
    driver: local
```

**DEPLOY-REQ-004**: The `api` service MUST use `depends_on` with `condition: service_healthy` on the `postgres` service. The API container MUST NOT attempt to run migrations or start Uvicorn until PostgreSQL reports healthy via `pg_isready`.

**DEPLOY-REQ-005**: The `restart: unless-stopped` policy MUST be applied to all three services. This ensures the stack automatically recovers from container crashes and host reboots (when Docker is configured to start on boot).

---

## 4. Container Image Specifications

### 4.1 `api` — Dockerfile

**DEPLOY-REQ-006**: The `api` Dockerfile MUST use a **two-stage build** separating dependency installation from the final runtime image:

```
Stage 1 (builder): Install Python dependencies into a virtual environment
Stage 2 (runtime): Copy only the venv and application code into a clean python:3.12-slim image
```

This produces a smaller final image without build tools.

**DEPLOY-REQ-007**: The final `api` runtime image MUST be based on `python:3.12-slim` (not `-bullseye` or full Python image). The slim variant excludes unnecessary system packages.

**DEPLOY-REQ-008**: The `api` container MUST run as a non-root user (SEC-REQ-049). The Dockerfile MUST create a dedicated system user:
```dockerfile
RUN addgroup --system appgroup && \
    adduser --system --ingroup appgroup --no-create-home appuser
USER appuser
```

**DEPLOY-REQ-009**: The `api` Dockerfile MUST NOT copy the `.env` file or any secret into the image. Secrets are injected at runtime via Docker Compose's `env_file` directive.

**DEPLOY-REQ-010**: The `api` container entrypoint MUST be a shell script (`entrypoint.sh`) that executes the startup sequence in order (see §6). The script MUST be copied into the image and marked executable in the Dockerfile.

### 4.2 `frontend` — Dockerfile

**DEPLOY-REQ-011**: The `frontend` Dockerfile MUST use a **multi-stage build**:

```
Stage 1 (builder): node:20-alpine
  - Copy package.json + package-lock.json
  - Run npm ci (clean install from lock file)
  - Copy application source
  - Run npm run build → outputs to /app/dist

Stage 2 (runtime): nginx:alpine
  - Copy /app/dist from builder → /usr/share/nginx/html
  - Copy nginx.conf → /etc/nginx/conf.d/default.conf
```

**DEPLOY-REQ-012**: `npm ci` MUST be used (not `npm install`) in the build stage. `npm ci` installs exact versions from `package-lock.json` — reproducible builds.

**DEPLOY-REQ-013**: The `frontend` image MUST NOT contain Node.js, npm, or build tools in the final runtime stage. Only the static compiled assets and Nginx are present.

### 4.3 `postgres`

**DEPLOY-REQ-014**: The `postgres` service MUST use the official `postgres:16.3-alpine` image without customisation. No custom Dockerfile is needed. All PostgreSQL configuration is provided via environment variables.

---

## 5. Volume Strategy

### 5.1 `postgres_data` Named Volume

**DEPLOY-REQ-015**: A Docker named volume `postgres_data` MUST be defined and mounted to `/var/lib/postgresql/data` in the `postgres` container. This is the sole persistence mechanism for all application data.

**DEPLOY-REQ-016**: The `postgres_data` volume MUST use the default `local` driver. No distributed or cloud volume drivers are required.

**DEPLOY-REQ-017**: The `postgres_data` volume MUST persist across:
- `docker compose restart`
- `docker compose stop` / `docker compose start`
- `docker compose down` (without `--volumes`)
- Container image rebuilds and upgrades

**DEPLOY-REQ-018**: The volume is destroyed ONLY by `docker compose down --volumes` or `docker volume rm`. This MUST be documented prominently in the operator guide as a **data-destructive operation**.

### 5.2 SSL Certificate Volumes (Optional)

**DEPLOY-REQ-019**: When `HTTPS_ENABLED=true`, the `frontend` service requires SSL certificate files. These MUST be provided via **bind mounts** (host directory → container path), not baked into the image:

```yaml
# docker-compose.yml addition when HTTPS_ENABLED=true
frontend:
  volumes:
    - ${SSL_CERT_PATH}:/etc/nginx/ssl/cert.pem:ro
    - ${SSL_KEY_PATH}:/etc/nginx/ssl/key.pem:ro
```

The `:ro` (read-only) flag MUST be applied — the container only reads certificates, never writes them.

### 5.3 No Application-Layer Volumes

**DEPLOY-REQ-020**: The `api` and `frontend` containers MUST NOT use volumes for application data. All state is in PostgreSQL. This keeps the containers fully stateless and replaceable.

---

## 6. Startup Sequence

### 6.1 Container Start Order

```
1. postgres container starts
      └── healthcheck: pg_isready runs every 10s
      └── PostgreSQL initialises and becomes ready (~10-30s)

2. api container starts (gated on postgres health)
      └── entrypoint.sh executes:
          a. Run database migrations
          b. Run database seed (first-run user creation)
          c. Start Uvicorn (which starts APScheduler → immediate first poll)

3. frontend container starts (after api container starts)
      └── Nginx starts, begins serving static files
      └── /api/* proxy available (502s briefly if api not yet serving — acceptable)
```

### 6.2 `api` Container Entrypoint Script

**DEPLOY-REQ-021**: The `api` container's `entrypoint.sh` MUST execute the following steps in strict order:

```bash
#!/bin/sh
set -e  # Exit immediately on any error

echo "=== Step 1: Running database migrations ==="
alembic upgrade head

echo "=== Step 2: Running database seed ==="
python -m app.seed

echo "=== Step 3: Starting application ==="
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers 1 \
    --no-access-log
```

**DEPLOY-REQ-022**: `set -e` MUST be present in the entrypoint script. If `alembic upgrade head` or the seed script fails, the container MUST exit with a non-zero code. Docker will restart it (per `unless-stopped`), and the operator will see the error in `docker compose logs api`.

**DEPLOY-REQ-023**: Uvicorn MUST be started with `--workers 1`. The application uses APScheduler for background polling — multiple workers would create duplicate schedulers and duplicate polls. Single-worker is correct for this architecture.

**DEPLOY-REQ-024**: Uvicorn MUST bind to `0.0.0.0` (not `127.0.0.1`) so it is reachable from the `frontend` container on the Docker network.

**DEPLOY-REQ-025**: `--no-access-log` is recommended to reduce log noise. Structured application logs from FastAPI provide sufficient observability.

### 6.3 Database Seed Script (`app.seed`)

**DEPLOY-REQ-026**: The seed script (`python -m app.seed`) MUST:

```
1. Check: SELECT COUNT(*) FROM users
2. If count == 0:
   a. Validate ADMIN_USERNAME is set and non-empty
   b. Validate ADMIN_PASSWORD meets minimum requirements (≥ 12 chars)
   c. Hash ADMIN_PASSWORD with bcrypt
   d. INSERT INTO users (username, password_hash, token_version, is_active)
   e. Log INFO: "Initial admin user '{ADMIN_USERNAME}' created successfully."
3. If count > 0:
   a. Log INFO: "Database already seeded. Skipping user creation."
4. If ADMIN_PASSWORD env var is still set:
   a. Log WARNING: "ADMIN_PASSWORD is still set in environment. Remove it from .env."
5. Exit cleanly
```

**DEPLOY-REQ-027**: The seed script MUST be **idempotent** — running it multiple times against an already-seeded database MUST produce no changes and no errors.

**DEPLOY-REQ-028**: If `ADMIN_USERNAME` or `ADMIN_PASSWORD` is absent when the database has no users (required for first-run seeding), the seed script MUST exit with a non-zero code and the error:
```
CRITICAL: Database has no users and ADMIN_USERNAME/ADMIN_PASSWORD are not set.
          Cannot start without an admin user. Set these variables and restart.
```

---

## 7. Nginx Configuration

### 7.1 Core Configuration

**DEPLOY-REQ-029**: The Nginx configuration file (`nginx.conf`) MUST be included in the `frontend` image and provide the following routing:

```nginx
server {
    listen 80;
    server_name _;

    # Gzip compression for text assets
    gzip on;
    gzip_types text/plain text/css application/json application/javascript
               text/xml application/xml text/javascript;

    # API reverse proxy
    location /api/ {
        proxy_pass         http://api:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 60s;
        proxy_connect_timeout 10s;
    }

    # React SPA — all other routes serve index.html
    location / {
        root       /usr/share/nginx/html;
        index      index.html;
        try_files  $uri $uri/ /index.html;
    }

    # Cache static assets aggressively (Vite generates content-hashed filenames)
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
        root       /usr/share/nginx/html;
        expires    1y;
        add_header Cache-Control "public, immutable";
        try_files  $uri =404;
    }
}
```

**DEPLOY-REQ-030**: The `try_files $uri $uri/ /index.html` directive in the SPA location block MUST be present. This serves `index.html` for all client-side routes (e.g. `/deliveries/some-id`) that don't map to static files, enabling React Router's client-side routing.

**DEPLOY-REQ-031**: Static assets (JS, CSS, fonts, images) generated by Vite MUST be served with `Cache-Control: public, immutable` and a 1-year `expires`. Vite generates content-hashed filenames (e.g. `main.a1b2c3d4.js`) — the hash changes when content changes, making aggressive caching safe.

**DEPLOY-REQ-032**: `X-Real-IP` and `X-Forwarded-For` headers MUST be set by Nginx when proxying to the API. This enables accurate source IP logging and brute-force rate limiting in the API (SEC-REQ-060, SEC-REQ-040).

### 7.2 HTTPS Configuration (When Enabled)

**DEPLOY-REQ-033**: When `HTTPS_ENABLED=true`, the Nginx configuration MUST be extended to:

```nginx
# HTTP → HTTPS redirect
server {
    listen 80;
    server_name _;
    return 301 https://$host$request_uri;
}

# HTTPS server
server {
    listen 443 ssl;
    server_name _;

    ssl_certificate     /etc/nginx/ssl/cert.pem;
    ssl_certificate_key /etc/nginx/ssl/key.pem;

    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:
                        ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # ... same location blocks as HTTP config
}
```

**DEPLOY-REQ-034**: The HTTPS Nginx configuration MUST be delivered as a separate config file (`nginx-https.conf`) that replaces `nginx.conf` when `HTTPS_ENABLED=true`. The Docker Compose configuration selects which file to mount based on the env var. This avoids Nginx failing to start when certificate files are absent in HTTP-only mode.

---

## 8. Full Environment Variable Schema

This is the canonical, authoritative list of all environment variables. All variables are read from the `.env` file via Docker Compose's `env_file` directive.

### 8.1 Database (postgres service)

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `POSTGRES_USER` | ✅ | — | PostgreSQL superuser username |
| `POSTGRES_PASSWORD` | ✅ | — | PostgreSQL superuser password |
| `POSTGRES_DB` | ✅ | — | Database name to create on first run |

### 8.2 API Service

**Database Connection**

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `DATABASE_URL` | ✅ | — | Full async connection string: `postgresql+psycopg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}` |

**Parcel API**

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `PARCEL_API_KEY` | ✅ | — | Parcel App API key from web.parcelapp.net |

**Authentication & Security**

| Variable | Required | Default | Min | Max | Description |
|----------|:--------:|---------|-----|-----|-------------|
| `JWT_SECRET_KEY` | ✅ | — | 32 chars | — | JWT signing secret (generate with `secrets.token_hex(32)`) |
| `JWT_ALGORITHM` | No | `HS256` | — | — | JWT algorithm (do not change) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | No | `60` | `5` | `1440` | Access token TTL in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | No | `7` | `1` | `30` | Refresh token TTL in days |
| `BCRYPT_ROUNDS` | No | `12` | `10` | `15` | bcrypt cost factor |
| `COOKIE_SECURE` | No | `false` | — | — | Set `true` when HTTPS enabled |
| `TRUST_PROXY_HEADERS` | No | `true` | — | — | Trust X-Forwarded-For from Nginx proxy |

**First-Run Seeding (remove after initial setup)**

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `ADMIN_USERNAME` | ✅ (first run) | — | Initial admin username |
| `ADMIN_PASSWORD` | ✅ (first run) | — | Initial admin password (plaintext, hashed and discarded) |

**Polling**

| Variable | Required | Default | Min | Max | Description |
|----------|:--------:|---------|-----|-----|-------------|
| `POLL_INTERVAL_MINUTES` | No | `15` | `5` | — | Parcel API polling interval in minutes |
| `POLL_JITTER_SECONDS` | No | `30` | `0` | `120` | Random jitter added to each polling interval |
| `POLL_HTTP_TIMEOUT_SECONDS` | No | `30` | `5` | `120` | Parcel API HTTP request timeout |
| `POLL_MAX_RETRIES` | No | `3` | `0` | `5` | Max retry attempts for transient errors |

**Application**

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `ENVIRONMENT` | No | `production` | `development` or `production`. Controls CORS, Swagger UI. |
| `LOG_LEVEL` | No | `INFO` | Python logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### 8.3 Frontend / Nginx

| Variable | Required | Default | Description |
|----------|:--------:|---------|-------------|
| `FRONTEND_HTTP_PORT` | No | `80` | Host port to expose the frontend on |
| `HTTPS_ENABLED` | No | `false` | Set `true` to enable HTTPS in Nginx |
| `SSL_CERT_PATH` | HTTPS only | — | Host path to SSL certificate file |
| `SSL_KEY_PATH` | HTTPS only | — | Host path to SSL private key file |

---

## 9. Health Checks

### 9.1 `postgres` Health Check

**DEPLOY-REQ-035**: The `postgres` service health check MUST use `pg_isready`:

```yaml
healthcheck:
  test: ["CMD", "pg_isready", "-U", "${POSTGRES_USER}", "-d", "${POSTGRES_DB}"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 30s
```

- `interval: 10s` — check every 10 seconds
- `start_period: 30s` — allow 30 seconds for PostgreSQL to initialise before health failures count against retries
- `retries: 5` — 5 consecutive failures = unhealthy (50 seconds maximum from start)

### 9.2 `api` Health Check

**DEPLOY-REQ-036**: The `api` service health check MUST call the `/api/health` endpoint:

```yaml
healthcheck:
  test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8000/api/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 60s
```

- `start_period: 60s` — allow time for migrations, seed, and first poll to complete before health failures count
- Uses `wget` (available in `python:3.12-slim`); alternatively `curl` if added to the image

### 9.3 `frontend` Health Check

**DEPLOY-REQ-037**: The `frontend` service health check verifies Nginx is serving:

```yaml
healthcheck:
  test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:80/"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 10s
```

---

## 10. Logging Configuration

**DEPLOY-REQ-038**: Docker's default `json-file` logging driver MUST be configured with rotation limits to prevent unbounded log growth:

```yaml
# Applied to api and frontend services
logging:
  driver: json-file
  options:
    max-size: "50m"
    max-file: "5"
```

This retains up to 250MB of logs per service (5 × 50MB files). Older logs are rotated out automatically.

**DEPLOY-REQ-039**: The `postgres` service does not require custom log rotation configuration — PostgreSQL's internal log management handles this within the data volume.

**DEPLOY-REQ-040**: All application logs from the `api` service MUST be written to stdout/stderr (not to files inside the container). This allows `docker compose logs api` to display them and Docker's logging driver to manage them.

---

## 11. Upgrade Procedure

**DEPLOY-REQ-041**: The standard upgrade procedure MUST be documented in the operator guide as:

```bash
# 1. Pull or build new images
docker compose build

# 2. Restart with new images (zero-data-loss rolling restart)
docker compose up -d

# Database migrations run automatically on api container startup.
# The postgres_data volume is preserved.
```

**DEPLOY-REQ-042**: Schema migrations (Alembic) run automatically on every `api` container start via the entrypoint script. If a migration fails, the container exits and Docker restarts it. Operators see the failure via `docker compose logs api`. This prevents the application from starting against an incompatible schema.

**DEPLOY-REQ-043**: Downgrade (rolling back a migration) requires manual intervention:
1. `docker compose run api alembic downgrade -1`
2. `docker compose up -d`
This is documented as an operational procedure, not an automated process.

---

## 12. Backup & Recovery

**DEPLOY-REQ-044**: The operator guide MUST document the following backup procedure for the `postgres_data` volume:

**Logical backup (recommended)**:
```bash
# Create a SQL dump
docker exec delivery-tracking-postgres-1 \
  pg_dump -U ${POSTGRES_USER} ${POSTGRES_DB} > backup_$(date +%Y%m%d_%H%M%S).sql
```

**Restore from backup**:
```bash
# Stop the api service to prevent writes during restore
docker compose stop api

# Restore from dump
cat backup_YYYYMMDD_HHMMSS.sql | \
  docker exec -i delivery-tracking-postgres-1 \
  psql -U ${POSTGRES_USER} ${POSTGRES_DB}

# Restart
docker compose start api
```

**DEPLOY-REQ-045**: No automated backup mechanism is built into the application. Backup scheduling is the operator's responsibility (e.g. a cron job running the pg_dump command above). This is documented as a known operational gap.

---

## 13. Resource Recommendations

**DEPLOY-REQ-046**: Minimum host resource requirements:

| Resource | Minimum | Notes |
|----------|---------|-------|
| CPU | 1 core | Low utilisation; polling is infrequent |
| RAM | 512 MB | ~150MB for postgres, ~100MB for api, ~10MB for nginx |
| Storage | 1 GB | Primarily for PostgreSQL data volume; grows slowly |
| Network | Outbound HTTPS | Required to reach api.parcel.app |

> The service is well-suited for deployment on a Raspberry Pi 4, a home server, or a small VPS.

**DEPLOY-REQ-047**: Optional resource limits MAY be defined in `docker-compose.yml` to prevent any single container monopolising the host:

```yaml
deploy:
  resources:
    limits:
      memory: 256M
      cpus: '0.5'
```

These are commented out by default — uncomment if running on memory-constrained hardware.

---

## 14. `.env.example` Specification

**DEPLOY-REQ-048**: The `.env.example` file committed to the repository MUST contain all environment variables with placeholder values, inline comments, and clear section headers:

```bash
# ============================================================
# Delivery Tracking Service — Environment Configuration
# Copy this file to .env and fill in your values.
# NEVER commit .env to source control.
# ============================================================

# ── Database ─────────────────────────────────────────────────
POSTGRES_USER=delivery_user
POSTGRES_PASSWORD=change_this_strong_password
POSTGRES_DB=delivery_tracker

# Constructed from the above — update if you change them
DATABASE_URL=postgresql+psycopg://delivery_user:change_this_strong_password@postgres:5432/delivery_tracker

# ── Parcel API ────────────────────────────────────────────────
# Get your API key at https://web.parcelapp.net
PARCEL_API_KEY=your_parcel_api_key_here

# ── Authentication ────────────────────────────────────────────
# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=replace_with_64_hex_chars_minimum_32_chars_required

# ── First-Run Admin Setup ─────────────────────────────────────
# IMPORTANT: Remove ADMIN_PASSWORD from .env after first successful start.
ADMIN_USERNAME=admin
ADMIN_PASSWORD=change_me_immediately_at_least_12_chars

# ── Frontend ──────────────────────────────────────────────────
FRONTEND_HTTP_PORT=80

# ── HTTPS (optional — leave HTTPS_ENABLED=false for HTTP-only) ─
HTTPS_ENABLED=false
# SSL_CERT_PATH=/path/on/host/to/cert.pem
# SSL_KEY_PATH=/path/on/host/to/key.pem
# COOKIE_SECURE=true  # Uncomment when HTTPS_ENABLED=true

# ── Polling (defaults shown) ──────────────────────────────────
# POLL_INTERVAL_MINUTES=15
# POLL_JITTER_SECONDS=30

# ── Application ───────────────────────────────────────────────
ENVIRONMENT=production
# LOG_LEVEL=INFO
```

---

## 15. Requirements Summary

| ID | Requirement |
|----|-------------|
| DEPLOY-REQ-001 | All services on shared Docker bridge network `delivery_network` |
| DEPLOY-REQ-002 | postgres and api ports NOT exposed on host |
| DEPLOY-REQ-003 | frontend exposes port 80; configurable via FRONTEND_HTTP_PORT |
| DEPLOY-REQ-004 | api depends_on postgres with condition: service_healthy |
| DEPLOY-REQ-005 | restart: unless-stopped on all three services |
| DEPLOY-REQ-006 | api Dockerfile uses two-stage build |
| DEPLOY-REQ-007 | api runtime image based on python:3.12-slim |
| DEPLOY-REQ-008 | api container runs as non-root appuser |
| DEPLOY-REQ-009 | .env file never copied into api image |
| DEPLOY-REQ-010 | api container uses entrypoint.sh shell script |
| DEPLOY-REQ-011 | frontend Dockerfile uses multi-stage build (node:20-alpine + nginx:alpine) |
| DEPLOY-REQ-012 | npm ci used in frontend build stage |
| DEPLOY-REQ-013 | frontend runtime image contains only static assets + Nginx |
| DEPLOY-REQ-014 | postgres uses official postgres:16.3-alpine without customisation |
| DEPLOY-REQ-015 | postgres_data named volume mounted at /var/lib/postgresql/data |
| DEPLOY-REQ-016 | postgres_data uses local driver |
| DEPLOY-REQ-017 | postgres_data persists across restarts and rebuilds |
| DEPLOY-REQ-018 | Volume destruction requires explicit --volumes flag; documented as destructive |
| DEPLOY-REQ-019 | SSL certs provided via read-only bind mounts when HTTPS enabled |
| DEPLOY-REQ-020 | api and frontend containers have no persistent volumes |
| DEPLOY-REQ-021 | entrypoint.sh: migrations → seed → uvicorn in strict order |
| DEPLOY-REQ-022 | set -e in entrypoint; migration/seed failure stops container |
| DEPLOY-REQ-023 | Uvicorn started with --workers 1 |
| DEPLOY-REQ-024 | Uvicorn binds to 0.0.0.0 |
| DEPLOY-REQ-025 | Uvicorn started with --no-access-log |
| DEPLOY-REQ-026 | Seed script checks user count; creates admin if zero |
| DEPLOY-REQ-027 | Seed script is idempotent |
| DEPLOY-REQ-028 | Seed script exits non-zero if DB empty and credentials not set |
| DEPLOY-REQ-029 | Nginx config: API proxy to api:8000, SPA fallback to index.html |
| DEPLOY-REQ-030 | try_files directive enables client-side SPA routing |
| DEPLOY-REQ-031 | Static assets served with Cache-Control: public, immutable, 1-year expires |
| DEPLOY-REQ-032 | Nginx sets X-Real-IP and X-Forwarded-For on API proxy requests |
| DEPLOY-REQ-033 | HTTPS Nginx: HTTP→HTTPS redirect, TLS 1.2+ only, strong ciphers |
| DEPLOY-REQ-034 | HTTPS config in separate nginx-https.conf; avoids startup failure without certs |
| DEPLOY-REQ-035 | postgres healthcheck: pg_isready, 10s interval, 30s start_period |
| DEPLOY-REQ-036 | api healthcheck: GET /api/health, 30s interval, 60s start_period |
| DEPLOY-REQ-037 | frontend healthcheck: GET /, 30s interval |
| DEPLOY-REQ-038 | json-file logging with max-size 50m, max-file 5 on api and frontend |
| DEPLOY-REQ-039 | postgres log rotation managed internally |
| DEPLOY-REQ-040 | api logs written to stdout/stderr only |
| DEPLOY-REQ-041 | Upgrade procedure: docker compose build + docker compose up -d |
| DEPLOY-REQ-042 | Migrations run automatically on api container start |
| DEPLOY-REQ-043 | Downgrade requires manual alembic downgrade procedure |
| DEPLOY-REQ-044 | Backup via pg_dump documented in operator guide |
| DEPLOY-REQ-045 | No automated backup; operator's responsibility |
| DEPLOY-REQ-046 | Minimum: 1 CPU core, 512MB RAM, 1GB storage |
| DEPLOY-REQ-047 | Optional resource limits documented (commented out by default) |
| DEPLOY-REQ-048 | .env.example with all variables, placeholders, comments, and section headers |

---

*Source: Architecture (01-architecture.md), security requirements (07-auth-security.md), user scoping input (Docker self-hosted)*  
*Traceability: DEPLOY-REQ-001 through DEPLOY-REQ-048*
