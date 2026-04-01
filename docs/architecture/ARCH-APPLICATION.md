# Application Layer Design
## Delivery Tracking Web Service

**Document ID**: ARCH-APPLICATION  
**Status**: Draft  
**Addresses**: `03-polling-service.md`, `05-rest-api.md`, `07-auth-security.md`  
**Layer Mapping**: Layer 2 — Application

---

## Summary

The Application layer orchestrates domain logic to fulfil the service's use cases. It depends only on the Domain layer and defines every cross-boundary operation as a use case class with a single `execute()` method. This layer owns the DTOs (typed input/output contracts), application-level exceptions, and the high-level logic for polling, authentication, delivery queries, and system health — without importing SQLAlchemy, FastAPI, httpx, or APScheduler.

---

## 1. Layer Role and Rules

| Property | Value |
|----------|-------|
| Package | `app.application` |
| Depends on | `app.domain` only |
| Must NOT import | `sqlalchemy`, `fastapi`, `httpx`, `apscheduler` |
| May import | `app.domain.*`, `pydantic`, `abc`, `datetime`, `uuid`, Python stdlib |
| Testing | Mocked repository ABCs only; no database or HTTP client needed |

### Constructor Injection Pattern

Every use case receives its dependencies (repository interfaces and external service interfaces) via `__init__`. The presentation layer supplies the concrete implementations via `Depends()`. No use case reaches for a global or calls `get_db()` internally.

```python
class GetDeliveriesUseCase:
    def __init__(self, delivery_repo: AbstractDeliveryRepository):
        self._delivery_repo = delivery_repo

    async def execute(self, params: DeliveryFilterParams) -> DeliveryListDTO:
        ...
```

---

## 2. DTOs

DTOs (Data Transfer Objects) are Pydantic `BaseModel` subclasses that define the typed contracts between the application layer and its callers (presentation layer) or delegates (repository ABCs). They contain no SQLAlchemy metadata, no FastAPI-specific field info, and no ORM objects.

**File**: `app/application/dtos/`

---

### 2.1 Auth DTOs (`auth_dtos.py`)

```python
# ── Inputs ──────────────────────────────────────────────────────────────────

class LoginCredentialsDTO(BaseModel):
    username: str   # 1–100 chars
    password: str   # 1–200 chars (SecretStr in practice; cleared after hashing)


class RefreshTokenClaimsDTO(BaseModel):
    """Decoded, pre-validated claims from the refresh token cookie.
    JWT signature and expiry validation happens in the presentation layer
    before this DTO is constructed."""
    sub: str            # username
    token_version: int
    type: Literal["refresh"]


# ── Outputs ──────────────────────────────────────────────────────────────────

class AuthTokensDTO(BaseModel):
    """Issued on successful login. Presentation layer signs these into JWTs."""
    access_token_claims: AccessTokenClaimsDTO
    refresh_token_claims: RefreshTokenClaimsDTO


class AccessTokenClaimsDTO(BaseModel):
    """Claims payload for the access token (signed by presentation layer)."""
    sub: str
    type: Literal["access"] = "access"
    token_version: int
    # iat and exp are added by the presentation JWT-signing logic
```

---

### 2.2 Delivery DTOs (`delivery_dtos.py`)

