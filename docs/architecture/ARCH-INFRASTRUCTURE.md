# Infrastructure Layer Design
## Delivery Tracking Web Service

**Document ID**: ARCH-INFRASTRUCTURE  
**Status**: Draft  
**Addresses**: `02-data-model.md`, `03-polling-service.md`, `05-rest-api.md`, `08-deployment.md`  
**Layer Mapping**: Layer 3 — Infrastructure

---

## Summary

The Infrastructure layer contains all concrete adapters: SQLAlchemy ORM models, repository implementations, domain-to-ORM mappers, the httpx Parcel API client, the in-memory carrier cache, and the APScheduler polling integration. This layer implements the abstract interfaces defined by the domain and application layers. It is the only layer that imports SQLAlchemy, httpx, and APScheduler.

---

## 1. Layer Role and Rules

| Property | Value |
|----------|-------|
| Package | `app.infrastructure` |
| Depends on | `app.domain`, `app.application` |
| Must NOT import | `fastapi`, `app.presentation.*` |
| May import | `sqlalchemy`, `httpx`, `apscheduler`, `passlib`, `jose`, Python stdlib |
| Testing | Requires a test database (integration) or thorough mocking of SQLAlchemy sessions |

---

## 2. Database Setup

**File**: `app/infrastructure/database/engine.py`

### 2.1 Async Engine and Session Factory

```python
# SQLAlchemy 2.0 async engine + session factory
engine = create_async_engine(
    settings.database_url,
    echo=settings.environment == "development",
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,   # validate connections on checkout
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,   # prevent lazy-load errors after commit
    autocommit=False,
    autoflush=False,
)
```

**`pool_pre_ping=True`** is required to detect stale connections after PostgreSQL restarts, which is common in Docker Compose environments.

**`expire_on_commit=False`** is required because async SQLAlchemy cannot lazy-load expired attributes outside a session context. Entities returned from committed transactions must remain accessible.

### 2.2 Session Dependency

```python
async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

This is used by the FastAPI `Depends()` DI chain in the presentation layer. The polling use case uses sessions differently — see §6.

### 2.3 Alembic Configuration

**File**: `alembic/env.py`

Alembic uses the **synchronous** version of the database URL (psycopg, not async psycopg) for migration execution, or uses SQLAlchemy's async-safe migration pattern:

```python
# alembic/env.py
def run_migrations_online():
    connectable = create_engine(settings.sync_database_url)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
```

All schema changes are via Alembic revision files — direct `ALTER TABLE` is prohibited (DM-MIG-001).

---

## 3. ORM Models

**Package**: `app/infrastructure/database/models/`

All ORM models use **SQLAlchemy 2.0 `MappedColumn` syntax** with the `DeclarativeBase` pattern. They share a common `Base` class defined in `app/infrastructure/database/models/__init__.py`.

ORM models and domain entities are **separate classes**. They share the same conceptual shape but ORM models carry SQLAlchemy column metadata, relationship declarations, and table constraints. Mappers translate between them.

### 3.1 `DeliveryORM`

**File**: `app/infrastructure/database/models/delivery_orm.py`

```python
class DeliveryORM(Base):
    __tablename__ = "deliveries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tracking_number: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    carrier_code: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    description: Mapped[str] = mapped_column(VARCHAR(500), nullable=False, default="")
    extra_information: Mapped[Optional[str]] = mapped_column(VARCHAR(500))
    parcel_status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    semantic_status: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    date_expected_raw: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    date_expected_end_raw: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    timestamp_expected: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    timestamp_expected_end: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    first_seen_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=utcnow)
    last_raw_response: Mapped[Optional[dict]] = mapped_column(JSONB)

    # Relationships (lazy="raise" enforces explicit loading; no N+1 by accident)
    events: Mapped[list["DeliveryEventORM"]] = relationship(lazy="raise")
    status_history: Mapped[list["StatusHistoryORM"]] = relationship(lazy="raise")

    __table_args__ = (
        UniqueConstraint("tracking_number", "carrier_code", name="uq_delivery_tracking"),
        Index("idx_delivery_semantic_status", "semantic_status"),
        Index("idx_delivery_timestamp_expected", "timestamp_expected",
              postgresql_nulls_last=True),
        Index("idx_delivery_last_seen", "last_seen_at", postgresql_using="btree"),
        Index("idx_delivery_updated_at", "updated_at"),
    )
