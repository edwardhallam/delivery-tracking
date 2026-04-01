# Web Dashboard Requirements

**Document ID**: DASH-001  
**Plan Phase**: Phase 6  
**Status**: Draft — Awaiting Review  
**Project**: Delivery Tracking Web Service  
**Dependencies**: [01-architecture.md](./01-architecture.md), [04-status-normalization.md](./04-status-normalization.md), [05-rest-api.md](./05-rest-api.md)

---

## 1. Overview

The web dashboard is a single-page application (SPA) served by Nginx that provides the primary user interface for the Delivery Tracking Service. It is the sole consumer of the REST API and is purpose-built for a single authenticated user.

**Primary goal**: At a glance, show what packages are coming, where they are, and when to expect them.

### Technology Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 18 + TypeScript |
| Build tool | Vite |
| Routing | React Router v6 |
| Data fetching | TanStack Query (React Query) v5 |
| HTTP client | Axios |
| Styling | Tailwind CSS v3 |
| Component primitives | shadcn/ui |
| Auth state | React Context + in-memory token |

### Routes

| Path | Component | Auth Required | Description |
|------|-----------|:-------------:|-------------|
| `/login` | `LoginPage` | ❌ | Credential entry |
| `/` | Redirect → `/deliveries` | ✅ | Root redirect |
| `/deliveries` | `DeliveryListPage` | ✅ | Main dashboard view |
| `/deliveries/:id` | `DeliveryDetailPage` | ✅ | Single delivery detail |
| `*` (404) | `NotFoundPage` | — | Unknown routes |

**DASH-REQ-001**: Any navigation to an authenticated route when no valid session exists MUST redirect to `/login`, preserving the originally requested path as a `redirect` query parameter (e.g. `/login?redirect=/deliveries/3fa85f64`). After successful login, the user is forwarded to the preserved path.

---

## 2. Application Shell

### 2.1 Layout

The application shell wraps all authenticated pages with a consistent top navigation bar and a main content area.

