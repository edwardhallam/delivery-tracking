"""System router — health and carrier list endpoints.

Endpoints:
  GET /api/health    — service health (public — no auth required)
  GET /api/carriers  — carrier code → name list (requires auth)

Architecture: ARCH-PRESENTATION §7.3
Requirements: API-REQ-016–020
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse

from app.application.dtos.system_dtos import CarrierDTO, CarrierListDTO, HealthDTO
from app.application.use_cases.system.get_carriers import GetCarriersUseCase
from app.application.use_cases.system.get_health import GetHealthUseCase
from app.domain.entities.user import User
from app.presentation.dependencies import (
    get_carriers_use_case,
    get_current_user,
    get_health_use_case,
)
from app.presentation.schemas.auth_schemas import ErrorResponse
from app.presentation.schemas.system_schemas import (
    CarrierListResponse,
    CarrierListSchema,
    CarrierSchema,
    DatabaseHealthSchema,
    HealthResponse,
    HealthSchema,
    PollingHealthSchema,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["system"])


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service health check",
    responses={
        200: {"description": "Healthy or degraded"},
        503: {"description": "Unhealthy — database or scheduler down"},
    },
)
async def health_check(
    use_case: GetHealthUseCase = Depends(get_health_use_case),
) -> JSONResponse:
    """Return service health.

    **No authentication required** — Docker health checks and load balancers
    must be able to call this endpoint without credentials.

    HTTP status codes (API-REQ-017):
      - ``200`` — ``status`` is ``"healthy"`` OR ``"degraded"``
      - ``503`` — ``status`` is ``"unhealthy"`` (DB disconnected or scheduler stopped)

    The health use case **never raises** — all sub-check failures produce a
    conservative health value in the DTO.
    """
    health_dto: HealthDTO = await use_case.execute()

    http_status = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if health_dto.status == "unhealthy"
        else status.HTTP_200_OK
    )

    response_body = HealthResponse(
        data=HealthSchema(
            status=health_dto.status,
            database=DatabaseHealthSchema(
                status=health_dto.database.status,
                latency_ms=health_dto.database.latency_ms,
            ),
            polling=PollingHealthSchema(
                scheduler_running=health_dto.polling.scheduler_running,
                last_poll_at=health_dto.polling.last_poll_at,
                last_poll_outcome=health_dto.polling.last_poll_outcome,
                last_successful_poll_at=health_dto.polling.last_successful_poll_at,
                consecutive_errors=health_dto.polling.consecutive_errors,
                next_poll_at=health_dto.polling.next_poll_at,
            ),
            version=health_dto.version,
        )
    )

    return JSONResponse(
        content=response_body.model_dump(mode="json"),
        status_code=http_status,
    )


# ---------------------------------------------------------------------------
# GET /carriers
# ---------------------------------------------------------------------------


@router.get(
    "/carriers",
    response_model=CarrierListResponse,
    status_code=status.HTTP_200_OK,
    summary="List supported carriers (from cache)",
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_carriers(
    current_user: User = Depends(get_current_user),
    use_case: GetCarriersUseCase = Depends(get_carriers_use_case),
) -> CarrierListResponse:
    """Return the cached carrier code → name mapping.

    **Never triggers a synchronous outbound HTTP call** (API-REQ-019).  The
    carrier list is populated asynchronously from the Parcel API on startup
    and refreshed every 24 hours.

    When the cache has never been populated, an empty list is returned with
    ``cache_status="unavailable"`` — no error is raised (API-REQ-020).
    """
    result: CarrierListDTO = await use_case.execute()

    return CarrierListResponse(
        data=CarrierListSchema(
            carriers=[
                CarrierSchema(code=c.code, name=c.name)
                for c in result.carriers
            ],
            cached_at=result.cached_at,
            cache_status=result.cache_status,
        )
    )
