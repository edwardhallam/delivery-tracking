"""SecurityHeadersMiddleware — adds security headers to every response.

Applied to ALL responses regardless of route or authentication status.

Headers added (API-REQ-021, SEC-REQ-031):
  X-Content-Type-Options: nosniff          — prevents MIME sniffing
  X-Frame-Options: DENY                    — prevents clickjacking
  X-XSS-Protection: 0                      — disables broken XSS auditor (modern browsers)
  Referrer-Policy: strict-origin-when-cross-origin

Header removed (SEC-REQ-034):
  Server                                   — suppresses Uvicorn/Python version leakage

Implementation note: Uses a **pure ASGI middleware** (not BaseHTTPMiddleware).
BaseHTTPMiddleware in recent Starlette versions bypasses exception handlers
registered via ``add_exception_handler(Exception, ...)`` by propagating route
exceptions past ``ExceptionMiddleware`` to ``ServerErrorMiddleware``.  The
pure ASGI approach intercepts the ``http.response.start`` event directly,
which preserves the full exception handling chain.

Architecture: ARCH-PRESENTATION §3, §8.1
Requirements: API-REQ-021, SEC-REQ-031, SEC-REQ-034
"""
from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

# Security header bytes for efficient repeated use
_SECURITY_HEADERS: list[tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"x-xss-protection", b"0"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
]


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that injects security headers on every HTTP response.

    Operates at the ASGI message level — intercepts ``http.response.start``
    events to add headers and strip the ``server`` header before the response
    bytes are sent to the client.  Non-HTTP scope types (WebSocket, lifespan)
    are passed through unchanged.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_security_headers(message: dict) -> None:
            if message["type"] == "http.response.start":
                # Filter out the Server header (SEC-REQ-034) and rebuild the list
                filtered: list[tuple[bytes, bytes]] = [
                    (k, v)
                    for k, v in message.get("headers", [])
                    if k.lower() != b"server"
                ]
                # Append all security headers
                message = {**message, "headers": filtered + _SECURITY_HEADERS}
            await send(message)

        await self.app(scope, receive, send_with_security_headers)
