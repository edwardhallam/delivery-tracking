# Domain Layer Design
## Delivery Tracking Web Service

**Document ID**: ARCH-DOMAIN  
**Status**: Draft  
**Addresses**: `02-data-model.md`, `04-status-normalization.md`  
**Layer Mapping**: Layer 1 — Domain (innermost)

---

## Summary

The Domain layer is the innermost layer of the Clean Architecture stack. It contains the business concepts of the Delivery Tracking Service expressed as pure Python: entities, value objects, repository interfaces, and domain exceptions. This layer has **zero external framework dependencies** — no SQLAlchemy, no FastAPI, no httpx, no APScheduler. It is independently importable and fully testable with plain `pytest`.

---

## 1. Layer Role and Rules

| Property | Value |
|----------|-------|
| Package | `app.domain` |
| Depends on | Nothing outside itself |
| Must NOT import | `sqlalchemy`, `fastapi`, `httpx`, `apscheduler`, `pydantic` (BaseModel only) |
| May import | Python stdlib, `pydantic.BaseModel` (for entity validation), `abc`, `enum`, `uuid`, `datetime` |
| Testing | No database, no HTTP client, no framework needed |

> **Pydantic exception**: Domain entities may use `pydantic.BaseModel` or `@dataclass` for validation and serialisation convenience, provided the models carry no SQLAlchemy decorators or FastAPI-specific field metadata. Pydantic is a data-description library, not a framework dependency.

---

## 2. Entities

Entities are the core business objects. Each entity maps to a database table but is **not** a SQLAlchemy model — ORM concerns live exclusively in the infrastructure layer. Mappers translate between the two representations.

All entities use Python `dataclasses` or `pydantic.BaseModel`. UUIDs are represented as `uuid.UUID`; timestamps as `datetime` (timezone-aware, UTC). Optional fields use `Optional[T]` with a `None` default.

---

### 2.1 `Delivery`

**File**: `app/domain/entities/delivery.py`  
**Table**: `deliveries`  
**Business key**: `(tracking_number, carrier_code)`

Represents a single tracked parcel. One record per unique carrier+tracking pair. Records are never hard-deleted (DM-BR-005).

```python
@dataclass
class Delivery:
    id: UUID
    tracking_number: str           # max 255 chars
    carrier_code: str              # max 50 chars
    description: str               # max 500 chars; user label from Parcel
    extra_information: Optional[str]   # max 500 chars; nullable
    parcel_status_code: int        # raw Parcel integer, 0–8 (or UNKNOWN)
    semantic_status: SemanticStatus
    date_expected_raw: Optional[str]       # max 50 chars; timezone-naive; display as-is
    date_expected_end_raw: Optional[str]   # max 50 chars; nullable
    timestamp_expected: Optional[datetime]     # UTC TIMESTAMPTZ; preferred for sorting
    timestamp_expected_end: Optional[datetime] # UTC TIMESTAMPTZ; nullable
    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime
    last_raw_response: Optional[dict]  # most recent Parcel API JSON; not history
```

**Key invariants**:
- `timestamp_expected` takes precedence over `date_expected_raw` for any temporal ordering (DM-BR-024)
- `last_raw_response` is overwritten on every poll; it is not a history field (DM-BR-004)
- `semantic_status` is always consistent with `parcel_status_code` as mapped by `normalize_status()` (DM-BR-021)

---

### 2.2 `DeliveryEvent`

**File**: `app/domain/entities/delivery_event.py`  
**Table**: `delivery_events`

A single carrier scan or tracking event. Events are append-only — never updated or deleted (DM-BR-006). Deduplication uses the `(delivery_id, event_description, event_date_raw)` fingerprint (DM-BR-007).

```python
@dataclass
class DeliveryEvent:
    id: UUID
    delivery_id: UUID
    event_description: str     # TEXT; not null
    event_date_raw: str        # max 50 chars; timezone-naive; stored verbatim (DM-BR-009)
    location: Optional[str]    # max 255 chars
    additional_info: Optional[str]  # TEXT; nullable
    sequence_number: int       # API array index; 0 = oldest (DM-BR-008)
    recorded_at: datetime
```

**Key invariants**:
- `event_date_raw` is **never parsed** into a timestamp — stored and displayed as a raw string (DM-BR-025)
- `sequence_number` reflects API array order and is used for stable display ordering (API-REQ-014)

---

### 2.3 `StatusHistory`

**File**: `app/domain/entities/status_history.py`  
**Table**: `status_history`

