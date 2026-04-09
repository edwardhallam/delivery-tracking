---
status: complete
linear_issue: DEL-9
spec: docs/designs/2026-04-08-demo-mode-day1-design.md
---

# Day1 Demo Mode Implementation Plan

> **For agentic workers:** Use build-inline to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Rebrand delivery tracker as "Day1" with a demo account serving fixture data, disable live polling, and deploy at day1.edwardhallam.com.

**Architecture:** Add a DEMO_MODE config flag. When true: seed script creates a demo user + 6 fixture deliveries instead of admin user, lifespan skips Parcel API / scheduler startup (stubs used for health endpoint), and frontend shows a demo banner. All read-path code (use cases, repos, routers) unchanged.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2.0 async, React 18, TypeScript, Tailwind CSS, Cloudflare Tunnels

**QA Tier:** Medium

**Spec:** docs/designs/2026-04-08-demo-mode-day1-design.md

---

## Task 1: Configuration - DEMO_MODE flag and optional PARCEL_API_KEY

**Files:**
- Modify: api/app/config.py
- Modify: api/tests/conftest.py

- [ ] **Step 1: Update config.py**

Add DEMO_MODE field. Change PARCEL_API_KEY to optional. Replace the field-level validator with a model validator that checks the API key only when not in demo mode.

In the Settings class fields, add after FRONTEND_HTTP_PORT:
  DEMO_MODE: bool = False

Change PARCEL_API_KEY from SecretStr to Optional[SecretStr] = None.

Remove the parcel_api_key_non_empty field validator. Add a model_validator(mode='after') named require_parcel_api_key_when_not_demo that raises ValueError if PARCEL_API_KEY is None or empty when DEMO_MODE is False. When DEMO_MODE is True, skip the check.

Add model_validator to the pydantic import.

- [ ] **Step 2: Update test conftest**

In api/tests/conftest.py, add os.environ.setdefault("DEMO_MODE", "false") after the existing setdefault lines.

- [ ] **Step 3: Run existing tests to verify backward compatibility**

- [ ] **Step 4: Commit**

---

## Task 2: Seed script - demo user and fixture deliveries

**Files:**
- Modify: api/app/seed.py

- [ ] **Step 1: Refactor seed.py with demo mode branch**

Extract the existing admin seed logic into _seed_admin_user(session, pwd_context). Add _seed_demo_data(session, pwd_context) that:
- Creates demo user: username="demo", password=bcrypt("demo"), is_active=True (no _MIN_PASSWORD_LENGTH check)
- Inserts 6 DeliveryORM rows:
  - DAY1-AMZN-001 / amazon_logistics / Wireless Headphones / status_code=0 / DELIVERED
  - DAY1-FEDX-002 / fedex / Standing Desk Frame / status_code=2 / IN_TRANSIT
  - DAY1-UPS-003 / ups / Mechanical Keyboard / status_code=4 / OUT_FOR_DELIVERY
  - DAY1-DHL-004 / dhl / Camera Lens / status_code=8 / INFO_RECEIVED
  - DAY1-USPS-005 / usps / Vintage Record / status_code=7 / EXCEPTION
  - DAY1-ROYML-006 / royal_mail / Tea Collection / status_code=1 / FROZEN
- Each delivery gets 2-4 DeliveryEventORM rows with realistic descriptions, locations, event_date_raw as ISO date strings, sequential sequence_number starting at 0
- Each delivery gets 1-2 StatusHistoryORM entries (initial entry with previous_*=NULL, plus a transition entry for DELIVERED and EXCEPTION)
- All timestamps relative to now at seed time, staggered over 7 days
- timestamp_expected set for deliveries with expected dates, None for EXCEPTION/FROZEN
- last_raw_response=None, poll_log_id=None

The main seed_initial_user() retains the idempotency guard, then branches on settings.DEMO_MODE.

- [ ] **Step 2: Verify existing tests still pass**

- [ ] **Step 3: Commit**

---

## Task 3: Lifespan - demo mode stubs for scheduler and carrier cache

**Files:**
- Modify: api/app/main.py

- [ ] **Step 1: Add stub classes and conditional lifespan**

Add two inline stub classes before the lifespan function:
- _DemoSchedulerStub(AbstractSchedulerState): is_running() returns False, get_next_poll_at() returns None
- _DemoCarrierCacheStub(AbstractCarrierCache): get_carriers() returns CarrierListDTO(carriers=[], cached_at=None, cache_status="unavailable"), refresh() is a no-op

