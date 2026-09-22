"""Security response headers for every HTTP response (docs/09).

Pure ASGI middleware: it never reads bodies and only *adds* headers, so routes that set
their own ``Cache-Control`` (signed downloads) keep it. Interactive API docs are exempt
from the content-security policy because Swagger UI loads its assets from a CDN.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

DOCS_PREFIXES = ("/docs", "/openapi.json")

BASE_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), interest-cohort=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}
# The API serves data, never a page: nothing may load and nobody may frame it.
API_CSP = "default-src 'none'; frame-ancestors 'none'"
HSTS = "max-age=63072000; includeSubDomains"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self._app = app
        self._hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        path = str(scope.get("path", ""))

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in BASE_HEADERS.items():
                    headers[name] = value
                if not path.startswith(DOCS_PREFIXES):
                    headers["Content-Security-Policy"] = API_CSP
                # Responses carry per-user data: no shared caches, unless a route said otherwise.
                headers.setdefault("Cache-Control", "no-store")
                if self._hsts:
                    headers["Strict-Transport-Security"] = HSTS
            await send(message)

        await self._app(scope, receive, send_with_headers)
