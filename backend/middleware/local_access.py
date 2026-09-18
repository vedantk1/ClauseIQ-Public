"""Local browser boundary: loopback Host, explicit Origin and non-simple requests.

The marker is not a password. It forces browsers to preflight cross-origin
requests, which only the configured local frontend origins may make. Native
programs and other processes running as the local OS user are trusted.
"""
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse

LOCAL_REQUEST_HEADER = "X-ClauseIQ-Local"
LOCAL_REQUEST_VALUE = "1"
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def local_access_middleware(allowed_origins: list[str]):
    origins = frozenset(allowed_origins)

    async def enforce(request: Request, call_next):
        def deny(message: str):
            return JSONResponse(status_code=403, content={
                "success": False,
                "error": {"code": "LOCAL_ACCESS_REQUIRED", "message": message},
            })

        try:
            authority = urlsplit("http://" + request.headers.get("host", ""))
            valid_host = (
                authority.hostname in LOOPBACK_HOSTS
                and not authority.username and not authority.password
                and not authority.path and not authority.query and not authority.fragment
            )
            # Validate malformed ports as well as the hostname.
            authority.port
        except ValueError:
            valid_host = False
        if not valid_host:
            return deny("ClauseIQ is available on localhost only.")

        origin = request.headers.get("origin")
        # Swagger's own origin may use the backend port.
        same_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
        if origin is not None and origin not in origins and origin != same_origin:
            return deny("This browser origin cannot access the local workspace.")

        if request.method == "OPTIONS":
            return await call_next(request)

        # Minimal liveness and the API docs have no workspace data or side effects.
        public_paths = {"/", "/health", "/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}
        if request.url.path not in public_paths:
            if request.headers.get(LOCAL_REQUEST_HEADER) != LOCAL_REQUEST_VALUE:
                return deny("The local workspace request header is required.")
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    return enforce