Immutable audit log of every detected status transition. One entry is written at delivery creation (`previous_*` = NULL) and one for each subsequent status change (DM-BR-010, DM-BR-011). Records are never modified (DM-BR-012).

```python
@dataclass
class StatusHistory:
    id: UUID
    delivery_id: UUID
    previous_status_code: Optional[int]            # NULL for initial entry
    previous_semantic_status: Optional[SemanticStatus]  # NULL for initial entry
    new_status_code: int
    new_semantic_status: SemanticStatus
    detected_at: datetime    # poller detection time; not carrier-side time (DM-BR-013)
    poll_log_id: Optional[UUID]   # FK to PollLog; nullable
```

**Key invariants**:
- `detected_at` is the system's detection timestamp — carriers do not provide when a status changed (DM-BR-013)
- Both the raw code and semantic status are stored at write time and are never retroactively changed (NORM-REQ-009)

---

### 2.4 `User`

**File**: `app/domain/entities/user.py`  
**Table**: `users`

Single-user credentials. The table schema supports multiple rows for future multi-user expansion without schema change, but exactly one record is expected in production (DM-BR-015).

```python
@dataclass
class User:
    id: int                        # GENERATED ALWAYS AS IDENTITY
    username: str                  # max 100 chars; case-sensitive (SEC-REQ-007)
    password_hash: str             # bcrypt hash, cost ≥ 12; never plaintext (DM-BR-014)
    created_at: datetime
    last_login_at: Optional[datetime]
    is_active: bool                # False prevents login; never delete (DM-BR-016, DM-BR-017)
    token_version: int             # Incremented on logout; invalidates all outstanding tokens
                                   # (SEC-REQ-020; see GAP-001 in ARCH-OVERVIEW.md)
```

**Key invariants**:
- `password_hash` is excluded from all serialisation paths — never appears in API responses (API-REQ-024)
- `token_version` is validated server-side on every authenticated request (SEC-REQ-017, API-REQ-004)
- `is_active = False` is the only supported "removal" mechanism — records are never hard-deleted (DM-BR-017)

---

### 2.5 `PollLog`

**File**: `app/domain/entities/poll_log.py`  
**Table**: `poll_logs`

Operational record of every Parcel API poll cycle. Created at cycle start (before the API call) so that even hard failures produce a record (DM-BR-018). Retained indefinitely (DM-BR-020).

```python
@dataclass
class PollLog:
    id: UUID
    started_at: datetime
    completed_at: Optional[datetime]   # NULL = still in progress or hard-interrupted (DM-BR-019)
    outcome: PollOutcome               # 'success' | 'partial' | 'error' | 'in_progress'
    deliveries_fetched: Optional[int]
    new_deliveries: Optional[int]
    status_changes: Optional[int]
    new_events: Optional[int]
    error_message: Optional[str]
```

```python
class PollOutcome(str, Enum):
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    PARTIAL = "partial"      # some deliveries processed; some failed (POLL-REQ-030)
    ERROR = "error"
```

---

## 3. Value Objects

Value objects are immutable typed wrappers around primitive values. They capture domain invariants in the type system and carry no identity — two instances with the same value are equal.

---

### 3.1 `SemanticStatus`

**File**: `app/domain/value_objects/semantic_status.py`

The canonical, stable representation of delivery status. The single source of truth for the status-code-to-semantic mapping (NORM-REQ-010).

```python
class SemanticStatus(str, Enum):
    INFO_RECEIVED    = "INFO_RECEIVED"
    IN_TRANSIT       = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    AWAITING_PICKUP  = "AWAITING_PICKUP"
    DELIVERED        = "DELIVERED"
    DELIVERY_FAILED  = "DELIVERY_FAILED"
    EXCEPTION        = "EXCEPTION"
    NOT_FOUND        = "NOT_FOUND"
    FROZEN           = "FROZEN"
    UNKNOWN          = "UNKNOWN"    # sentinel for unrecognised Parcel codes


PARCEL_CODE_TO_SEMANTIC: dict[int, SemanticStatus] = {
    0: SemanticStatus.DELIVERED,
    1: SemanticStatus.FROZEN,
    2: SemanticStatus.IN_TRANSIT,
    3: SemanticStatus.AWAITING_PICKUP,
    4: SemanticStatus.OUT_FOR_DELIVERY,
    5: SemanticStatus.NOT_FOUND,
    6: SemanticStatus.DELIVERY_FAILED,
    7: SemanticStatus.EXCEPTION,
    8: SemanticStatus.INFO_RECEIVED,
}


def normalize_status(parcel_code: int) -> SemanticStatus:
    """
    Map a Parcel integer status code to SemanticStatus.

    Returns SemanticStatus.UNKNOWN for any unrecognised code.
    Never raises an exception for any integer input (NORM-REQ-010).
    Requires 100% branch coverage in tests (NORM-REQ-012).
    """
    return PARCEL_CODE_TO_SEMANTIC.get(parcel_code, SemanticStatus.UNKNOWN)
```

