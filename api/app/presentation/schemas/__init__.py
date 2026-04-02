"""Presentation layer HTTP schemas.

All Pydantic request/response models that define the JSON wire format
for the API.  These are distinct from Domain entities and Application DTOs.

Imports:
    from app.presentation.schemas.auth_schemas import LoginRequest, LoginResponse, ErrorResponse
    from app.presentation.schemas.delivery_schemas import PaginatedDeliveryResponse, DeliveryDetailResponse
    from app.presentation.schemas.system_schemas import HealthResponse, CarrierListResponse
"""
