"""Server-owned HTTP identity, separate from document and paid-attempt IDs."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

from starlette.requests import Request


_request_id: ContextVar[str | None] = ContextVar("http_request_id", default=None)


def current_request_id() -> str | None:
    """Return only the current server-generated HTTP identity."""
    return _request_id.get()


@contextmanager
def request_context(request: Request) -> Iterator[str]:
    """Reuse a request's identity across middleware without trusting headers.

    Context variables isolate concurrent requests and propagate through async
    calls and Starlette's worker threads. Resetting prevents later work on the
    same task from inheriting the completed request's identity.
    """
    identity = getattr(request.state, "_http_request_id", None)
    if identity is None:
        identity = str(uuid4())
        request.state._http_request_id = identity
    request.state.request_id = identity
    request.state.correlation_id = identity
    token = _request_id.set(identity)
    try:
        yield identity
    finally:
        _request_id.reset(token)