```

### 3.2 `DeliveryEventORM`

**File**: `app/infrastructure/database/models/delivery_event_orm.py`

```python
class DeliveryEventORM(Base):
    __tablename__ = "delivery_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    delivery_id: Mapped[UUID] = mapped_column(ForeignKey("deliveries.id"), nullable=False)
    event_description: Mapped[str] = mapped_column(Text, nullable=False)
    event_date_raw: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(VARCHAR(255))
    additional_info: Mapped[Optional[str]] = mapped_column(Text)
    sequence_number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=utcnow)

    __table_args__ = (
        # Deduplication fingerprint (DM-BR-007)
        UniqueConstraint(
            "delivery_id", "event_description", "event_date_raw",
            name="uq_event_fingerprint"
        ),
        Index("idx_event_delivery_seq", "delivery_id", "sequence_number"),
    )
```

### 3.3 `StatusHistoryORM`

**File**: `app/infrastructure/database/models/status_history_orm.py`

```python
class StatusHistoryORM(Base):
    __tablename__ = "status_history"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    delivery_id: Mapped[UUID] = mapped_column(ForeignKey("deliveries.id"), nullable=False)
    previous_status_code: Mapped[Optional[int]] = mapped_column(SmallInteger)
    previous_semantic_status: Mapped[Optional[str]] = mapped_column(VARCHAR(50))
    new_status_code: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    new_semantic_status: Mapped[str] = mapped_column(VARCHAR(50), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=utcnow)
    poll_log_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("poll_logs.id"))

    __table_args__ = (
        Index("idx_status_history_delivery", "delivery_id", "detected_at"),
        Index("idx_status_history_detected_at", "detected_at"),
    )