Add imports for AbstractCarrierCache, AbstractSchedulerState from app.application.services.interfaces, and CarrierListDTO from app.application.dtos.system_dtos.

Modify the lifespan function to branch on settings.DEMO_MODE:
- Demo mode: set app.state.polling_scheduler and app.state.carrier_cache to stubs, yield, log shutdown
- Non-demo: existing full startup sequence unchanged

- [ ] **Step 2: Verify existing tests still pass**

- [ ] **Step 3: Commit**

---

## Task 4: New endpoint - GET /api/auth/me

**Files:**
- Modify: api/app/presentation/schemas/auth_schemas.py
- Modify: api/app/presentation/routers/auth_router.py

- [ ] **Step 1: Add UserInfoSchema and UserInfoResponse to auth_schemas.py**

UserInfoSchema: username (str), is_demo (bool)
UserInfoResponse: data (UserInfoSchema)

- [ ] **Step 2: Add GET /me endpoint to auth_router.py**

Requires get_current_user dependency. Returns UserInfoResponse with is_demo = (current_user.username == "demo"). Add UserInfoResponse and UserInfoSchema to the existing auth_schemas import.

- [ ] **Step 3: Verify existing tests still pass**

- [ ] **Step 4: Commit**

---

## Task 5: Frontend - demo banner and useMe hook

**Files:**
- Create: frontend/src/hooks/useMe.ts
- Modify: frontend/src/types/api.ts
- Modify: frontend/src/components/Header.tsx

- [ ] **Step 1: Add UserInfo type to api.ts**

Add interface UserInfo with username (string) and is_demo (boolean) in the Auth section.

- [ ] **Step 2: Create useMe.ts hook**

Uses useQuery with queryKey ["me"], calls GET /auth/me, returns UserInfo. staleTime: Infinity.

- [ ] **Step 3: Update Header.tsx**

Add DemoBanner component: amber background div with "Demo Mode -- APIs are not active."
Import and call useMe() hook. When is_demo is true:
- Render DemoBanner above the header element (use Fragment wrapper)
- Hide PollIndicator and refresh button
Keep logout button visible always.

- [ ] **Step 4: Commit**

---

## Task 6: Update .env.example with DEMO_MODE

**Files:**
- Modify: .env.example

- [ ] **Step 1: Add DEMO_MODE section**

Add after the Frontend section: a Demo Mode section explaining it seeds a demo user with fixture deliveries and disables polling. Default: false.

- [ ] **Step 2: Commit**

---

## Task 7: Update README for Day1 rebrand

**Files:**
- Modify: README.md

- [ ] **Step 1: Rewrite README.md**

Title: "Day1". Description: "A delivery tracking dashboard built in one day."
Add demo mode to feature table. Quick start shows both demo mode (no API key) and live mode configs. Add GET /api/auth/me to API table. Update config table with DEMO_MODE and conditional PARCEL_API_KEY. Remove all references to deliveries.edwardhallam.com. Do NOT include demo credentials. Keep architecture, tech stack, project structure, development sections.

- [ ] **Step 2: Commit**

---

## Task 8: Cloudflare tunnel route update

**Files:** None (infrastructure operation)

- [ ] **Step 1: Update CF tunnel route**

Use CF Zero Trust MCP tools to:
1. Find oci-edwardhallam-com tunnel
2. Remove deliveries.edwardhallam.com route
3. Add day1.edwardhallam.com route to same origin
4. Add/verify DNS CNAME for day1.edwardhallam.com

- [ ] **Step 2: Verify DNS resolves**

---

## Task 9: Deploy to OCI

**Files:** None (server operation)

- [ ] **Step 1: Push code to GitHub**
- [ ] **Step 2: Pull on OCI server**
- [ ] **Step 3: Update .env on OCI** - Set DEMO_MODE=true, remove PARCEL_API_KEY, ADMIN_USERNAME, ADMIN_PASSWORD
- [ ] **Step 4: Reset DB and rebuild** - docker compose down, remove postgres volume (fresh DB for demo seed), docker compose build, docker compose up -d
- [ ] **Step 5: Verify logs** - Check for "Demo mode" and "6 fixture deliveries" messages
- [ ] **Step 6: Verify via browser** - day1.edwardhallam.com loads, demo login works, banner visible, 6 deliveries rendered
- [ ] **Step 7: Verify old domain gone** - deliveries.edwardhallam.com no longer resolves
