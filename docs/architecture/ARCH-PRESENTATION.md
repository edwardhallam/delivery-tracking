# Presentation Layer Design
## Delivery Tracking Web Service

**Document ID**: ARCH-PRESENTATION  
**Status**: Draft  
**Addresses**: `05-rest-api.md`, `07-auth-security.md`, `08-deployment.md`  
**Layer Mapping**: Layer 4 — Presentation (outermost)

---

## Summary

The Presentation layer is the FastAPI surface of the service. It owns HTTP routing, request validation, response serialisation, JWT creation and validation, DI wiring (connecting application use cases to their infrastructure implementations), security middleware, and the application factory. This layer is the only part of the system that knows FastAPI exists — layers below it are entirely framework-independent.

---

## 1. Layer Role and Rules

| Property | Value |
|----------|-------|
| Package | `app.presentation` |
| Depends on | `app.application`, `app.domain` |
| Must NOT import | `sqlalchemy` internals, `httpx`, `apscheduler` directly |
| May import | `fastapi`, `pydantic`, `python-jose`, `passlib`, `app.application.*`, `app.domain.*` |
| Testing | FastAPI `TestClient` / `AsyncClient`; mock use cases via `app.dependency_overrides` |

---

## 2. Configuration (`config.py`)

**File**: `app/config.py`  
*Note: Shared by all layers that need it. Lives at package root to avoid circular imports.*

Built on `pydantic-settings` `BaseSettings`. All settings are read from environment variables; all required variables are validated at import time. Startup failures are fatal (logged CRITICAL, then `sys.exit(1)`).

```python
class Settings(BaseSettings):
    # ── Required ───────────────────────────────────────────────────────────
    parcel_api_key: SecretStr           # never logged (POLL-REQ-007/009)
    database_url: str                   # async: postgresql+psycopg://...
    jwt_secret_key: SecretStr

    # ── Authentication ─────────────────────────────────────────────────────
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7

    # ── Polling ────────────────────────────────────────────────────────────
    poll_interval_minutes: int = 15
    poll_jitter_seconds: int = 30
    poll_http_timeout_seconds: int = 30
    poll_max_retries: int = 3

    # ── Security ───────────────────────────────────────────────────────────
    bcrypt_rounds: int = 12
    cookie_secure: bool = False        # True when HTTPS (SEC-REQ-023)
    trust_proxy_headers: bool = False  # True behind Nginx (SEC-REQ-040)
    https_enabled: bool = False

    # ── Application ────────────────────────────────────────────────────────
    environment: str = "production"    # "development" | "production"
    version: str = "1.0.0"

    # ── Optional first-run ─────────────────────────────────────────────────
    admin_username: Optional[str] = None
    admin_password: Optional[SecretStr] = None
    frontend_http_port: int = 80

    # ── Derived (computed property) ────────────────────────────────────────
    @property
    def sync_database_url(self) -> str:
        """Synchronous DB URL for Alembic migrations."""
        return self.database_url.replace("postgresql+psycopg", "postgresql+psycopg2")

    # ── Validators ─────────────────────────────────────────────────────────
    @field_validator("jwt_secret_key")
    def validate_jwt_secret(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters (SEC-REQ-010)")
        return v

    @field_validator("access_token_expire_minutes")
    def validate_access_ttl(cls, v: int) -> int:
        if not (5 <= v <= 1440):
            raise ValueError("ACCESS_TOKEN_EXPIRE_MINUTES must be 5–1440 (SEC-REQ-014)")
        return v

    @field_validator("refresh_token_expire_days")
    def validate_refresh_ttl(cls, v: int) -> int:
        if not (1 <= v <= 30):
            raise ValueError("REFRESH_TOKEN_EXPIRE_DAYS must be 1–30 (SEC-REQ-014)")
        return v

    @field_validator("poll_interval_minutes")
    def validate_poll_interval(cls, v: int) -> int:
        if v < 5:
            logger.warning("POLL_INTERVAL_MINUTES < 5; using minimum of 5 (POLL-REQ-005)")
            return 5
        return v

    @field_validator("bcrypt_rounds")
    def validate_bcrypt_rounds(cls, v: int) -> int:
        if not (10 <= v <= 15):
            raise ValueError("BCRYPT_ROUNDS must be 10–15 (SEC-REQ-002)")
        return v

    @model_validator(mode="after")
    def validate_https_cookie_consistency(self) -> "Settings":
        if self.https_enabled and not self.cookie_secure:
            logger.warning(
                "HTTPS_ENABLED=true but COOKIE_SECURE=false — "
                "set COOKIE_SECURE=true for secure deployments (SEC-REQ-044)"
            )
        return self

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()  # singleton; validated at import time
```