**Invariants**:
- `normalize_status()` never raises — all integers are valid inputs; unknowns map to `UNKNOWN` (NORM-REQ-010)
- The mapping table (`PARCEL_CODE_TO_SEMANTIC`) is the authoritative, exhaustive mapping — no other translation path exists

---

### 3.2 `LifecycleGroup`

**File**: `app/domain/value_objects/lifecycle_group.py`

Groups `SemanticStatus` values into three operational categories. Used for dashboard filtering and badge colouring. **Never stored in the database** — always derived at runtime (NORM-REQ-004).

```python
class LifecycleGroup(str, Enum):
    ACTIVE    = "ACTIVE"     # IN_TRANSIT, AWAITING_PICKUP, OUT_FOR_DELIVERY, INFO_RECEIVED
    ATTENTION = "ATTENTION"  # NOT_FOUND, DELIVERY_FAILED, EXCEPTION, UNKNOWN
    TERMINAL  = "TERMINAL"   # DELIVERED, FROZEN


SEMANTIC_TO_LIFECYCLE: dict[SemanticStatus, LifecycleGroup] = {
    SemanticStatus.INFO_RECEIVED:    LifecycleGroup.ACTIVE,
    SemanticStatus.IN_TRANSIT:       LifecycleGroup.ACTIVE,
    SemanticStatus.OUT_FOR_DELIVERY: LifecycleGroup.ACTIVE,
    SemanticStatus.AWAITING_PICKUP:  LifecycleGroup.ACTIVE,
    SemanticStatus.DELIVERED:        LifecycleGroup.TERMINAL,
    SemanticStatus.FROZEN:           LifecycleGroup.TERMINAL,
    SemanticStatus.DELIVERY_FAILED:  LifecycleGroup.ATTENTION,
    SemanticStatus.EXCEPTION:        LifecycleGroup.ATTENTION,
    SemanticStatus.NOT_FOUND:        LifecycleGroup.ATTENTION,
    SemanticStatus.UNKNOWN:          LifecycleGroup.ATTENTION,
}


def get_lifecycle_group(status: SemanticStatus) -> LifecycleGroup:
    """
    Return the LifecycleGroup for a given SemanticStatus.
    UNKNOWN maps to ATTENTION.
    Never raises for any SemanticStatus value (NORM-REQ-011).
    Requires 100% branch coverage in tests (NORM-REQ-012).
    """
    return SEMANTIC_TO_LIFECYCLE.get(status, LifecycleGroup.ATTENTION)
```

**Invariants**:
- `get_lifecycle_group()` never raises — all `SemanticStatus` values including `UNKNOWN` have a defined group (NORM-REQ-011)
- Both `normalize_status()` and `get_lifecycle_group()` require 100% branch coverage (NORM-REQ-012)

---

## 4. Repository Interfaces

Repository interfaces define the **persistence contract** in domain terms. They are abstract base classes (`abc.ABC`). The domain layer uses these; the infrastructure layer implements them; the presentation layer wires them together.

No repository interface imports SQLAlchemy, psycopg, or any persistence technology. All parameters and return types are domain entities or Python primitives.

---

### 4.1 `AbstractDeliveryRepository`

**File**: `app/domain/repositories/abstract_delivery_repository.py`