```
┌────────────────────────────────────────────────────────────┐
│  HEADER                                                    │
│  📦 Delivery Tracker          ● Last polled 3 min ago  [↻] [Logout] │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  PAGE CONTENT                                              │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### 2.2 Header

**DASH-REQ-002**: The header MUST be present on all authenticated pages and MUST contain:

| Element | Behaviour |
|---------|-----------|
| App name/logo | "Delivery Tracker" — links to `/deliveries` |
| Poll status indicator | Dot + text: "Last polled X min ago" — sourced from `GET /health` `polling.last_poll_at` |
| Manual refresh button (↻) | Triggers re-fetch of the current page's data from the API (does not trigger a new Parcel poll) |
| Logout button | Calls `POST /api/auth/logout` then redirects to `/login` |

**DASH-REQ-003**: The poll status indicator MUST use colour to communicate health:

| Condition | Indicator Colour | Text |
|-----------|-----------------|------|
| `last_poll_outcome = success` and polled ≤ 20 min ago | Green dot | "Last polled X min ago" |
| `last_poll_outcome = success` and polled > 20 min ago | Amber dot | "Last polled X min ago" |
| `last_poll_outcome = error` or `degraded` health | Red dot | "Polling issue — last polled X min ago" |
| Health endpoint unreachable | Grey dot | "Status unknown" |

**DASH-REQ-004**: The header health indicator MUST refresh automatically every **60 seconds** by polling `GET /api/health` in the background. This is independent of the delivery data refresh cycle.

---

## 3. Login Page (`/login`)

### 3.1 Layout

```
┌────────────────────────────────────────────────┐
│                                                │
│              📦 Delivery Tracker               │
│                                                │
│  ┌──────────────────────────────────────────┐  │
│  │  Username                                │  │
│  │  [________________________]              │  │
│  │                                          │  │
│  │  Password                                │  │
│  │  [________________________]              │  │
│  │                                          │  │
│  │  [        Sign In         ]              │  │
│  │                                          │  │
│  │  ⚠ Invalid username or password          │  │
│  └──────────────────────────────────────────┘  │
│                                                │
└────────────────────────────────────────────────┘
```

### 3.2 Behaviour

**DASH-REQ-005**: The login form MUST contain:
- `username` text input (autofocus on page load)
- `password` input (type=`password`)
- "Sign In" submit button
- Error message area (hidden when no error)

**DASH-REQ-006**: The "Sign In" button MUST be disabled and show a loading spinner while the login request is in flight. The form MUST prevent double-submission.

**DASH-REQ-007**: On `401 INVALID_CREDENTIALS` from `POST /api/auth/login`, the error area MUST display: *"Invalid username or password."* No distinction between the two is shown (matching API-REQ-006).

**DASH-REQ-008**: On `403 ACCOUNT_DISABLED`, display: *"This account has been disabled. Contact the administrator."*

**DASH-REQ-009**: On network error or `5xx` response, display: *"Unable to connect. Please try again."*

**DASH-REQ-010**: On successful login:
1. Store the access token in React auth context (in-memory)
2. The `refresh_token` httpOnly cookie is set automatically by the browser from the `Set-Cookie` response header
3. Navigate to the redirect path (if present) or `/deliveries`

**DASH-REQ-011**: If the user navigates to `/login` while already authenticated (valid token in context), they MUST be immediately redirected to `/deliveries`.

**DASH-REQ-012**: The login page MUST support form submission via the `Enter` key from any input field.

---

## 4. Delivery List Page (`/deliveries`)

This is the primary view. Its purpose is to answer: *"What's on its way to me, and when?"*

### 4.1 Layout

```
┌────────────────────────────────────────────────────────────┐
│ HEADER (see §2.2)                                          │
├────────────────────────────────────────────────────────────┤
│                                                            │
│  [All] [Active] [Needs Attention] [Delivered]   🔍 [Search] │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Description    │ Carrier │ Status         │ Expected  │  │
│  ├────────────────┼─────────┼────────────────┼──────────┤  │
│  │ Amazon - iPad  │ DHL     │ 🔵 In Transit  │ Tomorrow │  │
│  │ ASOS Order     │ Evri    │ 🔵 Out for Del │ Today    │  │
│  │ Apple Store    │ UPS     │ 🔴 Failed      │ —        │  │
│  │ eBay - Camera  │ Royal..  │ 🔵 Info Rcvd  │ Jan 22   │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  Showing 4 of 4 deliveries                                 │
└────────────────────────────────────────────────────────────┘
```

### 4.2 Filter Tabs

**DASH-REQ-013**: The list view MUST display a filter tab bar with the following tabs:

| Tab Label | API Parameters | Description |
|-----------|---------------|-------------|
| **All** | *(no lifecycle filter, include_terminal=false)* | All non-terminal deliveries |
| **Active** | `lifecycle_group=ACTIVE` | Progressing normally |
| **Needs Attention** | `lifecycle_group=ATTENTION` | Requires user awareness |
| **Delivered** | `lifecycle_group=TERMINAL` | Completed and stalled |

**DASH-REQ-014**: The **"Needs Attention"** tab MUST display a badge count showing the number of deliveries in the `ATTENTION` group. This count is fetched alongside the delivery list and updates on each data refresh. If the count is zero, the badge is hidden.

**DASH-REQ-015**: The default tab on page load is **"All"**. The selected tab persists in the URL as a query parameter (`?tab=all|active|attention|delivered`) so that bookmarking and browser navigation work correctly.

### 4.3 Search

**DASH-REQ-016**: A search input field MUST be present on the right of the filter bar. It searches across `description` and `tracking_number` via the `search` query parameter on `GET /api/deliveries`.

**DASH-REQ-017**: Search MUST be **debounced** — the API call is not triggered until the user has stopped typing for **300 milliseconds**. This prevents a request on every keystroke.

**DASH-REQ-018**: The search input is applied on top of the current tab filter. A user can search within "Needs Attention" deliveries for example.

**DASH-REQ-019**: When a search term is active, a clear (✕) button MUST appear within the search input to reset it.

### 4.4 Delivery Table

**DASH-REQ-020**: The delivery table MUST display the following columns:

| Column | Source Field | Sortable | Default Sort | Notes |
|--------|-------------|:--------:|:------------:|-------|
| **Description** | `description` | ✅ | — | Truncated to single line with ellipsis; full text on hover tooltip |
| **Carrier** | `carrier_code` | ✅ | — | Display name looked up from `/api/carriers`; fall back to raw `carrier_code` if name not found |
| **Status** | `semantic_status` + `lifecycle_group` | ✅ | — | Coloured badge (see §6) |
| **Expected Delivery** | `timestamp_expected` / `date_expected_raw` | ✅ | ⬇️ Ascending | See date display rules (§4.5) |

**DASH-REQ-021**: The default sort is **Expected Delivery ascending** (soonest first, NULLs last). The currently active sort column and direction MUST be visually indicated in the column header with an arrow icon.

**DASH-REQ-022**: Clicking a column header toggles sort direction (`asc` → `desc` → `asc`). Sort state MUST persist in the URL as query parameters (`?sort_by=timestamp_expected&sort_dir=asc`) so that page refreshes and bookmarks preserve the sort.

**DASH-REQ-023**: Each table row MUST be clickable and navigate to `/deliveries/:id` on click. The entire row is the click target (not just the description cell).

**DASH-REQ-024**: A **tracking number** is NOT displayed as a primary column but MUST be accessible. It appears as secondary smaller text below the `description` in the Description column.

### 4.5 Expected Delivery Date Display Rules

The date/time data from the Parcel API has known timezone ambiguity (see DM-BR-024). Display must handle this gracefully.

**DASH-REQ-025**: Expected delivery date rendering priority:

```
1. If timestamp_expected is present (UTC epoch, timezone-aware):
   → Use for relative/calendar rendering
   → Display rules:
      - Same calendar day as today  → "Today"
      - Next calendar day           → "Tomorrow"  
      - Within 7 days               → Day name (e.g. "Thursday")
      - Beyond 7 days               → Short date (e.g. "22 Jan")
      - If timestamp_expected_end also present → show as window:
        "Today, 12:00 – 18:00"
        "Thursday, 09:00 – 13:00"