---

## 3. Application Factory (`main.py`)

**File**: `app/main.py`

The app factory constructs the FastAPI instance, registers all middleware and routes, and manages the application lifespan.

```python
def create_app() -> FastAPI:
    app = FastAPI(
        title="Delivery Tracking API",
        version=settings.version,
        # OpenAPI disabled in production (API-REQ-023)
        docs_url="/api/docs" if settings.environment == "development" else None,
        redoc_url="/api/redoc" if settings.environment == "development" else None,
        lifespan=lifespan,
    )

    # ── Middleware (registered outermost-first = executes last-first) ──────
    app.add_middleware(SecurityHeadersMiddleware)

    if settings.environment == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_credentials=True,
            allow_methods=["GET", "POST"],
            allow_headers=["Authorization", "Content-Type"],
        )   # SEC-REQ-029; not added in production (SEC-REQ-030)

    # ── Exception handlers ────────────────────────────────────────────────
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, generic_exception_handler)  # API-REQ-025

    # ── Routers ───────────────────────────────────────────────────────────
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(deliveries_router, prefix="/api/deliveries", tags=["deliveries"])
    app.include_router(system_router, prefix="/api", tags=["system"])

    return app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    # ── Startup ───────────────────────────────────────────────────────────
    logger.info("Service starting up", version=settings.version)

    # 1. Create shared httpx client (keep-alive across poll cycles, POLL-REQ-012)
    http_client = httpx.AsyncClient(verify=True)
    app.state.http_client = http_client

    # 2. Initialise carrier cache + attempt initial fetch
    carrier_cache = CarrierCache(http_client)
    asyncio.create_task(carrier_cache.refresh())  # best-effort; non-blocking
    app.state.carrier_cache = carrier_cache

    # 3. Initialise APScheduler
    scheduler = AsyncIOScheduler()
    parcel_client = ParcelAPIClient(
        client=http_client,
        api_key=settings.parcel_api_key.get_secret_value(),
        timeout=settings.poll_http_timeout_seconds,
        max_retries=settings.poll_max_retries,
    )
    app.state.scheduler = scheduler
    app.state.parcel_client = parcel_client

    # 4. Register poll + carrier refresh jobs
    register_poll_job(scheduler, parcel_client, settings)
    register_carrier_refresh_job(scheduler, carrier_cache)

    # 5. Start scheduler
    scheduler.start()
    logger.info("APScheduler started", interval_minutes=settings.poll_interval_minutes)

    # 6. Cold-start poll (POLL-REQ-003) — non-blocking; runs in parallel with HTTP serving
    asyncio.create_task(_run_cold_start_poll(parcel_client))

    yield  # ── Application serves requests ─────────────────────────────────

    # ── Shutdown ──────────────────────────────────────────────────────────
    logger.info("Service shutting down")
    scheduler.shutdown(wait=True)       # POLL-REQ-002: allow in-progress poll to complete
    await http_client.aclose()
    await engine.dispose()
    logger.info("Service stopped")


app = create_app()
```

---

## 4. HTTP Schemas

**Package**: `app/presentation/schemas/`

HTTP schemas are Pydantic models that define the exact shape of API request bodies and response payloads. They are **separate from** domain entities and application DTOs — this three-way separation ensures that changes to the API contract, the application logic, and the domain model can evolve independently.

### 4.1 Auth Schemas (`auth_schemas.py`)

