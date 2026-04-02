"""Auth DTOs — typed contracts for authentication use cases.

These DTOs carry the inputs and outputs between the presentation layer and
the authentication use cases.  JWT signing and cookie handling are the sole
responsibility of the presentation layer; the application layer works with
plain claim dictionaries captured in these models.

No SQLAlchemy, no FastAPI, no httpx imports.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class LoginCredentialsDTO(BaseModel):
    """Input credentials supplied by the user at POST /api/auth/login."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class AccessTokenClaimsDTO(BaseModel):
    """Payload for the short-lived access token.

    The presentation layer adds ``iat`` and ``exp`` before signing.
    """

    sub: str
    """Username — the token subject."""

    type: Literal["access"] = "access"
    """Token type discriminator — prevents a refresh token being used as access."""

    token_version: int
    """Must match ``users.token_version`` at validation time (SEC-REQ-017)."""


class RefreshTokenClaimsDTO(BaseModel):
    """Decoded, pre-validated claims extracted from the refresh token cookie.

    JWT signature verification and expiry checks are performed by the
    presentation layer *before* constructing this DTO.  The application
    layer receives only the decoded claims.
    """

    sub: str
    """Username — the token subject."""

    token_version: int
    """Used to verify the token has not been revoked via logout."""

    type: Literal["refresh"]
    """Type discriminator — must equal ``'refresh'``."""


class AuthTokensDTO(BaseModel):
    """Claims for both tokens, returned by ``AuthenticateUserUseCase``.

    The presentation layer uses these to sign and set the two JWT cookies.
    """

    access_token_claims: AccessTokenClaimsDTO
    refresh_token_claims: RefreshTokenClaimsDTO