2. If only date_expected_raw is present (timezone-naive string):
   → Display verbatim as returned by API, no formatting applied
   → Prefix with tilde to indicate approximate: "~ 2025-01-16 12:00"

3. If neither is present:
   → Display "—" (em dash)
```

**DASH-REQ-026**: All relative date labels ("Today", "Tomorrow", day names) MUST be computed using the **browser's local timezone**, not UTC. The `timestamp_expected` epoch value is first converted to the user's local time before applying the label rules.

### 4.6 Pagination

**DASH-REQ-027**: The list view MUST display pagination controls at the bottom of the table when `pages > 1`. Pagination shows: `Previous` button, current page number indicator (e.g. "Page 2 of 5"), `Next` button. Individual page number buttons are not required.

**DASH-REQ-028**: The default `page_size` for the delivery list is **25**. It is not user-configurable in this version.

**DASH-REQ-029**: Page number MUST persist in the URL as `?page=N` so that browser back/forward navigation works correctly.

### 4.7 Data Refresh

**DASH-REQ-030**: The delivery list MUST **automatically refresh** every **5 minutes** using TanStack Query's `refetchInterval`. This keeps the dashboard current without requiring manual interaction. The in-progress spinner during a background refresh MUST be subtle (e.g. a small indicator in the header area) — it MUST NOT replace or obscure the current table content.

**DASH-REQ-031**: The manual refresh button (↻) in the header MUST trigger an immediate invalidation of the TanStack Query cache, causing the list to re-fetch immediately.

**DASH-REQ-032**: On initial page load, the list MUST display a skeleton loading state (placeholder rows) while the first data fetch is in progress, not a blank screen or spinner overlay.

### 4.8 Empty States

**DASH-REQ-033**: Empty states for the delivery list:

| Condition | Message |
|-----------|---------|
| "All" tab empty (no non-terminal deliveries) | "No active deliveries. All packages have been delivered or the tracking list is empty in Parcel." |
| Tab filter active, no results | "No [Active / Attention / Delivered] deliveries." |
| Search active, no results | "No deliveries match '[search term]'." |
| API error on load | "Unable to load deliveries. [Retry] button." |
| First ever poll not yet run | "Waiting for first sync with Parcel… This may take up to a minute." |

---

## 5. Delivery Detail Page (`/deliveries/:id`)

### 5.1 Layout

```
┌────────────────────────────────────────────────────────────┐
│ HEADER                                                     │
├────────────────────────────────────────────────────────────┤
│                                                            │
│ ← Back to deliveries                                       │
│                                                            │
│ ┌──────────────────────────────────────────────────────┐   │
│ │  Amazon - MacBook Pro              🔵 In Transit     │   │
│ │  1Z999AA10123456784 · UPS          📅 Tomorrow       │   │
│ └──────────────────────────────────────────────────────┘   │
│                                                            │
│ STATUS HISTORY ─────────────────────────────────────       │
│  ●── Info Received        10 Jan, 09:00                    │
│  ●── In Transit           12 Jan, 08:15                    │
│  ◌   (current)                                             │
│                                                            │
│ TRACKING EVENTS ────────────────────────────────────       │
│  14:30  Package arrived at facility · London, UK           │
│         Sorted for next-day delivery                       │
│  10:15  Shipment information sent to DHL                   │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