```python
# ── Request schemas ──────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


# ── Response schemas ──────────────────────────────────────────────────────────

class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int     # seconds


class LoginResponse(BaseModel):
    data: AccessTokenResponse


# Error envelope (shared across all routes)
class ErrorDetail(BaseModel):
    field: Optional[str]
    message: str

class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[Union[list[ErrorDetail], dict]] = None

class ErrorResponse(BaseModel):
    error: ErrorBody
```

### 4.2 Delivery Schemas (`delivery_schemas.py`)

```python
# ── Query parameter schemas ──────────────────────────────────────────────────

class DeliveryListQueryParams(BaseModel):
    """FastAPI `Depends()` for GET /deliveries query parameters."""
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)   # API-REQ-027
    lifecycle_group: Optional[Literal["ACTIVE", "ATTENTION", "TERMINAL"]] = None
    semantic_status: Optional[str] = None
    carrier_code: Optional[str] = Field(None, max_length=50)
    search: Optional[str] = Field(None, max_length=200)
    sort_by: Literal[
        "timestamp_expected", "updated_at", "carrier_code",
        "description", "semantic_status", "first_seen_at"
    ] = "timestamp_expected"
    sort_dir: Literal["asc", "desc"] = "asc"
    include_terminal: bool = False


# ── Response schemas ──────────────────────────────────────────────────────────

class DeliveryEventSchema(BaseModel):
    id: UUID
    event_description: str
    event_date_raw: str
    location: Optional[str]
    additional_info: Optional[str]
    sequence_number: int
    recorded_at: str    # ISO 8601 UTC Z suffix (API-REQ-013)

    model_config = ConfigDict(json_encoders={datetime: lambda v: v.strftime("%Y-%m-%dT%H:%M:%SZ")})


class StatusHistoryEntrySchema(BaseModel):
    id: UUID
    previous_status_code: Optional[int]
    previous_semantic_status: Optional[str]
    new_status_code: int
    new_semantic_status: str
    detected_at: str    # ISO 8601 UTC Z suffix


class DeliverySummarySchema(BaseModel):
    id: UUID
    tracking_number: str
    carrier_code: str
    description: str
    semantic_status: str
    lifecycle_group: str    # derived; never stored (NORM-REQ-004)
    parcel_status_code: int
    date_expected_raw: Optional[str]
    date_expected_end_raw: Optional[str]
    timestamp_expected: Optional[str]      # ISO 8601 UTC Z (API-REQ-013)
    timestamp_expected_end: Optional[str]
    first_seen_at: str
    last_seen_at: str
    updated_at: str


class DeliveryDetailSchema(DeliverySummarySchema):
    extra_information: Optional[str]
    events: list[DeliveryEventSchema]
    status_history: list[StatusHistoryEntrySchema]


class PaginatedDeliveryResponse(BaseModel):
    data: "PaginatedDeliveryData"

class PaginatedDeliveryData(BaseModel):
    items: list[DeliverySummarySchema]
    total: int
    page: int
    page_size: int
    pages: int

class DeliveryDetailResponse(BaseModel):
    data: DeliveryDetailSchema
```

**Timestamp serialisation**: All `datetime` fields are serialised to ISO 8601 UTC strings with `Z` suffix (e.g. `"2025-01-16T14:30:00Z"`) — not Unix integers (API-REQ-013). A custom Pydantic JSON encoder handles this consistently.

### 4.3 System Schemas (`system_schemas.py`)

```python
class DatabaseHealthSchema(BaseModel):
    status: Literal["connected", "disconnected"]
    latency_ms: Optional[float]

class PollingHealthSchema(BaseModel):
    scheduler_running: bool
    last_poll_at: Optional[str]
    last_poll_outcome: Optional[str]
    last_successful_poll_at: Optional[str]
    consecutive_errors: int
    next_poll_at: Optional[str]   # null if scheduler not running (API-REQ-018)

class HealthSchema(BaseModel):
    status: Literal["healthy", "degraded", "unhealthy"]
    database: DatabaseHealthSchema
    polling: PollingHealthSchema
    version: str

class HealthResponse(BaseModel):
    data: HealthSchema

class CarrierSchema(BaseModel):
    code: str
    name: str

class CarrierListSchema(BaseModel):
    carriers: list[CarrierSchema]
    cached_at: Optional[str]
    cache_status: Literal["fresh", "stale", "unavailable"]

class CarrierListResponse(BaseModel):
    data: CarrierListSchema
```