```python
class AbstractDeliveryRepository(ABC):

    @abstractmethod
    async def get_snapshot(self) -> dict[tuple[str, str], UUID]:
        """
        Return a dict keyed by (tracking_number, carrier_code) → delivery_id
        for all persisted deliveries. Used by the poller for O(1) existence checks.
        Single query; no N+1 pattern (POLL-REQ-015).
        """
        ...

    @abstractmethod
    async def get_by_id(self, delivery_id: UUID) -> Optional[Delivery]:
        """Return a Delivery by its internal UUID, or None if not found."""
        ...

    @abstractmethod
    async def list_filtered(self, filter_params: DeliveryFilterParams) -> tuple[list[Delivery], int]:
        """
        Return a page of deliveries matching filter_params and the total count.
        Supports: lifecycle_group, semantic_status, carrier_code, search (ILIKE),
                  sort_by, sort_dir, include_terminal, page, page_size.
        NULLs-last for timestamp_expected sort (API-REQ-012).
        search is parameterised LIKE; no string interpolation (SEC-REQ-058).
        """
        ...

    @abstractmethod
    async def create(self, delivery: Delivery) -> Delivery:
        """Insert a new Delivery record. Returns the created entity."""
        ...

    @abstractmethod
    async def update(self, delivery: Delivery) -> Delivery:
        """
        Update a Delivery record (upsert mutable fields).
        Always updates last_seen_at and updated_at (POLL-REQ-018).
        """
        ...

    @abstractmethod
    async def create_event(self, event: DeliveryEvent) -> Optional[DeliveryEvent]:
        """
        Insert a DeliveryEvent. Returns None if the fingerprint already exists
        (ON CONFLICT DO NOTHING — DM-BR-007).
        """
        ...

    @abstractmethod
    async def get_events_for_delivery(self, delivery_id: UUID) -> list[DeliveryEvent]:
        """Return all events for a delivery ordered by sequence_number ASC (API-REQ-014)."""
        ...

    @abstractmethod
    async def create_status_history(self, entry: StatusHistory) -> StatusHistory:
        """Append a StatusHistory record. History entries are never updated (DM-BR-012)."""
        ...

    @abstractmethod
    async def get_status_history_for_delivery(self, delivery_id: UUID) -> list[StatusHistory]:
        """Return all status history entries ordered by detected_at ASC (API-REQ-014)."""
        ...
```

---

### 4.2 `AbstractUserRepository`

**File**: `app/domain/repositories/abstract_user_repository.py`

```python
class AbstractUserRepository(ABC):

    @abstractmethod
    async def get_by_username(self, username: str) -> Optional[User]:
        """
        Return a User by username (case-sensitive, SEC-REQ-007), or None.
        Used by login and token validation paths.
        """
        ...

    @abstractmethod
    async def get_by_id(self, user_id: int) -> Optional[User]:
        """Return a User by internal integer ID, or None."""
        ...

    @abstractmethod
    async def update_last_login(self, user_id: int) -> None:
        """Update last_login_at to UTC now. Called on successful authentication (API-REQ-007)."""
        ...

    @abstractmethod
    async def increment_token_version(self, user_id: int) -> int:
        """
        Atomically increment token_version and return the new value.
        UPDATE users SET token_version = token_version + 1 WHERE id = :id
        Atomic operation (SEC-REQ-021). Called on logout (SEC-REQ-020).
        """
        ...

    @abstractmethod
    async def get_user_count(self) -> int:
        """Return total number of User records. Used by seed script (DM-MIG-004)."""
        ...

    @abstractmethod
    async def create(self, user: User) -> User:
        """Insert a new User record. Used by seed script only."""
        ...
```

---

### 4.3 `AbstractPollLogRepository`

**File**: `app/domain/repositories/abstract_poll_log_repository.py`

```python
class AbstractPollLogRepository(ABC):

    @abstractmethod
    async def create_in_progress(self, started_at: datetime) -> PollLog:
        """
        INSERT a PollLog with outcome='in_progress' and completed_at=NULL.
        Called at the START of every poll cycle, before the Parcel API call (DM-BR-018).
        """
        ...

    @abstractmethod
    async def complete(
        self,
        poll_id: UUID,
        outcome: PollOutcome,
        completed_at: datetime,
        deliveries_fetched: Optional[int],
        new_deliveries: Optional[int],
        status_changes: Optional[int],
        new_events: Optional[int],
        error_message: Optional[str],
    ) -> PollLog:
        """
        Update PollLog outcome and counters after all deliveries are processed.
        Executed in a separate transaction from delivery processing (POLL-REQ-020).
        """
        ...

    @abstractmethod
    async def get_recent(self, limit: int = 10) -> list[PollLog]:
        """Return the most recent N poll logs ordered by started_at DESC."""
        ...

    @abstractmethod
    async def get_last_successful(self) -> Optional[PollLog]:
        """Return the most recent PollLog with outcome='success', or None."""
        ...

    @abstractmethod
    async def count_consecutive_errors(self) -> int:
        """
        Count the number of consecutive error/partial outcomes from most recent
        backwards, stopping at the first success. Used for health degradation check
        (POLL-REQ-036: consecutive_errors >= 3 triggers degraded health status).
        """
        ...
```