### 5.2 Delivery Header Card

**DASH-REQ-034**: The delivery header card MUST display:
- `description` — primary heading
- `tracking_number` and carrier display name — secondary line
- Status badge (`semantic_status` + `lifecycle_group` colour)
- Expected delivery date (same rendering rules as §4.5)
- `extra_information` if present (shown as a small supplementary label, e.g. "Postcode: SW1A 1AA")

### 5.3 Status History Timeline

**DASH-REQ-035**: The status history MUST be rendered as a **vertical timeline** with one node per `StatusHistory` entry, ordered oldest-to-newest (top-to-bottom). Each node displays:
- `new_semantic_status` display label (from `STATUS_DISPLAY` map)
- `detected_at` formatted as: `"DD MMM, HH:mm"` in the browser's local timezone
- The most recent node is visually distinguished (e.g. filled circle vs outline, or bold text)

**DASH-REQ-036**: The initial history entry (where `previous_semantic_status` is null) MUST be labelled with its `new_semantic_status` display label, prefixed with "First seen as:" to communicate it is the starting state.

### 5.4 Tracking Events Log

**DASH-REQ-037**: Tracking events MUST be rendered as a list, ordered by `sequence_number ASC` (oldest first, matching carrier scan chronology). Each event entry displays:
- `event_date_raw` — displayed verbatim (timezone-naive, as from carrier)
- `event_description`
- `location` if present (smaller secondary text)
- `additional_info` if present (smaller secondary text, italicised)

**DASH-REQ-038**: If `events` is an empty array, display: *"No tracking events recorded yet."*

### 5.5 Navigation

**DASH-REQ-039**: A "← Back to deliveries" link MUST appear above the detail card. It navigates back to `/deliveries`, preserving the filter/sort/search state the user had when they clicked through (using browser history or URL state).

### 5.6 Detail Page Data Refresh

**DASH-REQ-040**: The detail page MUST auto-refresh its data every **5 minutes**, consistent with the list page. Background refresh MUST not disrupt reading the event timeline.

**DASH-REQ-041**: If the delivery `lifecycle_group` is `TERMINAL` on load, the auto-refresh interval SHOULD be extended to **30 minutes** (terminal deliveries change rarely). If the status changes to non-terminal during a refresh, the interval reverts to 5 minutes.

---

## 6. Status Badge Component

The status badge is used in both the list and detail views.

### 6.1 Colour Scheme

**DASH-REQ-042**: Badge colours are determined by `lifecycle_group` with one override for `DELIVERED`:

| Condition | Background | Text | Example |
|-----------|-----------|------|---------|
| `lifecycle_group = ACTIVE` | Blue tint | Blue | `bg-blue-100 text-blue-800` |
| `lifecycle_group = ATTENTION` | Red tint | Red | `bg-red-100 text-red-700` |
| `semantic_status = DELIVERED` | Green tint | Green | `bg-green-100 text-green-800` |
| `semantic_status = FROZEN` | Grey tint | Grey | `bg-gray-100 text-gray-600` |

> `DELIVERED` receives a green badge (positive terminal) rather than the default grey for all `TERMINAL` states, to provide a positive visual confirmation that the delivery is complete.

### 6.2 Badge Content

**DASH-REQ-043**: The badge displays the `STATUS_DISPLAY` label string (e.g. "In Transit", "Out for Delivery") — never the raw `SemanticStatus` enum value or the integer `parcel_status_code`.

### 6.3 Attention Icon

**DASH-REQ-044**: Badges with `lifecycle_group = ATTENTION` MUST include a warning icon (⚠️ or equivalent) before the label text to draw immediate visual attention.

---

## 7. Session Management & Auth Flow

### 7.1 Authentication State

**DASH-REQ-045**: Authentication state is managed via React Context (`AuthContext`). The context holds:
- `accessToken: string | null` — the JWT access token (in-memory only, never persisted to localStorage or sessionStorage)
- `isAuthenticated: boolean` — derived from whether `accessToken` is non-null
- `login(token)` — stores the token and marks authenticated
- `logout()` — clears token, calls `POST /api/auth/logout`, navigates to `/login`