```python
# ── Inputs ──────────────────────────────────────────────────────────────────

class DeliveryFilterParams(BaseModel):
    """Input contract for GET /deliveries (API-REQ-010 through API-REQ-012)."""
    page: int = 1                   # ≥ 1
    page_size: int = 20             # 1–100 (API-REQ-027)
    lifecycle_group: Optional[str] = None   # ACTIVE | ATTENTION | TERMINAL
    semantic_status: Optional[str] = None   # any SemanticStatus value
    carrier_code: Optional[str] = None
    search: Optional[str] = None    # max 200 chars; ILIKE on description + tracking_number
    sort_by: str = "timestamp_expected"
    sort_dir: str = "asc"           # asc | desc
    include_terminal: bool = False  # False = exclude TERMINAL lifecycle_group (API-REQ-010)


# ── Outputs ──────────────────────────────────────────────────────────────────

class DeliveryEventDTO(BaseModel):
    id: UUID
    event_description: str
    event_date_raw: str     # displayed verbatim; never parsed (DM-BR-009)
    location: Optional[str]
    additional_info: Optional[str]
    sequence_number: int
    recorded_at: datetime


class StatusHistoryEntryDTO(BaseModel):
    id: UUID
    previous_status_code: Optional[int]
    previous_semantic_status: Optional[str]
    new_status_code: int
    new_semantic_status: str
    detected_at: datetime


class DeliverySummaryDTO(BaseModel):
    """Output for GET /deliveries list items."""
    id: UUID
    tracking_number: str
    carrier_code: str
    description: str
    semantic_status: str
    lifecycle_group: str    # derived at serialisation; not stored (NORM-REQ-004)
    parcel_status_code: int
    date_expected_raw: Optional[str]
    date_expected_end_raw: Optional[str]
    timestamp_expected: Optional[datetime]
    timestamp_expected_end: Optional[datetime]
    first_seen_at: datetime
    last_seen_at: datetime
    updated_at: datetime


class DeliveryDetailDTO(DeliverySummaryDTO):
    """Output for GET /deliveries/{id} — extends summary with full history."""
    extra_information: Optional[str]
    events: list[DeliveryEventDTO]          # ordered by sequence_number ASC (API-REQ-014)
    status_history: list[StatusHistoryEntryDTO]  # ordered by detected_at ASC (API-REQ-014)


class DeliveryListDTO(BaseModel):
    """Paginated delivery list output."""
    items: list[DeliverySummaryDTO]
    total: int
    page: int
    page_size: int
    pages: int
```

---

### 2.3 System DTOs (`system_dtos.py`)

```python
class HealthDatabaseDTO(BaseModel):
    status: Literal["connected", "disconnected"]
    latency_ms: Optional[float]


class HealthPollingDTO(BaseModel):
    scheduler_running: bool
    last_poll_at: Optional[datetime]
    last_poll_outcome: Optional[str]
    last_successful_poll_at: Optional[datetime]
    consecutive_errors: int
    next_poll_at: Optional[datetime]   # from APScheduler; null if not running (API-REQ-018)


class HealthDTO(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    database: HealthDatabaseDTO
    polling: HealthPollingDTO
    version: str


class CarrierDTO(BaseModel):
    code: str
    name: str


class CarrierListDTO(BaseModel):
    carriers: list[CarrierDTO]
    cached_at: Optional[datetime]
    cache_status: Literal["fresh", "stale", "unavailable"]


# ── Polling internal DTOs ────────────────────────────────────────────────────

class ParcelDeliveryDTO(BaseModel):
    """
    Structured representation of a single delivery from the Parcel API response.
    Created by the infrastructure ParcelAPIClient; consumed by PollAndSyncUseCase.
    Lives in Application because the use case needs to understand its shape.
    """
    tracking_number: str
    carrier_code: str
    description: str
    extra_information: Optional[str]
    parcel_status_code: int
    date_expected_raw: Optional[str]
    date_expected_end_raw: Optional[str]
    timestamp_expected: Optional[datetime]
    timestamp_expected_end: Optional[datetime]
    events: list["ParcelEventDTO"]
    raw_response: dict   # full response for last_raw_response storage (DM-BR-004)


class ParcelEventDTO(BaseModel):
    event_description: str
    event_date_raw: str
    location: Optional[str]
    additional_info: Optional[str]
    sequence_number: int
```

---

## 3. External Service Interfaces

The application layer needs to call the Parcel API and query the APScheduler state, but it must not import `httpx` or `apscheduler`. It achieves this through abstract interfaces, implemented concretely in the infrastructure layer.

**File**: `app/application/services/` (or colocated with use cases)

```python
class AbstractParcelAPIClient(ABC):
    """Interface for calling the external Parcel App API."""

    @abstractmethod
    async def get_deliveries(self) -> list[ParcelDeliveryDTO]:
        """
        Call GET /external/deliveries/?filter_mode=recent.
        Returns parsed delivery list on success (POLL-REQ-011).
        Raises PollerAPIError subclasses on failure (mapped from HTTP status codes).
        """
        ...

    @abstractmethod
    async def get_carriers(self) -> list[CarrierDTO]:
        """
        Call GET /external/supported_carriers.json.
        Used by the carrier cache refresh task (API-REQ-019).
        """
        ...


class AbstractCarrierCache(ABC):
    """Interface for the in-memory carrier name cache."""

    @abstractmethod
    def get_carriers(self) -> CarrierListDTO:
        """Return the current cached carrier list (stale if TTL expired, API-REQ-020)."""
        ...

    @abstractmethod
    async def refresh(self) -> None:
        """Fetch carriers from Parcel API and update the cache."""
        ...


class AbstractSchedulerState(ABC):
    """Interface to query the APScheduler for health data (API-REQ-018)."""

    @abstractmethod
    def is_running(self) -> bool:
        ...

    @abstractmethod
    def get_next_poll_at(self) -> Optional[datetime]:
        """Return next scheduled fire time, or None if scheduler is not running."""
        ...
```