---

## 5. Domain Exceptions

**File**: `app/domain/exceptions.py`

Domain exceptions represent **business rule violations** — conditions that are invalid within the domain model regardless of the delivery mechanism. They are pure Python exceptions with no HTTP status codes.

```python
class DomainError(Exception):
    """Base class for all domain exceptions."""
    pass


class DeliveryNotFoundError(DomainError):
    """No Delivery exists with the given ID or business key."""
    def __init__(self, identifier: str):
        super().__init__(f"Delivery not found: {identifier}")
        self.identifier = identifier


class UserNotFoundError(DomainError):
    """No User exists with the given username or ID."""
    def __init__(self, identifier: str):
        super().__init__(f"User not found: {identifier}")
        self.identifier = identifier


class InvalidCredentialsError(DomainError):
    """
    Authentication failed — username not found or password incorrect.
    The error message is intentionally generic to prevent username enumeration
    (API-REQ-006, SEC-REQ-008).
    """
    pass


class AccountDisabledError(DomainError):
    """User account exists but is_active == False (DM-BR-016)."""
    pass


class TokenVersionMismatchError(DomainError):
    """
    JWT token_version claim does not match the current users.token_version.
    The token has been invalidated by a logout or key rotation (SEC-REQ-017).
    """
    pass


class InvalidStatusCodeError(DomainError):
    """
    A Parcel status code outside 0–8 was encountered.
    The service records UNKNOWN and logs a WARNING; it does not raise this
    exception during normal operation. Reserved for explicit validation paths.
    """
    def __init__(self, code: int):
        super().__init__(f"Unrecognised Parcel status code: {code}")
        self.code = code


class AnomalousStatusTransitionError(DomainError):
    """
    A terminal-state delivery received a non-terminal status update (NORM-REQ-005).
    Raised by transition-validation logic; caught and logged as WARNING.
    The transition is still persisted (NORM-REQ-006).
    """
    def __init__(self, tracking_number: str, from_status: SemanticStatus, to_status: SemanticStatus):
        super().__init__(
            f"Anomalous transition from terminal state: "
            f"{tracking_number} {from_status} → {to_status}"
        )
        self.tracking_number = tracking_number
        self.from_status = from_status
        self.to_status = to_status
```

---

## 6. Domain Invariants Summary

The following invariants are enforced at the domain layer level — not at the database or API level:

| Invariant | Entity | Source |
|-----------|--------|--------|
| `normalize_status()` never raises | `SemanticStatus` | NORM-REQ-010 |
| `get_lifecycle_group()` never raises | `LifecycleGroup` | NORM-REQ-011 |
| `event_date_raw` is never parsed to timestamp | `DeliveryEvent` | DM-BR-009, DM-BR-025 |
| `date_expected_raw` is never parsed to timestamp | `Delivery` | DM-BR-025 |
| `password_hash` is always a bcrypt hash, never plaintext | `User` | DM-BR-014 |
| `token_version` is always a positive integer | `User` | SEC-REQ-020 |
| `StatusHistory` entries are never modified after creation | `StatusHistory` | DM-BR-012 |
| `PollOutcome.IN_PROGRESS` → `completed_at` is None | `PollLog` | DM-BR-018, DM-BR-019 |
| Anomalous terminal transitions logged but not rejected | `Delivery` | NORM-REQ-005, NORM-REQ-006 |

---

## 7. Testing Notes

Domain tests require no fixtures, no database, and no HTTP server. A `tests/unit/domain/` directory is sufficient:

| Test Target | Test Type | What to Mock |
|-------------|-----------|--------------|
| `normalize_status()` | Parametrized unit test (0–8 + unknown) | Nothing |
| `get_lifecycle_group()` | Parametrized unit test (all SemanticStatus values) | Nothing |
| Domain exception construction | Unit test | Nothing |
| `Delivery` / `User` / `StatusHistory` instantiation | Unit test | Nothing |

Both normalisation functions require **100% branch coverage** (NORM-REQ-012). This is verifiable with `pytest --cov=app.domain.value_objects --cov-branch`.

---

*Requirements traceability: DM-BR-001–026, DM-MIG-001–004, NORM-REQ-001–014, SEC-REQ-007–008, SEC-REQ-017–021, API-REQ-004–006, API-REQ-014*  
*Produced from: `02-data-model.md`, `04-status-normalization.md`, `05-rest-api.md`, `07-auth-security.md`*