```

### 3.4 `UserORM`

**File**: `app/infrastructure/database/models/user_orm.py`

```python
class UserORM(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(VARCHAR(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(VARCHAR(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=utcnow)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # GAP-001: token_version not in 02-data-model.md; added per 05-rest-api.md §2

    __table_args__ = (
        Index("uq_user_username", "username", unique=True),
    )
```

### 3.5 `PollLogORM`

**File**: `app/infrastructure/database/models/poll_log_orm.py`

```python
class PollLogORM(Base):
    __tablename__ = "poll_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    started_at: Mapped[datetime] = mapped_column(TIMESTAMPTZ, nullable=False, default=utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMPTZ)
    outcome: Mapped[str] = mapped_column(VARCHAR(20), nullable=False)
    deliveries_fetched: Mapped[Optional[int]] = mapped_column(Integer)
    new_deliveries: Mapped[Optional[int]] = mapped_column(Integer)
    status_changes: Mapped[Optional[int]] = mapped_column(Integer)
    new_events: Mapped[Optional[int]] = mapped_column(Integer)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("outcome IN ('in_progress','success','partial','error')",
                        name="ck_poll_log_outcome"),
        Index("idx_poll_log_started_at", "started_at"),
        Index("idx_poll_log_outcome", "outcome"),
    )
```

---

## 4. Mappers

**Package**: `app/infrastructure/mappers/`

Each mapper module provides two static methods: `to_domain()` converts an ORM row to a domain entity; `to_orm()` converts a domain entity to an ORM model for persistence. They are the **only** code that crosses the ORM/entity boundary.

```python
# app/infrastructure/mappers/delivery_mapper.py

class DeliveryMapper:
    @staticmethod
    def to_domain(orm: DeliveryORM) -> Delivery:
        return Delivery(
            id=orm.id,
            tracking_number=orm.tracking_number,
            carrier_code=orm.carrier_code,
            description=orm.description,
            extra_information=orm.extra_information,
            parcel_status_code=orm.parcel_status_code,
            semantic_status=SemanticStatus(orm.semantic_status),
            date_expected_raw=orm.date_expected_raw,
            date_expected_end_raw=orm.date_expected_end_raw,
            timestamp_expected=orm.timestamp_expected,
            timestamp_expected_end=orm.timestamp_expected_end,
            first_seen_at=orm.first_seen_at,
            last_seen_at=orm.last_seen_at,
            created_at=orm.created_at,
            updated_at=orm.updated_at,
            last_raw_response=orm.last_raw_response,
        )

    @staticmethod
    def to_orm(entity: Delivery) -> DeliveryORM:
        return DeliveryORM(
            id=entity.id,
            tracking_number=entity.tracking_number,
            # ... all fields
        )
```

Each entity has a corresponding mapper: `DeliveryMapper`, `DeliveryEventMapper`, `StatusHistoryMapper`, `UserMapper`, `PollLogMapper`. The mapper pattern ensures domain entities never carry SQLAlchemy instrumentation — a domain entity returned from a repository method is a plain dataclass, not an ORM instance.

---

## 5. Repository Implementations

**Package**: `app/infrastructure/database/repositories/`

Each implementation accepts an `AsyncSession` via its constructor (injected by the presentation layer's `Depends()` chain).

### 5.1 `SQLAlchemyDeliveryRepository`

**File**: `app/infrastructure/database/repositories/sqlalchemy_delivery_repository.py`

Implements `AbstractDeliveryRepository`. Key method implementations:

#### `get_snapshot()`
```python
async def get_snapshot(self) -> dict[tuple[str, str], UUID]:
    result = await self._session.execute(
        select(DeliveryORM.tracking_number, DeliveryORM.carrier_code, DeliveryORM.id)
    )
    return {(row.tracking_number, row.carrier_code): row.id for row in result}
```
Single query; O(1) lookup in memory during the poll cycle (POLL-REQ-015).

#### `list_filtered()` — Dynamic Query Builder
```python
async def list_filtered(self, params: DeliveryFilterParams) -> tuple[list[Delivery], int]:
    query = select(DeliveryORM)

    # TERMINAL exclusion (API-REQ-010)
    if not params.include_terminal:
        terminal_statuses = [s.value for s in SemanticStatus
                             if get_lifecycle_group(s) == LifecycleGroup.TERMINAL]
        query = query.where(DeliveryORM.semantic_status.not_in(terminal_statuses))

    # lifecycle_group filter
    if params.lifecycle_group:
        statuses_in_group = [s.value for s in SemanticStatus
                             if get_lifecycle_group(s).value == params.lifecycle_group]
        query = query.where(DeliveryORM.semantic_status.in_(statuses_in_group))

    # semantic_status filter (overrides lifecycle_group if both provided)
    if params.semantic_status:
        query = query.where(DeliveryORM.semantic_status == params.semantic_status)

    # carrier filter
    if params.carrier_code:
        query = query.where(DeliveryORM.carrier_code == params.carrier_code)

    # search — parameterised ILIKE on two columns (SEC-REQ-058, API-REQ-011)
    if params.search:
        term = f"%{params.search}%"
        query = query.where(
            or_(
                DeliveryORM.description.ilike(bindparam("search_term", term)),
                DeliveryORM.tracking_number.ilike(bindparam("search_term2", term)),
            )
        )

    # Count total before pagination
    count_query = select(func.count()).select_from(query.subquery())
    total = (await self._session.execute(count_query)).scalar_one()

    # Sort (API-REQ-012: NULLs last for timestamp_expected)
    sort_col = getattr(DeliveryORM, params.sort_by)
    if params.sort_by == "timestamp_expected":
        sort_col = sort_col.asc().nullslast() if params.sort_dir == "asc" \
                   else sort_col.desc().nullslast()
    else:
        sort_col = sort_col.asc() if params.sort_dir == "asc" else sort_col.desc()
    query = query.order_by(sort_col)

    # Pagination
    offset = (params.page - 1) * params.page_size
    query = query.offset(offset).limit(params.page_size)

    rows = (await self._session.execute(query)).scalars().all()
    return [DeliveryMapper.to_domain(row) for row in rows], total
```

#### `create_event()` — ON CONFLICT DO NOTHING
```python
async def create_event(self, event: DeliveryEvent) -> Optional[DeliveryEvent]:
    stmt = insert(DeliveryEventORM).values(
        id=uuid4(),
        delivery_id=event.delivery_id,
        event_description=event.event_description,
        event_date_raw=event.event_date_raw,
        location=event.location,
        additional_info=event.additional_info,
        sequence_number=event.sequence_number,
        recorded_at=utcnow(),
    ).on_conflict_do_nothing(
        index_elements=["delivery_id", "event_description", "event_date_raw"]
    ).returning(DeliveryEventORM)

    result = await self._session.execute(stmt)
    row = result.scalars().first()
    return DeliveryEventMapper.to_domain(row) if row else None
```
Returns `None` (not an error) if the fingerprint already exists (DM-BR-007).

---

### 5.2 `SQLAlchemyUserRepository`

**File**: `app/infrastructure/database/repositories/sqlalchemy_user_repository.py`

#### `increment_token_version()` — Atomic Update
```python
async def increment_token_version(self, user_id: int) -> int:
    stmt = (
        update(UserORM)
        .where(UserORM.id == user_id)
        .values(token_version=UserORM.token_version + 1)
        .returning(UserORM.token_version)
    )
    result = await self._session.execute(stmt)
    await self._session.commit()
    return result.scalar_one()
```
Single `UPDATE … RETURNING` — atomic at the database level (SEC-REQ-021).

---

### 5.3 `SQLAlchemyPollLogRepository`

**File**: `app/infrastructure/database/repositories/sqlalchemy_poll_log_repository.py`

#### `count_consecutive_errors()`
```python
async def count_consecutive_errors(self) -> int:
    """
    Walk recent PollLog records newest-first.
    Stop at the first 'success' outcome and return the error count.
    """
    rows = await self.get_recent(limit=20)  # cap scan at 20
    count = 0
    for row in rows:
        if row.outcome == PollOutcome.SUCCESS:
            break
        if row.outcome in (PollOutcome.ERROR, PollOutcome.PARTIAL):
            count += 1
    return count
```

---

## 6. Parcel API Client

**File**: `app/infrastructure/parcel_api/client.py`

Implements `AbstractParcelAPIClient`. Uses a **shared** `httpx.AsyncClient` instance passed in at construction time — not created per-poll (POLL-REQ-012, keep-alive).

### Configuration
```
Base URL:   https://api.parcel.app
Endpoint:   GET /external/deliveries/?filter_mode=recent
Header:     api-key: <PARCEL_API_KEY>  (not Authorization — POLL-REQ-010)
Timeout:    30s combined connect + read
TLS:        certificate verification enabled; system trust store
```

### Retry Logic (POLL-REQ-026)

The retry logic lives in the client, not the use case. The use case receives either a result or a terminal exception (rate-limited, auth failure, or all retries exhausted).

```python
RETRY_DELAYS = [15, 60, 120]   # seconds (POLL-REQ-026)

async def get_deliveries(self) -> list[ParcelDeliveryDTO]:
    last_error = None

    for attempt in range(len(RETRY_DELAYS) + 1):   # 0, 1, 2, 3
        try:
            response = await self._client.get(
                "/external/deliveries/",
                params={"filter_mode": "recent"},
                headers={"api-key": self._api_key},
                timeout=self._timeout,
            )

            if response.status_code == 429:
                raise ParcelRateLimitError("Rate limited (HTTP 429)")

            if response.status_code == 401:
                raise ParcelAuthError("Authentication failed (HTTP 401)")

            if response.status_code >= 400:
                raise ParcelServerError(response.status_code,
                                        f"Client error HTTP {response.status_code}")

            if response.status_code >= 500:
                raise ParcelServerError(response.status_code,
                                        f"Server error HTTP {response.status_code}")

            try:
                body = response.json()
            except Exception:
                raise ParcelServerError(None, "Response body is not valid JSON")

            if not body.get("success", False):
                raise ParcelResponseError(body.get("error_message", "Unknown error"))

            # Empty deliveries list is valid (POLL-REQ-014)
            return self._parse_deliveries(body.get("deliveries", []))

        except (ParcelRateLimitError, ParcelAuthError, ParcelResponseError):
            raise   # Non-retryable; propagate immediately

        except (ParcelServerError, httpx.TransportError) as err:
            last_error = err
            if attempt < len(RETRY_DELAYS):
                delay = RETRY_DELAYS[attempt]
                logger.warning(
                    "Parcel API retryable error",
                    attempt=attempt + 1,
                    error=str(err),
                    retry_delay_seconds=delay,
                )   # POLL-REQ-027
                await asyncio.sleep(delay)
            else:
                raise ParcelServerError(None, f"All retries exhausted: {last_error}") from err
```

### API Key Security

The API key is passed as an `httpx` header value. It is **never logged** at any level (POLL-REQ-033). The client uses a private `_api_key` attribute; no method exposes it. Log entries reference key presence/absence only.

### Response Parsing

**File**: `app/infrastructure/parcel_api/schemas.py`

Pydantic models for the Parcel API response shape, used only within the infrastructure layer:

```python
class ParcelAPIEvent(BaseModel):
    description: str
    date: str                   # raw string; never parsed (DM-BR-009)
    location: Optional[str]
    additional_info: Optional[str]

class ParcelAPIDelivery(BaseModel):
    tracking_number: str
    carrier_code: str
    description: str
    extra_information: Optional[str]
    status_code: int
    date_expected: Optional[str]          # raw string (DM-BR-025)
    date_expected_end: Optional[str]
    timestamp_expected: Optional[int]     # Unix epoch → converted to datetime on parse
    timestamp_expected_end: Optional[int]
    events: list[ParcelAPIEvent] = []

class ParcelAPIResponse(BaseModel):
    success: bool
    deliveries: list[ParcelAPIDelivery] = []
    error_message: Optional[str]
```

`timestamp_expected` and `timestamp_expected_end` are epoch integers in the Parcel API; the client converts them to UTC `datetime` objects. Raw date strings are passed through verbatim (DM-BR-025).

---

## 7. Carrier Cache

**File**: `app/infrastructure/parcel_api/carrier_cache.py`

Implements `AbstractCarrierCache`. Stores the carrier list in application memory with a 24-hour TTL. A background refresh task is registered during lifespan startup, separate from the polling scheduler (API-REQ-019).

```python
class CarrierCache(AbstractCarrierCache):
    def __init__(self, client: httpx.AsyncClient):
        self._carriers: list[CarrierDTO] = []
        self._cached_at: Optional[datetime] = None
        self._ttl_hours: int = 24
        self._client = client

    def get_carriers(self) -> CarrierListDTO:
        if not self._cached_at:
            return CarrierListDTO(carriers=[], cached_at=None, cache_status="unavailable")

        age = datetime.utcnow() - self._cached_at
        status = "fresh" if age.total_seconds() < self._ttl_hours * 3600 else "stale"
        return CarrierListDTO(
            carriers=self._carriers,
            cached_at=self._cached_at,
            cache_status=status,
        )

    async def refresh(self) -> None:
        """
        Fetch carriers from Parcel API. On failure, retain existing cache
        (API-REQ-020: stale data served without error).
        """
        try:
            response = await self._client.get(
                "https://api.parcel.app/external/supported_carriers.json",
                timeout=10.0,
            )
            response.raise_for_status()
            data = response.json()
            self._carriers = [CarrierDTO(code=k, name=v) for k, v in data.items()]
            self._cached_at = datetime.utcnow()
        except Exception as err:
            logger.warning("Carrier cache refresh failed; retaining existing cache", error=str(err))
            # Existing self._carriers is preserved (API-REQ-020)
```

The carrier refresh runs as an `IntervalTrigger` job (interval=24h) alongside the main polling job in the APScheduler instance.

---

## 8. APScheduler Integration

**File**: `app/infrastructure/scheduler/polling_scheduler.py`

### Scheduler Configuration

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler()
```

| Setting | Value | Source |
|---------|-------|--------|
| Job class | `IntervalTrigger` | POLL-REQ-005 |
| Interval | `POLL_INTERVAL_MINUTES` minutes (default 15) | POLL-REQ-005 |
| Jitter | `POLL_JITTER_SECONDS` seconds (default 30) | non-functional requirement |
| Max instances | `1` — overlapping poll dropped with WARNING (POLL-REQ-032) | POLL-REQ-032 |
| Misfire grace | `60` seconds | ARCH-OVERVIEW §6 |
| Coalesce | `True` — multiple misfired triggers collapse to one | Standard practice |

### Job Registration

```python
def register_poll_job(
    scheduler: AsyncIOScheduler,
    poll_use_case: PollAndSyncUseCase,
    interval_minutes: int,
    jitter_seconds: int,
) -> None:
    scheduler.add_job(
        func=_run_poll_cycle,
        args=[poll_use_case],
        trigger=IntervalTrigger(
            minutes=interval_minutes,
            jitter=jitter_seconds,
        ),
        id="poll_and_sync",
        name="Parcel API Poll Cycle",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
        replace_existing=True,
    )
```

### Session Management for Polling

The polling use case runs **outside the per-request session lifecycle**. A dedicated session is created and passed to the use case repositories for each poll cycle:

```python
async def _run_poll_cycle(use_case: PollAndSyncUseCase) -> None:
    """
    APScheduler job function. Creates a fresh database session for the poll cycle.
    """
    try:
        async with async_session_factory() as session:
            # Inject session into repositories for this cycle
            delivery_repo = SQLAlchemyDeliveryRepository(session)
            poll_log_repo = SQLAlchemyPollLogRepository(session)
            # use_case already holds parcel_client reference

            poll_use_case = PollAndSyncUseCase(
                delivery_repo=delivery_repo,
                poll_log_repo=poll_log_repo,
                parcel_client=use_case._parcel_client,
            )
            await poll_use_case.execute()
    except Exception:
        logger.exception("Unhandled error in poll cycle job")
        # Scheduler remains running; next interval fires normally
```

### Cold-Start Behaviour (POLL-REQ-003)

The immediate cold-start poll is triggered during FastAPI lifespan startup, **before** the scheduler's first interval fires. It runs as an `asyncio.create_task()` — non-blocking, so HTTP serving begins in parallel:

```python
# In FastAPI lifespan startup:
asyncio.create_task(_run_poll_cycle(poll_use_case))  # POLL-REQ-003
scheduler.start()
# Next scheduled poll runs POLL_INTERVAL_MINUTES after the cold-start poll completes
# (POLL-REQ-004: cold-start poll doesn't count against interval)
```

### Scheduler Shutdown (POLL-REQ-002)

```python
# In FastAPI lifespan teardown:
scheduler.shutdown(wait=True)  # waits up to APScheduler's grace period for in-progress job
```

The `wait=True` parameter allows the in-progress poll cycle to complete before the process exits, up to a maximum of 30 seconds (POLL-REQ-002). If the poll does not complete within this window, APScheduler interrupts it.

---

## 9. Alembic Migration Notes

**Package**: `alembic/versions/`

### Initial Migration (`0001_initial_schema.py`)

The initial Alembic revision creates all five tables with all indexes, constraints, and check constraints specified in `02-data-model.md` and required by `05-rest-api.md` (DM-MIG-003):

| Table | Critical additions vs requirements doc |
|-------|---------------------------------------|
| `users` | `token_version INTEGER NOT NULL DEFAULT 1` (GAP-001 from ARCH-OVERVIEW) |
| `deliveries` | `JSONB` column `last_raw_response`; `NULLS LAST` index on `timestamp_expected` |
| `delivery_events` | `UNIQUE (delivery_id, event_description, event_date_raw)` fingerprint constraint |
| `status_history` | `CHECK (outcome IN (...))` — note: this check is on `poll_logs`, not here |
| `poll_logs` | `CHECK (outcome IN ('in_progress','success','partial','error'))` |

### Seed Script (`app/seed.py`)

Separate from Alembic. Executed by `entrypoint.sh` after migrations:

```python
async def seed_initial_user():
    async with async_session_factory() as session:
        count = await session.scalar(select(func.count(UserORM.id)))
        if count > 0:
            logger.info("Users table is not empty; skipping seed.")
            return  # DM-MIG-004: idempotent

        username = settings.admin_username
        password = settings.admin_password
        if not username or not password:
            logger.critical("Database empty but ADMIN_USERNAME/ADMIN_PASSWORD not set")
            sys.exit(1)  # DEPLOY-REQ-028

        if len(password) < 12:
            logger.critical("ADMIN_PASSWORD must be at least 12 characters")
            sys.exit(1)  # SEC-REQ-005

        password_hash = pwd_context.hash(password)  # bcrypt cost ≥ 12 (SEC-REQ-001)
        session.add(UserORM(
            username=username,
            password_hash=password_hash,
            is_active=True,
            token_version=1,
        ))
        await session.commit()
        logger.warning(
            "Initial user seeded. REMOVE ADMIN_PASSWORD from .env now.",
        )  # SEC-REQ-004
```

---

## 10. Infrastructure Test Strategy

| Component | Test Type | Fixture Requirement |
|-----------|-----------|---------------------|
| ORM models | Integration | Test PostgreSQL (Docker) or SQLite |
| Repository implementations | Integration | Test database |
| Mappers | Unit | No fixture; pure Python |
| `ParcelAPIClient` | Unit | `httpx.MockTransport` or `respx` |
| `CarrierCache` | Unit | Mocked httpx client |
| APScheduler integration | Integration | Mocked `PollAndSyncUseCase` |
| Alembic migrations | Integration | Test PostgreSQL |

**Note**: Integration tests should use a dedicated test database spun up via `docker compose -f docker-compose.test.yml`. The `pytest-asyncio` plugin handles async test cases.

---

*Requirements traceability: DM-BR-001–026, DM-MIG-001–004, POLL-REQ-007–036, SEC-REQ-001–004, SEC-REQ-021, API-REQ-007, API-REQ-012, API-REQ-019–020, DEPLOY-REQ-021–028*  
*Produced from: `02-data-model.md`, `03-polling-service.md`, `05-rest-api.md`, `07-auth-security.md`, `08-deployment.md`*