**DASH-REQ-046**: The access token MUST be stored **in-memory only** (React state). It MUST NOT be written to `localStorage`, `sessionStorage`, or any cookie. This prevents XSS-based token theft.

### 7.2 Silent Token Refresh

**DASH-REQ-047**: On application load (before rendering any route), the app MUST attempt a **silent token refresh** via `POST /api/auth/refresh`. This uses the `refresh_token` httpOnly cookie automatically:
- If refresh succeeds: store the new access token in `AuthContext`, render the app
- If refresh fails (no cookie, expired, invalid): render the login page

This ensures users with valid sessions are not forced to log in on every page load/refresh.

**DASH-REQ-048**: During the silent refresh on load, the app MUST display a **full-screen loading indicator** (e.g. centred spinner) — not a flash of the login page followed by a redirect. This prevents layout flash.

### 7.3 Axios Interceptors

**DASH-REQ-049**: An Axios request interceptor MUST automatically attach the current access token to every API request as a `Bearer` token in the `Authorization` header.

**DASH-REQ-050**: An Axios response interceptor MUST handle `401 UNAUTHORIZED` responses:
1. Attempt one token refresh via `POST /api/auth/refresh`
2. If refresh succeeds: retry the original failed request with the new token
3. If refresh fails: call `logout()` (clear state, navigate to `/login`)
4. The interceptor MUST prevent retry loops — it MUST NOT attempt to refresh if the failing request is itself `/api/auth/refresh`.

### 7.4 Logout

**DASH-REQ-051**: The logout button in the header MUST:
1. Call `POST /api/auth/logout` (best-effort — proceed even if the call fails)
2. Clear `AuthContext` access token
3. Navigate to `/login`
4. TanStack Query cache is cleared on logout to prevent stale data appearing for a subsequent user

---

## 8. Error Handling

**DASH-REQ-052**: All data-fetching errors from TanStack Query MUST be handled at the component level with user-friendly messages:

| Error Type | Display |
|-----------|---------|
| Network error | "Unable to connect to the server. Check your network." |
| `401` (handled by interceptor, should not surface) | Redirect to login (interceptor handles) |
| `404` on delivery detail | "Delivery not found." with link back to list |
| `5xx` | "Something went wrong. [Try again] button." |

**DASH-REQ-053**: TanStack Query retry configuration for delivery endpoints: **2 retries** with exponential backoff (1s, 2s). Auth endpoints: **0 retries** (fail immediately to avoid duplicate token calls).

**DASH-REQ-054**: A global error boundary MUST wrap the application. Unhandled React rendering errors MUST display a fallback UI ("Something went wrong. Please refresh the page.") rather than a blank screen.

---

## 9. Accessibility Requirements

**DASH-REQ-055**: The login form MUST have proper `<label>` elements associated with each input via `htmlFor`/`id`.

**DASH-REQ-056**: Status badges MUST include a visually hidden text alternative for screen readers (e.g. `<span class="sr-only">Status: In Transit</span>`). The colour alone MUST NOT be the only status indicator.

**DASH-REQ-057**: Interactive table rows MUST have `role="button"` and `tabIndex={0}` with keyboard support (`Enter`/`Space` to navigate). The table MUST be navigable by keyboard.

**DASH-REQ-058**: Page titles (`<title>`) MUST update on route change:
- Login: `"Sign In — Delivery Tracker"`
- Delivery list: `"Deliveries — Delivery Tracker"`
- Delivery detail: `"[description] — Delivery Tracker"`

---

## 10. Responsive Design

**DASH-REQ-059**: The dashboard is primarily designed for **desktop browser use** (≥ 1024px wide). A functional mobile layout (≥ 375px) is required but may collapse the table into a card-per-delivery layout at narrow widths.

**DASH-REQ-060**: At viewport widths below `768px`, the delivery table MUST switch to a **card-based layout** where each delivery is a stacked card showing all four fields vertically rather than as table columns.

---

## 11. Requirements Summary

