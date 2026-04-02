"""Deliveries router — delivery list and detail endpoints.

Endpoints:
  GET /api/deliveries         — filtered, paginated delivery list
  GET /api/deliveries/{id}    — full delivery detail

Both endpoints require a valid Bearer access token.

Architecture: ARCH-PRESENTATION §7.2
Requirements: API-REQ-010–015, API-REQ-026–028
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse

from app.application.dtos.delivery_dtos import (
    DeliveryDetailDTO,
    DeliveryEventDTO,
    DeliveryFilterParams,
    DeliveryListDTO,
    DeliverySummaryDTO,
    StatusHistoryEntryDTO,
)
from app.application.use_cases.deliveries.get_deliveries import GetDeliveriesUseCase
from app.application.use_cases.deliveries.get_delivery_detail import (
    GetDeliveryDetailUseCase,
)
from app.domain.entities.user import User
from app.domain.exceptions import DeliveryNotFoundError
from app.presentation.dependencies import (
    get_current_user,
    get_deliveries_use_case,
    get_delivery_detail_use_case,
)
from app.presentation.schemas.auth_schemas import ErrorBody, ErrorResponse
from app.presentation.schemas.delivery_schemas import (
    DeliveryDetailResponse,
    DeliveryDetailSchema,
    DeliveryEventSchema,
    DeliveryListQueryParams,
    PaginatedDeliveryData,
    PaginatedDeliveryResponse,
    StatusHistoryEntrySchema,
    DeliverySummarySchema,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["deliveries"])


# ---------------------------------------------------------------------------
# GET /
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=PaginatedDeliveryResponse,
    status_code=status.HTTP_200_OK,
    summary="List deliveries (filtered, paginated)",
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
    },
)
async def list_deliveries(
    params: DeliveryListQueryParams = Depends(),
    current_user: User = Depends(get_current_user),
    use_case: GetDeliveriesUseCase = Depends(get_deliveries_use_case),
) -> PaginatedDeliveryResponse:
    """Return a filtered, sorted, paginated list of deliveries.

    ``lifecycle_group`` is derived at serialisation time — never stored in
    the database (NORM-REQ-004).

    A page number beyond the total returns an empty ``items`` list — it is
    NOT a 404 (API-REQ-028).
    """
    filter_params = DeliveryFilterParams(
        page=params.page,
        page_size=params.page_size,
        lifecycle_group=params.lifecycle_group,
        semantic_status=params.semantic_status,
        carrier_code=params.carrier_code,
        search=params.search,
        sort_by=params.sort_by,
        sort_dir=params.sort_dir,
        include_terminal=params.include_terminal,
    )

    result: DeliveryListDTO = await use_case.execute(filter_params)

    return PaginatedDeliveryResponse(
        data=PaginatedDeliveryData(
            items=[_summary_to_schema(d) for d in result.items],
            total=result.total,
            page=result.page,
            page_size=result.page_size,
            pages=result.pages,
        )
    )


# ---------------------------------------------------------------------------
# GET /{delivery_id}
# ---------------------------------------------------------------------------


@router.get(
    "/{delivery_id}",
    response_model=DeliveryDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get full delivery detail",
    responses={
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        404: {"model": ErrorResponse, "description": "Delivery not found"},
    },
)
async def get_delivery(
    delivery_id: UUID,
    current_user: User = Depends(get_current_user),
    use_case: GetDeliveryDetailUseCase = Depends(get_delivery_detail_use_case),
) -> DeliveryDetailResponse:
    """Return full delivery detail including all events and status history.

    Events are ordered by ``sequence_number ASC``; status history by
    ``detected_at ASC`` (API-REQ-014).  All records returned in a single
    response — not paginated (API-REQ-015).

    FastAPI validates that ``delivery_id`` is a valid UUID — a malformed
    UUID returns HTTP 422 before reaching this handler (automatic).
    """
    try:
        result: DeliveryDetailDTO = await use_case.execute(delivery_id)
    except DeliveryNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error=ErrorBody(
                    code="NOT_FOUND",
                    message=f"Delivery {delivery_id} not found",
                )
            ).model_dump(),
        )

    return DeliveryDetailResponse(data=_detail_to_schema(result))


# ---------------------------------------------------------------------------
# DTO → Schema mappers
# ---------------------------------------------------------------------------


def _summary_to_schema(dto: DeliverySummaryDTO) -> DeliverySummarySchema:
    """Map a ``DeliverySummaryDTO`` to its HTTP schema equivalent."""
    return DeliverySummarySchema(
        id=dto.id,
        tracking_number=dto.tracking_number,
        carrier_code=dto.carrier_code,
        description=dto.description,
        semantic_status=dto.semantic_status,
        lifecycle_group=dto.lifecycle_group,
        parcel_status_code=dto.parcel_status_code,
        date_expected_raw=dto.date_expected_raw,
        date_expected_end_raw=dto.date_expected_end_raw,
        timestamp_expected=dto.timestamp_expected,
        timestamp_expected_end=dto.timestamp_expected_end,
        first_seen_at=dto.first_seen_at,
        last_seen_at=dto.last_seen_at,
        updated_at=dto.updated_at,
    )


def _detail_to_schema(dto: DeliveryDetailDTO) -> DeliveryDetailSchema:
    """Map a ``DeliveryDetailDTO`` to its HTTP schema equivalent."""
    return DeliveryDetailSchema(
        id=dto.id,
        tracking_number=dto.tracking_number,
        carrier_code=dto.carrier_code,
        description=dto.description,
        extra_information=dto.extra_information,
        semantic_status=dto.semantic_status,
        lifecycle_group=dto.lifecycle_group,
        parcel_status_code=dto.parcel_status_code,
        date_expected_raw=dto.date_expected_raw,
        date_expected_end_raw=dto.date_expected_end_raw,
        timestamp_expected=dto.timestamp_expected,
        timestamp_expected_end=dto.timestamp_expected_end,
        first_seen_at=dto.first_seen_at,
        last_seen_at=dto.last_seen_at,
        updated_at=dto.updated_at,
        events=[_event_to_schema(e) for e in dto.events],
        status_history=[_history_to_schema(h) for h in dto.status_history],
    )


def _event_to_schema(dto: DeliveryEventDTO) -> DeliveryEventSchema:
    return DeliveryEventSchema(
        id=dto.id,
        event_description=dto.event_description,
        event_date_raw=dto.event_date_raw,
        location=dto.location,
        additional_info=dto.additional_info,
        sequence_number=dto.sequence_number,
        recorded_at=dto.recorded_at,
    )


def _history_to_schema(dto: StatusHistoryEntryDTO) -> StatusHistoryEntrySchema:
    return StatusHistoryEntrySchema(
        id=dto.id,
        previous_status_code=dto.previous_status_code,
        previous_semantic_status=dto.previous_semantic_status,
        new_status_code=dto.new_status_code,
        new_semantic_status=dto.new_semantic_status,
        detected_at=dto.detected_at,
    )