---

## 4. Use Cases

Each use case is a class in `app/application/use_cases/`. One module per use case. Single `async execute()` method. Returns a DTO or raises an application exception.

---

### 4.1 `AuthenticateUserUseCase`

**File**: `app/application/use_cases/auth/authenticate_user.py`  
**Triggers**: `POST /api/auth/login`

```
Purpose:
  Verify credentials and prepare token claims for issuance.

Dependencies (injected):
  - user_repo: AbstractUserRepository

Input:  LoginCredentialsDTO
Output: (User domain entity, int token_version)
        [Presentation layer creates JWTs from these]

Execution:
  1. user_repo.get_by_username(credentials.username)
  2. If user not found:
       → passlib dummy verify (constant-time, SEC-REQ-008)
       → raise InvalidCredentialsError
  3. passlib.verify(credentials.password, user.password_hash)
       → Fail: raise InvalidCredentialsError
  4. If not user.is_active: raise AccountDisabledError
  5. await user_repo.update_last_login(user.id)  (API-REQ-007)
  6. Return user entity (presentation layer reads user.token_version for JWT claims)
```

**Exceptions raised**: `InvalidCredentialsError`, `AccountDisabledError`

---

### 4.2 `RefreshAccessTokenUseCase`

**File**: `app/application/use_cases/auth/refresh_token.py`  
**Triggers**: `POST /api/auth/refresh`

```
Purpose:
  Validate the refresh token's user context and issue a new access token.
  JWT signature/expiry/type validation is done in the presentation layer BEFORE
  this use case is called.

Dependencies:
  - user_repo: AbstractUserRepository

Input:  RefreshTokenClaimsDTO (pre-decoded claims from presentation layer)
Output: User domain entity (presentation layer re-signs access token from user.token_version)

Execution:
  1. user_repo.get_by_username(claims.sub)
       → Not found: raise UserNotFoundError
  2. If not user.is_active: raise AccountDisabledError
  3. If user.token_version != claims.token_version: raise TokenVersionMismatchError (API-REQ-008)
  4. Return user entity
```

**Exceptions raised**: `UserNotFoundError`, `AccountDisabledError`, `TokenVersionMismatchError`

---

### 4.3 `LogoutUserUseCase`

**File**: `app/application/use_cases/auth/logout_user.py`  
**Triggers**: `POST /api/auth/logout`

```
Purpose:
  Increment token_version to immediately invalidate all outstanding tokens
  for the user (SEC-REQ-020, API-REQ-009).

Dependencies:
  - user_repo: AbstractUserRepository

Input:  int user_id
Output: None

Execution:
  1. user_repo.increment_token_version(user_id)  [atomic, SEC-REQ-021]
     → Failure propagates as infrastructure exception (DB error)
```

---

### 4.4 `GetDeliveriesUseCase`

**File**: `app/application/use_cases/deliveries/get_deliveries.py`  
**Triggers**: `GET /api/deliveries`

```
Purpose:
  Return a filtered, sorted, paginated list of deliveries with lifecycle_group derived.

Dependencies:
  - delivery_repo: AbstractDeliveryRepository

Input:  DeliveryFilterParams
Output: DeliveryListDTO

Execution:
  1. delivery_repo.list_filtered(params)
     → Returns (list[Delivery], total_count)
  2. For each Delivery, derive lifecycle_group:
       lifecycle_group = get_lifecycle_group(delivery.semantic_status)
  3. Map Delivery entities to DeliverySummaryDTO (including derived lifecycle_group)
  4. Compute pages = ceil(total / page_size)
  5. Return DeliveryListDTO(items, total, page, page_size, pages)

Notes:
  - include_terminal=False filter applied at repository query level (NORM-REQ-004)
  - search is passed through to repository as-is; repo handles parameterised LIKE
  - NULLs-last for timestamp_expected sort enforced at repository level (API-REQ-012)
```