---

## 5. Authentication Implementation (JWT)

JWT creation and validation live in the presentation layer. No layer below knows about JWT, Bearer tokens, or HTTP headers.

**File**: `app/presentation/dependencies.py` (auth portion)

### 5.1 Token Creation

```python
def create_access_token(user: User) -> tuple[str, int]:
    """
    Sign and return (access_token_str, expires_in_seconds).
    Claims: sub, type, token_version, iat, exp.
    """
    now = datetime.utcnow()
    expire = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": user.username,
        "type": "access",
        "token_version": user.token_version,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    token = jose.jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, settings.access_token_expire_minutes * 60


def create_refresh_token(user: User) -> str:
    now = datetime.utcnow()
    expire = now + timedelta(days=settings.refresh_token_expire_days)
    payload = {
        "sub": user.username,
        "type": "refresh",
        "token_version": user.token_version,
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jose.jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
```

### 5.2 Token Validation — `get_current_user` Dependency

The 6-step validation chain (SEC-REQ-015) is implemented as a single FastAPI dependency:

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

async def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """
    Validates Bearer token via the 6-step chain (SEC-REQ-015).
    All failures return 401 UNAUTHORIZED with the same message (SEC-REQ-016).
    Reason is logged server-side at INFO for audit (SEC-REQ-059).
    """
    credentials_exception = HTTPException(
        status_code=401,
        detail={"error": {"code": "UNAUTHORIZED", "message": "Authentication required", "details": None}},
        headers={"WWW-Authenticate": "Bearer"},
    )

    # Step 1: Token present
    if not token:
        logger.info("Token validation failed: no token provided")
        raise credentials_exception

    # Step 2: Signature valid; Step 3: Not expired
    try:
        payload = jose.jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as e:
        logger.info("Token validation failed: JWT error", reason=str(e))
        raise credentials_exception

    # Step 4: Type must be "access"
    if payload.get("type") != "access":
        logger.info("Token validation failed: wrong token type")
        raise credentials_exception

    username = payload.get("sub")
    if not username:
        logger.info("Token validation failed: missing sub claim")
        raise credentials_exception

    # Step 5: User exists and is active
    user_repo = SQLAlchemyUserRepository(session)
    user = await user_repo.get_by_username(username)
    if not user or not user.is_active:
        logger.info("Token validation failed: user not found or inactive", username=username)
        raise credentials_exception

    # Step 6: token_version matches (SEC-REQ-017)
    if user.token_version != payload.get("token_version"):
        logger.info("Token validation failed: token_version mismatch", username=username)
        raise credentials_exception

    return user


async def get_refresh_token_claims(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> RefreshTokenClaimsDTO:
    """
    Read and validate the refresh token cookie.
    Returns decoded claims; raises 401 on any failure.
    """
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=401, detail=...)

    try:
        payload = jose.jwt.decode(token, settings.jwt_secret_key.get_secret_value(), ...)
    except JWTError:
        raise HTTPException(status_code=401, detail=...)

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail=...)

    return RefreshTokenClaimsDTO(
        sub=payload["sub"],
        token_version=payload["token_version"],
        type="refresh",
    )
```

---

## 6. DI Providers (`dependencies.py`)

**File**: `app/presentation/dependencies.py`

This file is the architectural seam — it wires application use cases to their concrete infrastructure implementations. No layer below it needs to know FastAPI exists.

```python
# ── Database session ──────────────────────────────────────────────────────────

async def get_async_session(
    request: Request,
) -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── Repository providers ──────────────────────────────────────────────────────

async def get_delivery_repository(
    session: AsyncSession = Depends(get_async_session),
) -> AbstractDeliveryRepository:
    return SQLAlchemyDeliveryRepository(session)


