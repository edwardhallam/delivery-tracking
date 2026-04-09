---
status: complete
linear_issue: DEL-9
execution_mode: inline
---

# Day1 Demo Mode Design Spec

**Goal:** Rebrand the delivery tracker as "Day1", disable live polling, replace the admin account with a demo account serving fixture data, and deploy at day1.edwardhallam.com.

**Architecture:** Seed fixture deliveries into the existing database so the entire read path (use cases, repositories, routers) works unchanged. A `DEMO_MODE` config flag disables the Parcel API scheduler at startup and makes the API key optional. The frontend shows a demo banner when the logged-in user is the demo account.

**QA Tier:** Medium (5-6 files changed, shallow changes, but touches config validation, scheduler startup, CF tunnel, and deployment)

**Execution Mode:** Inline (tightly coupled sequential work)

## Design

### 1. Configuration

**`api/app/config.py`:**

- Add `DEMO_MODE: bool = False`
- Change `PARCEL_API_KEY` type from `SecretStr` to `Optional[SecretStr] = None`
- Update `parcel_api_key_non_empty` validator: use `@model_validator(mode='after')` to check that `PARCEL_API_KEY` is set and non-empty only when `DEMO_MODE=False`. When `DEMO_MODE=True`, skip the check entirely.
- `ADMIN_USERNAME`/`ADMIN_PASSWORD` are ignored in demo mode (seed creates demo user instead)

**`.env.example`:**

- Add `DEMO_MODE=false` with comment explaining it disables polling and seeds a demo user with fixture data

### 2. Seed Script

**`api/app/seed.py`:**

- Retain the existing idempotency guard (`count > 0` = skip)
- When `DEMO_MODE=True`:
  - Create demo user: username=`demo`, password=bcrypt("demo"), is_active=True. The `_MIN_PASSWORD_LENGTH` check is skipped in demo mode (guarded by `if not settings.DEMO_MODE`).
  - Insert 6 fixture deliveries into `deliveries` table as `DeliveryORM` rows:

    | tracking_number | carrier_code | description | parcel_status_code | semantic_status |
    |---|---|---|---|---|
    | DAY1-AMZN-001 | amazon_logistics | Wireless Headphones | 0 | DELIVERED |
    | DAY1-FEDX-002 | fedex | Standing Desk Frame | 2 | IN_TRANSIT |
    | DAY1-UPS-003 | ups | Mechanical Keyboard | 4 | OUT_FOR_DELIVERY |
    | DAY1-DHL-004 | dhl | Camera Lens | 8 | INFO_RECEIVED |
    | DAY1-USPS-005 | usps | Vintage Record | 7 | EXCEPTION |
    | DAY1-ROYML-006 | royal_mail | Tea Collection | 1 | FROZEN |

  - Each delivery gets 2-4 `DeliveryEventORM` rows with realistic `event_description`, `event_date_raw` (formatted as ISO date string), `location`, and sequential `sequence_number` starting at 0.
  - Each delivery gets 1 initial `StatusHistoryORM` entry (`previous_*` = NULL, `new_*` = current status). Deliveries with non-initial statuses (DELIVERED, EXCEPTION) get a second entry showing the transition.
  - All timestamps (`first_seen_at`, `last_seen_at`, `created_at`, `updated_at`, `recorded_at`, `detected_at`) are set relative to `datetime.now(timezone.utc)` at seed time. Offsets stagger deliveries over the past 7 days.
  - `timestamp_expected` set for deliveries with expected dates; `None` for EXCEPTION/FROZEN.
  - `last_raw_response` set to `None` (no Parcel API involved).
  - `poll_log_id` on status history entries set to `None` (seeded data, not from polling).
- When `DEMO_MODE=False`: existing admin seed behavior, unchanged

### 3. API & Scheduler

**`api/app/main.py` (lifespan):**

- When `DEMO_MODE=True`:
  - Skip `httpx.AsyncClient`, `ParcelAPIClient`, `CarrierCache`, and `PollingScheduler` creation
  - Create inline stub classes (defined in `main.py`, not separate files):
    - `DemoSchedulerStub(AbstractSchedulerState)`: `is_running() -> False`, `get_next_poll_at() -> None`
    - `DemoCarrierCacheStub(AbstractCarrierCache)`: `get_carriers() -> CarrierListDTO(carriers=[], cache_status="unavailable")`, `refresh() -> None` (no-op)
  - Set `app.state.polling_scheduler` and `app.state.carrier_cache` to these stubs
  - Do not set `app.state.http_client` or `app.state.parcel_client` (not needed; shutdown skips closing them)
- When `DEMO_MODE=False`: existing startup sequence, unchanged

**New endpoint: `GET /api/auth/me`:**

- Requires valid access token (uses `get_current_user` dependency)
- Response schema `UserInfoResponse`: `{ "data": { "username": str, "is_demo": bool } }`
- `is_demo` derived as `user.username == "demo"` in the route handler
- Add `UserInfoSchema` to `auth_schemas.py`, `UserInfoResponse` wrapping it
- 401 on invalid/missing token (standard `UNAUTHORIZED`, same as other protected endpoints)

**No changes to:** delivery use cases, repositories, routers, DTOs, mappers, or domain layer. They serve whatever is in the database.

### 4. Frontend

**`Header.tsx`:**

- Fetch `/api/auth/me` (or receive `is_demo` from login response / auth context)
- When `is_demo=true`: render a full-width amber banner above the header bar:
  > "Demo Mode -- APIs are not active."
- Hide `PollIndicator` in demo mode (no scheduler running)

**`LoginPage.tsx`:**

- No changes. No pre-filled credentials. Visitors must know the credentials externally.

**No other frontend changes.** Delivery list and detail pages render whatever the API returns.

### 5. Deployment & Infrastructure

**Cloudflare tunnel (`oci-edwardhallam-com`):**

- Remove `deliveries.edwardhallam.com` route
- Add `day1.edwardhallam.com` route pointing to the same origin

**CF DNS:**

- Add CNAME `day1` -> tunnel (if needed; tunnel routes may handle this automatically)

**OCI `.env`:**

- Set `DEMO_MODE=true`
- Remove `PARCEL_API_KEY` (no longer required)
- Remove `ADMIN_USERNAME`/`ADMIN_PASSWORD` (demo user seeded automatically)

**Redeploy:**

- `docker compose build && docker compose up -d --force-recreate`
- Seed script runs on boot, creates demo user + fixtures
- Verify via `day1.edwardhallam.com` with demo/demo login

### 6. GitHub Rebrand

**README.md:**

- Title: "Day1"
- Description: "A delivery tracking dashboard built in one day."
- Update all references from `deliveries.edwardhallam.com` to `day1.edwardhallam.com`
- Do NOT include demo credentials
- Keep technical setup docs (Docker Compose, .env.example, etc.)

**Repository:** Rename if desired (separate manual step on GitHub).

## Personas

N/A — inline execution, primary agent handles all tasks.

## Follow-Up Monitoring

- After deploy: verify `day1.edwardhallam.com` loads, demo login works, fixture data renders, demo banner visible
- Verify `deliveries.edwardhallam.com` no longer resolves (CF route removed)
- Monitor OCI container logs for clean startup without Parcel API key