---

### 4.5 `GetDeliveryDetailUseCase`

**File**: `app/application/use_cases/deliveries/get_delivery_detail.py`  
**Triggers**: `GET /api/deliveries/{delivery_id}`

```
Purpose:
  Return full delivery detail including events and status history.

Dependencies:
  - delivery_repo: AbstractDeliveryRepository

Input:  UUID delivery_id
Output: DeliveryDetailDTO

Execution:
  1. delivery_repo.get_by_id(delivery_id)
     → None: raise DeliveryNotFoundError(str(delivery_id))
  2. delivery_repo.get_events_for_delivery(delivery_id)
     → list[DeliveryEvent] ordered by sequence_number ASC
  3. delivery_repo.get_status_history_for_delivery(delivery_id)
     → list[StatusHistory] ordered by detected_at ASC
  4. Derive lifecycle_group = get_lifecycle_group(delivery.semantic_status)
  5. Map to DeliveryDetailDTO
     → events: list[DeliveryEventDTO]
     → status_history: list[StatusHistoryEntryDTO]

Notes:
  - Not paginated — all events and history returned in full (API-REQ-015)
  - Data volumes per delivery are bounded (design note in 05-rest-api.md)
```

**Exceptions raised**: `DeliveryNotFoundError`

---

### 4.6 `PollAndSyncUseCase`

**File**: `app/application/use_cases/polling/poll_and_sync.py`  
**Triggers**: APScheduler every 15 minutes ± 30s jitter; also cold-start (POLL-REQ-003)

This is the most complex use case. It orchestrates the entire polling cycle.

```
Purpose:
  Fetch deliveries from the Parcel API, diff against persisted state,
  and write all changes (new deliveries, status transitions, new events).

Dependencies:
  - delivery_repo: AbstractDeliveryRepository
  - poll_log_repo: AbstractPollLogRepository
  - parcel_client: AbstractParcelAPIClient

Input:  None (triggered by scheduler, not an HTTP request)
Output: PollLog (the completed log record; also written to DB)

Execution:

  PHASE 1 — Setup
  ├─ poll_log = poll_log_repo.create_in_progress(started_at=utcnow())
  │   [Creates record before API call; captures failures (DM-BR-018)]
  ├─ snapshot = delivery_repo.get_snapshot()
  │   [Single query; no N+1; in-memory map for O(1) lookups (POLL-REQ-015)]

  PHASE 2 — Parcel API Call (with retry logic)
  ├─ deliveries = await parcel_client.get_deliveries()
  │   Client raises:
  │   ├─ ParcelRateLimitError (HTTP 429)
  │   │   → log WARNING; complete poll with outcome=error; return
  │   ├─ ParcelAuthError (HTTP 401)
  │   │   → log CRITICAL; complete poll with outcome=error; return
  │   ├─ ParcelServerError (HTTP 5xx, network)
  │   │   → exponential backoff: 3 retries (15s, 60s, 120s) (POLL-REQ-026)
  │   │   → log WARNING per retry (POLL-REQ-027)
  │   │   → if all retries exhausted: complete poll with outcome=error; return
  │   └─ success: list[ParcelDeliveryDTO] (may be empty — valid, POLL-REQ-014)

  PHASE 3 — Change Detection (sequential, POLL-REQ-021)
  ├─ counters = {new=0, status_changes=0, new_events=0, errors=0}
  ├─ For each parcel_delivery in deliveries:
  │   ├─ Try (per-delivery transaction):
  │   │   ├─ semantic_status = normalize_status(parcel_delivery.parcel_status_code)
  │   │   │   [If UNKNOWN: log WARNING (POLL-REQ-023)]
  │   │   │
  │   │   ├─ Case: NEW delivery (tracking_number, carrier_code not in snapshot)
  │   │   │   ├─ INSERT Delivery (all fields, first_seen_at=now, last_seen_at=now)
  │   │   │   ├─ INSERT StatusHistory(prev=NULL, new=current_status)
  │   │   │   ├─ INSERT all events (ON CONFLICT DO NOTHING)
  │   │   │   └─ counters.new += 1
  │   │   │
  │   │   └─ Case: EXISTING delivery
  │   │       ├─ Status changed? (api_status != snapshot_status)
  │   │       │   ├─ Check for anomalous terminal transition → log WARNING if so
  │   │       │   ├─ INSERT StatusHistory(prev=old, new=new)
  │   │       │   └─ counters.status_changes += 1
  │   │       ├─ INSERT events ON CONFLICT DO NOTHING → count inserted rows
  │   │       │   counters.new_events += inserted_count
  │   │       └─ UPDATE Delivery (all mutable fields + last_seen_at=now, POLL-REQ-018)
  │   │
  │   └─ Except (per-delivery failure):
  │       ├─ Rollback delivery transaction
  │       ├─ log ERROR (tracking_number, carrier_code, error)
  │       └─ counters.errors += 1; continue to next delivery (POLL-REQ-029)

  PHASE 4 — Finalise (separate transaction, POLL-REQ-020)
  └─ outcome = 'success' if errors == 0 else 'partial'
      poll_log_repo.complete(poll_id, outcome, completed_at=now, counters)
```