async def get_user_repository(
    session: AsyncSession = Depends(get_async_session),
) -> AbstractUserRepository:
    return SQLAlchemyUserRepository(session)


async def get_poll_log_repository(
    session: AsyncSession = Depends(get_async_session),
) -> AbstractPollLogRepository:
    return SQLAlchemyPollLogRepository(session)


# ── External service providers ────────────────────────────────────────────────

def get_carrier_cache(request: Request) -> AbstractCarrierCache:
    return request.app.state.carrier_cache

def get_scheduler_state(request: Request) -> AbstractSchedulerState:
    return APSchedulerStateAdapter(request.app.state.scheduler)


# ── Use case providers ────────────────────────────────────────────────────────

async def get_authenticate_use_case(
    user_repo: AbstractUserRepository = Depends(get_user_repository),
) -> AuthenticateUserUseCase:
    return AuthenticateUserUseCase(user_repo=user_repo, settings=settings)


async def get_deliveries_use_case(
    delivery_repo: AbstractDeliveryRepository = Depends(get_delivery_repository),
) -> GetDeliveriesUseCase:
    return GetDeliveriesUseCase(delivery_repo=delivery_repo)


async def get_delivery_detail_use_case(
    delivery_repo: AbstractDeliveryRepository = Depends(get_delivery_repository),
) -> GetDeliveryDetailUseCase:
    return GetDeliveryDetailUseCase(delivery_repo=delivery_repo)


async def get_health_use_case(
    poll_log_repo: AbstractPollLogRepository = Depends(get_poll_log_repository),
    scheduler_state: AbstractSchedulerState = Depends(get_scheduler_state),
) -> GetHealthUseCase:
    return GetHealthUseCase(
        poll_log_repo=poll_log_repo,
        db_health_checker=DatabaseHealthChecker(async_session_factory),
        scheduler_state=scheduler_state,
        settings=settings,
    )


async def get_carriers_use_case(
    carrier_cache: AbstractCarrierCache = Depends(get_carrier_cache),
) -> GetCarriersUseCase:
    return GetCarriersUseCase(carrier_cache=carrier_cache)
```

---

## 7. Routers

### 7.1 Auth Router (`auth_router.py`)

```python
router = APIRouter()

@router.post("/login", response_model=LoginResponse, status_code=200)
async def login(
    request: Request,
    body: LoginRequest,
    use_case: AuthenticateUserUseCase = Depends(get_authenticate_use_case),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> LoginResponse:
    """
    Rate limiter runs first (SEC-REQ-035).
    On failure: InvalidCredentialsError → 401, AccountDisabledError → 403.
    On success: issues access token in body + refresh token as httpOnly cookie.
    """
    source_ip = get_client_ip(request, trust_proxy=settings.trust_proxy_headers)
    rate_limiter.check(source_ip)           # raises 429 if exceeded

    user = await use_case.execute(LoginCredentialsDTO(
        username=body.username,
        password=body.password,
    ))

    # Success: reset rate limiter counter for this IP (SEC-REQ-037)
    rate_limiter.reset(source_ip)

    access_token, expires_in = create_access_token(user)
    refresh_token = create_refresh_token(user)

    response = LoginResponse(data=AccessTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=expires_in,
    ))
    http_response = JSONResponse(content=response.model_dump())
    http_response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="strict",
        path="/api/auth",
        max_age=settings.refresh_token_expire_days * 86400,
        secure=settings.cookie_secure,   # SEC-REQ-023
    )

    logger.info("Successful login", username=user.username, source_ip=source_ip)
    return http_response


@router.post("/refresh", response_model=LoginResponse, status_code=200)
async def refresh_token(
    claims: RefreshTokenClaimsDTO = Depends(get_refresh_token_claims),
    use_case: RefreshAccessTokenUseCase = Depends(get_refresh_use_case),
) -> LoginResponse:
    user = await use_case.execute(claims)
    access_token, expires_in = create_access_token(user)
    return LoginResponse(data=AccessTokenResponse(
        access_token=access_token, token_type="bearer", expires_in=expires_in,
    ))