| ID | Requirement |
|----|-------------|
| DASH-REQ-001 | Unauthenticated access to protected routes redirects to /login with redirect param |
| DASH-REQ-002 | Header on all authenticated pages: app name, poll status, refresh, logout |
| DASH-REQ-003 | Poll status indicator uses colour to communicate health |
| DASH-REQ-004 | Header health indicator auto-refreshes every 60 seconds |
| DASH-REQ-005 | Login form: username, password, submit, error area |
| DASH-REQ-006 | Submit button disabled + spinner during login request |
| DASH-REQ-007 | Invalid credentials → single generic error message |
| DASH-REQ-008 | Disabled account → specific error message |
| DASH-REQ-009 | Network/5xx error → "Unable to connect" message |
| DASH-REQ-010 | Successful login stores token in context, navigates to redirect path |
| DASH-REQ-011 | Authenticated user navigating to /login is redirected to /deliveries |
| DASH-REQ-012 | Login form submits on Enter key |
| DASH-REQ-013 | Filter tabs: All, Active, Needs Attention, Delivered |
| DASH-REQ-014 | Needs Attention tab shows badge count; hidden when zero |
| DASH-REQ-015 | Default tab is All; tab persists in URL query param |
| DASH-REQ-016 | Search across description + tracking_number |
| DASH-REQ-017 | Search debounced 300ms |
| DASH-REQ-018 | Search applies within current tab filter |
| DASH-REQ-019 | Active search shows clear (✕) button |
| DASH-REQ-020 | Table columns: Description, Carrier, Status, Expected Delivery |
| DASH-REQ-021 | Default sort: Expected Delivery ascending; active sort visually indicated |
| DASH-REQ-022 | Column header click toggles sort; sort persists in URL |
| DASH-REQ-023 | Entire row clickable → /deliveries/:id |
| DASH-REQ-024 | Tracking number shown as secondary text under description |
| DASH-REQ-025 | Expected date rendered by priority: timestamp_expected → date_expected_raw → "—" |
| DASH-REQ-026 | Relative date labels computed in browser's local timezone |
| DASH-REQ-027 | Pagination controls shown when pages > 1 |
| DASH-REQ-028 | Default page_size = 25 |
| DASH-REQ-029 | Page number persists in URL |
| DASH-REQ-030 | List auto-refreshes every 5 minutes; background refresh non-disruptive |
| DASH-REQ-031 | Manual refresh button invalidates TanStack Query cache immediately |
| DASH-REQ-032 | Initial page load shows skeleton rows, not blank screen |
| DASH-REQ-033 | Empty states for all conditions (no results, error, first sync) |
| DASH-REQ-034 | Detail header: description, tracking number, carrier, badge, expected date |
| DASH-REQ-035 | Status history as vertical timeline, oldest-to-newest |
| DASH-REQ-036 | Initial history entry labelled "First seen as:" |
| DASH-REQ-037 | Events log ordered by sequence_number ASC |
| DASH-REQ-038 | Empty events array shows "No tracking events recorded yet." |
| DASH-REQ-039 | Back link preserves list filter/sort/search state |
| DASH-REQ-040 | Detail auto-refreshes every 5 minutes |
| DASH-REQ-041 | Terminal delivery detail refresh extended to 30 minutes |
| DASH-REQ-042 | Badge colour by lifecycle_group; DELIVERED = green override |
| DASH-REQ-043 | Badge displays STATUS_DISPLAY label, not enum value or integer |
| DASH-REQ-044 | ATTENTION badges include warning icon |
| DASH-REQ-045 | AuthContext holds accessToken, isAuthenticated, login(), logout() |
| DASH-REQ-046 | Access token in-memory only; never written to localStorage or cookies |
| DASH-REQ-047 | Silent token refresh on app load; success = render app, failure = login |
| DASH-REQ-048 | Full-screen loading indicator during silent refresh (no login flash) |
| DASH-REQ-049 | Axios interceptor attaches Bearer token to all requests |
| DASH-REQ-050 | Axios interceptor auto-refreshes on 401; logout on refresh failure |
| DASH-REQ-051 | Logout: calls API, clears context, clears query cache, navigates to /login |
| DASH-REQ-052 | All data errors handled with user-friendly messages |
| DASH-REQ-053 | TanStack Query: 2 retries for data endpoints, 0 for auth |
| DASH-REQ-054 | Global error boundary with fallback UI |
| DASH-REQ-055 | Login form labels properly associated with inputs |
| DASH-REQ-056 | Status badges have screen-reader text alternative |
| DASH-REQ-057 | Table rows keyboard-navigable (role=button, Enter/Space) |
| DASH-REQ-058 | Page title updates on route change |
| DASH-REQ-059 | Primary target: desktop ≥ 1024px |
| DASH-REQ-060 | Card layout for viewport < 768px |

---

*Source: User scoping input, REST API requirements (05-rest-api.md), status normalization (04-status-normalization.md)*  
*Traceability: DASH-REQ-001 through DASH-REQ-060*