**Error handling philosophy**: The use case itself is the retry coordinator. It calls `parcel_client.get_deliveries()` which may raise after exhausting its retries. The use case then marks the poll log and returns — it does not raise, ensuring the scheduler remains healthy.

**Transaction note**: Each delivery's Phase 3 operations run in a single async transaction supplied by the repository implementation. The Phase 4 PollLog update runs in a separate transaction. This boundary is enforced by the repository interface design — `create_in_progress()` and `complete()` each manage their own transaction scope.

---

### 4.7 `GetHealthUseCase`

**File**: `app/application/use_cases/system/get_health.py`  
**Triggers**: `GET /api/health` (unauthenticated)

```
Purpose:
  Aggregate service health data into a structured DTO for the health endpoint.

Dependencies:
  - poll_log_repo: AbstractPollLogRepository
  - db_health_checker: AbstractDBHealthChecker  [see §3 equivalent; simple ping]
  - scheduler_state: AbstractSchedulerState

Input:  None
Output: HealthDTO

Execution:
  1. [Concurrent, with 3s timeout each (API-REQ-016)]
     db_status = await db_health_checker.check()      → connected/disconnected + latency
     last_poll = await poll_log_repo.get_recent(1)[0]  → most recent PollLog
     last_success = await poll_log_repo.get_last_successful()
     consecutive_errors = await poll_log_repo.count_consecutive_errors()

  2. scheduler_running = scheduler_state.is_running()
     next_poll_at = scheduler_state.get_next_poll_at()

  3. Determine health status:
     ├─ 'unhealthy': db_status == 'disconnected' OR NOT scheduler_running
     ├─ 'degraded':  consecutive_errors >= 3  (POLL-REQ-036)
     └─ 'healthy':   otherwise

  4. Return HealthDTO
```

**Note on HTTP status**: Presentation layer returns 503 only for `unhealthy`; 200 for `healthy` and `degraded` (API-REQ-017).

---

### 4.8 `GetCarriersUseCase`

**File**: `app/application/use_cases/system/get_carriers.py`  
**Triggers**: `GET /api/carriers`

```
Purpose:
  Return the cached carrier code → name mapping. Never makes a synchronous
  outbound call (API-REQ-019).

Dependencies:
  - carrier_cache: AbstractCarrierCache

Input:  None
Output: CarrierListDTO

Execution:
  1. carrier_cache.get_carriers()
     → Returns CarrierListDTO with cache_status indicator
     → If never fetched: returns empty list with cache_status='unavailable' (API-REQ-020)
     → If stale (TTL expired): returns last data with cache_status='stale'
```

---

## 5. Application Exceptions

**File**: `app/application/exceptions.py`

Application exceptions represent **orchestration-level failures** — conditions discovered while executing a use case but not expressible as pure domain violations. They are mapped to HTTP status codes by the presentation layer.