@router.post("/logout", status_code=204)
async def logout(
    current_user: User = Depends(get_current_user),
    use_case: LogoutUserUseCase = Depends(get_logout_use_case),
) -> Response:
    await use_case.execute(current_user.id)
    response = Response(status_code=204)
    response.delete_cookie(key="refresh_token", path="/api/auth", samesite="strict")
    logger.info("Logout", username=current_user.username)
    return response
```

### 7.2 Deliveries Router (`deliveries_router.py`)

```python
router = APIRouter()

@router.get("", response_model=PaginatedDeliveryResponse)
async def list_deliveries(
    params: DeliveryListQueryParams = Depends(),
    use_case: GetDeliveriesUseCase = Depends(get_deliveries_use_case),
    current_user: User = Depends(get_current_user),   # SEC-REQ-026: explicit declaration
) -> PaginatedDeliveryResponse:
    """
    Filtered, sorted, paginated delivery list.
    include_terminal=false (default) excludes TERMINAL lifecycle group (API-REQ-010).
    Page beyond total returns empty items, not 404 (API-REQ-028).
    """
    filter_params = DeliveryFilterParams(**params.model_dump())
    result = await use_case.execute(filter_params)
    return _map_list_dto_to_response(result)


@router.get("/{delivery_id}", response_model=DeliveryDetailResponse)
async def get_delivery(
    delivery_id: UUID,
    use_case: GetDeliveryDetailUseCase = Depends(get_delivery_detail_use_case),
    current_user: User = Depends(get_current_user),
) -> DeliveryDetailResponse:
    """
    Full delivery detail with all events and status history.
    Not paginated (API-REQ-015).
    """
    result = await use_case.execute(delivery_id)
    return _map_detail_dto_to_response(result)
```

### 7.3 System Router (`system_router.py`)

```python
router = APIRouter()

@router.get("/health", response_model=HealthResponse)
async def health_check(
    use_case: GetHealthUseCase = Depends(get_health_use_case),
    # No auth — Docker health checks run without credentials (API-REQ-016)
) -> Response:
    """
    Returns 200 for healthy/degraded; 503 for unhealthy (API-REQ-017).
    Responds within 5s; DB check timeout 3s (API-REQ-016).
    """
    health = await use_case.execute()
    status_code = 503 if health.status == "unhealthy" else 200
    return JSONResponse(
        content=HealthResponse(data=_map_health_dto(health)).model_dump(),
        status_code=status_code,
    )


@router.get("/carriers", response_model=CarrierListResponse)
async def get_carriers(
    use_case: GetCarriersUseCase = Depends(get_carriers_use_case),
    current_user: User = Depends(get_current_user),
) -> CarrierListResponse:
    """
    Returns cached carrier list. No synchronous outbound call (API-REQ-019).
    Stale cache served without error (API-REQ-020).
    """
    result = use_case.execute()
    return CarrierListResponse(data=_map_carrier_dto(result))
```

---

## 8. Middleware

### 8.1 Security Headers Middleware (`security_headers.py`)

Applied to **all responses** (API-REQ-021, SEC-REQ-031):

```python
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "0"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Suppress Server header (SEC-REQ-034)
        response.headers.pop("server", None)
        return response
```

### 8.2 Rate Limiter (`rate_limiter.py`)

In-memory sliding window counter for login brute force protection (SEC-REQ-035–040):

```python
class RateLimiter:
    """
    In-memory sliding window rate limiter for failed login attempts.
    State: dict[ip_str, list[datetime]] — timestamps of failed attempts.
    """
    WINDOW_SECONDS = 900   # 15 minutes
    MAX_FAILURES = 10

    def __init__(self):
        self._failures: dict[str, list[datetime]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, ip: str) -> None:
        """
        Raise 429 if IP has ≥ 10 failed attempts in the last 15 minutes.
        Includes Retry-After header (SEC-REQ-039).
        """
        async with self._lock:
            now = datetime.utcnow()
            window_start = now - timedelta(seconds=self.WINDOW_SECONDS)
            self._failures[ip] = [t for t in self._failures[ip] if t > window_start]

            if len(self._failures[ip]) >= self.MAX_FAILURES:
                oldest = min(self._failures[ip])
                retry_after = int((oldest + timedelta(seconds=self.WINDOW_SECONDS) - now).total_seconds())
                raise HTTPException(
                    status_code=429,
                    detail={"error": {
                        "code": "RATE_LIMITED",
                        "message": "Too many failed login attempts. Please wait before trying again.",
                        "details": None,
                    }},
                    headers={"Retry-After": str(max(retry_after, 1))},
                )

    async def record_failure(self, ip: str) -> None:
        async with self._lock:
            self._failures[ip].append(datetime.utcnow())

    async def reset(self, ip: str) -> None:
        """Reset counter on successful login (SEC-REQ-037)."""
        async with self._lock:
            self._failures.pop(ip, None)
```

**IP resolution** respects `TRUST_PROXY_HEADERS` (SEC-REQ-040): reads `X-Real-IP` or `X-Forwarded-For` only when `settings.trust_proxy_headers=True`.

### 8.3 Exception Handlers

```python
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Maps FastAPI validation errors to standard error envelope (API-REQ-005)."""
    details = [
        ErrorDetail(field=".".join(str(l) for l in err["loc"]), message=err["msg"])
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content={
        "error": {"code": "VALIDATION_ERROR",
                  "message": "Request validation failed", "details": [d.model_dump() for d in details]}
    })


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all for unhandled exceptions (API-REQ-025).
    Logs the full traceback server-side; returns generic message to client.
    Never exposes stack traces in responses.
    """
    logger.exception("Unhandled exception", path=request.url.path)
    return JSONResponse(status_code=500, content={
        "error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred", "details": None}
    })
```

Application/domain exceptions are mapped to HTTP responses within each router via `try/except` blocks or a dedicated `app_exception_handler` for common types (`DeliveryNotFoundError → 404`, `InvalidCredentialsError → 401`, etc.).

---

## 9. Presentation Testing Strategy

| Test Target | Method | Fixture |
|-------------|--------|---------|
| Route handlers | `AsyncClient` + `app.dependency_overrides` | Mock use cases |
| JWT creation/validation | Unit tests | Test settings with known key |
| Rate limiter | Unit tests | No fixture |
| Security headers | Integration test via `AsyncClient` | Verify response headers |
| Exception handlers | `AsyncClient` + forced errors | Mock use case raises |
| OpenAPI docs disabled in prod | Integration | `ENVIRONMENT=production` |

`app.dependency_overrides` is the recommended FastAPI pattern for substituting real use cases with mocks in tests:

```python
def override_get_deliveries_use_case():
    return MockGetDeliveriesUseCase(returns=fake_delivery_list())

app.dependency_overrides[get_deliveries_use_case] = override_get_deliveries_use_case
```

---

## 10. Complete Route Summary

| Method | Path | Auth | Use Case | Notes |
|--------|------|:----:|----------|-------|
| `POST` | `/api/auth/login` | ❌ | `AuthenticateUserUseCase` | Rate-limited; sets httpOnly cookie |
| `POST` | `/api/auth/refresh` | ❌ (cookie) | `RefreshAccessTokenUseCase` | Reads `refresh_token` cookie |
| `POST` | `/api/auth/logout` | ✅ | `LogoutUserUseCase` | Increments token_version; clears cookie |
| `GET` | `/api/deliveries` | ✅ | `GetDeliveriesUseCase` | Filtered, paginated |
| `GET` | `/api/deliveries/{id}` | ✅ | `GetDeliveryDetailUseCase` | Full detail; not paginated |
| `GET` | `/api/health` | ❌ | `GetHealthUseCase` | 503 on unhealthy only |
| `GET` | `/api/carriers` | ✅ | `GetCarriersUseCase` | Cached; no synchronous outbound call |

---

*Requirements traceability: API-REQ-001–028, SEC-REQ-009–017, SEC-REQ-022–040, SEC-REQ-047–048, SEC-REQ-055–061, DEPLOY-REQ-021–024*  
*Produced from: `05-rest-api.md`, `07-auth-security.md`, `08-deployment.md`*