```python
class ApplicationError(Exception):
    """Base class for all application exceptions."""
    pass


# ── Auth ─────────────────────────────────────────────────────────────────────

# (Re-exports of domain exceptions for clarity; application layer may raise these)
# InvalidCredentialsError, AccountDisabledError, TokenVersionMismatchError
# are defined in domain and re-raised here as-is.


# ── Polling ──────────────────────────────────────────────────────────────────

class ParcelAPIError(ApplicationError):
    """Base for all Parcel API call failures."""
    pass


class ParcelRateLimitError(ParcelAPIError):
    """HTTP 429 from Parcel API (POLL-REQ-024)."""
    pass


class ParcelAuthError(ParcelAPIError):
    """HTTP 401 from Parcel API — API key invalid (POLL-REQ-025)."""
    pass


class ParcelServerError(ParcelAPIError):
    """HTTP 5xx or network error; subject to retry (POLL-REQ-026)."""
    def __init__(self, status_code: Optional[int], message: str):
        super().__init__(message)
        self.status_code = status_code


class ParcelResponseError(ParcelAPIError):
    """Parcel API returned success=false with an error_message."""
    def __init__(self, error_message: str):
        super().__init__(error_message)


# ── System ───────────────────────────────────────────────────────────────────

class DatabaseUnavailableError(ApplicationError):
    """
    Database is unreachable during a poll cycle (POLL-REQ-031).
    Poll is aborted; no Parcel API call is made.
    """
    pass
```

**Presentation mapping** (defined in the presentation layer, not here):

| Application/Domain Exception | HTTP Status | Error Code |
|------------------------------|-------------|------------|
| `InvalidCredentialsError` | 401 | `INVALID_CREDENTIALS` |
| `AccountDisabledError` | 403 | `ACCOUNT_DISABLED` |
| `TokenVersionMismatchError` | 401 | `UNAUTHORIZED` |
| `UserNotFoundError` | 401 | `UNAUTHORIZED` (masked; SEC-REQ-016) |
| `DeliveryNotFoundError` | 404 | `NOT_FOUND` |
| `DatabaseUnavailableError` | 503 | `SERVICE_UNAVAILABLE` |
| Unhandled `ApplicationError` | 500 | `INTERNAL_ERROR` |

---

## 6. Responsibility Matrix

| Use Case | Repo ABCs Used | External ABCs | Raises |
|----------|----------------|---------------|--------|
| `AuthenticateUserUseCase` | `AbstractUserRepository` | — | `InvalidCredentialsError`, `AccountDisabledError` |
| `RefreshAccessTokenUseCase` | `AbstractUserRepository` | — | `UserNotFoundError`, `AccountDisabledError`, `TokenVersionMismatchError` |
| `LogoutUserUseCase` | `AbstractUserRepository` | — | DB errors (propagate) |
| `GetDeliveriesUseCase` | `AbstractDeliveryRepository` | — | — |
| `GetDeliveryDetailUseCase` | `AbstractDeliveryRepository` | — | `DeliveryNotFoundError` |
| `PollAndSyncUseCase` | `AbstractDeliveryRepository`, `AbstractPollLogRepository` | `AbstractParcelAPIClient` | Never raises (all errors logged + PollLog updated) |
| `GetHealthUseCase` | `AbstractPollLogRepository` | `AbstractSchedulerState` | Never raises (returns unhealthy DTO on failure) |
| `GetCarriersUseCase` | — | `AbstractCarrierCache` | Never raises (returns unavailable DTO on failure) |

---

## 7. Testing Notes

Application use case tests mock the repository ABCs and external service ABCs with in-memory implementations. No database fixture is needed.

**Priority test cases**:

| Use Case | Key Test Scenarios |
|----------|--------------------|
| `AuthenticateUserUseCase` | Unknown user (dummy verify fires), wrong password, disabled account |
| `PollAndSyncUseCase` | New delivery, status change, duplicate event (no-op), 429 skip, 401 skip, partial delivery failure |
| `GetDeliveriesUseCase` | include_terminal filter, NULL-last sort, search filter, page beyond total → empty list |
| `GetHealthUseCase` | consecutive_errors=3 → degraded, DB unavailable → unhealthy |
| `LogoutUserUseCase` | token_version incremented atomically |

---

*Requirements traceability: POLL-REQ-003–036, API-REQ-001–028, SEC-REQ-007–008, SEC-REQ-015–021, NORM-REQ-003–006, NORM-REQ-010–012*  
*Produced from: `03-polling-service.md`, `05-rest-api.md`, `07-auth-security.md`, `04-status-normalization.md`*
