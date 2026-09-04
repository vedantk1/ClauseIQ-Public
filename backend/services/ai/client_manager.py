"""
OpenAI client management for ClauseIQ AI services.
Extracted from ai_service.py for better maintainability.
Includes rate limiting to prevent API quota exhaustion.
Supports request-scoped user API keys via context variables.
"""
import asyncio
import logging
from typing import Optional, Dict, Any
from contextlib import asynccontextmanager
from contextvars import ContextVar

_openai_semaphore: Optional[asyncio.Semaphore] = None
_embedding_semaphore: Optional[asyncio.Semaphore] = None

# Each authenticated request supplies its user's API key through this context.
_request_openai_client: ContextVar[Optional[Any]] = ContextVar(
    "request_openai_client",
    default=None,
)

logger = logging.getLogger(__name__)


def _ensure_rate_limiters() -> None:
    """Initialize process-wide concurrency limits on first use."""
    global _openai_semaphore, _embedding_semaphore
    if _openai_semaphore is None:
        _openai_semaphore = asyncio.Semaphore(10)
    if _embedding_semaphore is None:
        _embedding_semaphore = asyncio.Semaphore(20)


def get_openai_client():
    """Return the OpenAI client supplied for the current authenticated request."""
    return _request_openai_client.get()


def set_request_client(client) -> None:
    """Set the OpenAI client for the current request context."""
    _ensure_rate_limiters()
    _request_openai_client.set(client)


def clear_request_client() -> None:
    """Clear the request-scoped OpenAI client."""
    _request_openai_client.set(None)


@asynccontextmanager
async def user_openai_client(api_key: str):
    """
    Use a user-specific OpenAI API key for the duration of one request.

    Nested contexts are safe: the previous request client is restored on exit.
    """
    from openai import AsyncOpenAI

    if not api_key or not api_key.startswith("sk-"):
        raise ValueError("Invalid API key format")

    _ensure_rate_limiters()
    client = AsyncOpenAI(api_key=api_key)
    token = _request_openai_client.set(client)
    try:
        yield client
    finally:
        _request_openai_client.reset(token)


def is_ai_available() -> bool:
    """Check whether the current request has an OpenAI client."""
    return get_openai_client() is not None


def create_openai_client(api_key: str):
    """
    Create a new OpenAI client with the specified user API key.

    Args:
        api_key: The OpenAI API key to use

    Returns:
        AsyncOpenAI client instance
    """
    from openai import AsyncOpenAI

    if not api_key or not api_key.startswith("sk-"):
        raise ValueError("Invalid API key format")

    return AsyncOpenAI(api_key=api_key)


def reset_client() -> None:
    """Reset request state and rate limiters, primarily for shutdown and tests."""
    global _openai_semaphore, _embedding_semaphore
    clear_request_client()
    _openai_semaphore = None
    _embedding_semaphore = None


@asynccontextmanager
async def rate_limited_openai_call():
    """Context manager for rate-limited OpenAI API calls."""
    _ensure_rate_limiters()
    async with _openai_semaphore:
        logger.debug("Acquired OpenAI API semaphore")
        try:
            yield get_openai_client()
        finally:
            logger.debug("Released OpenAI API semaphore")


@asynccontextmanager
async def rate_limited_embedding_call():
    """Context manager for rate-limited OpenAI embedding API calls."""
    _ensure_rate_limiters()
    async with _embedding_semaphore:
        logger.debug("Acquired OpenAI embedding semaphore")
        try:
            yield get_openai_client()
        finally:
            logger.debug("Released OpenAI embedding semaphore")


async def safe_openai_call(call_func, *args, **kwargs):
    """
    Run an OpenAI call with request-scoped credentials and rate limiting.

    Returns the API response, or None when credentials are unavailable or the
    call fails.
    """
    try:
        async with rate_limited_openai_call() as client:
            if client is None:
                logger.error("Request-scoped OpenAI client not available")
                return None

            result = await call_func(client, *args, **kwargs)
            logger.debug(f"OpenAI API call successful: {call_func.__name__}")
            return result

    except Exception as e:
        logger.error(
            "OpenAI API call failed: operation=%s error_type=%s",
            call_func.__name__,
            type(e).__name__,
        )
        return None


async def safe_embedding_call(call_func, *args, **kwargs):
    """
    Run an embedding call with request-scoped credentials and rate limiting.

    Returns the API response, or None when credentials are unavailable or the
    call fails.
    """
    try:
        async with rate_limited_embedding_call() as client:
            if client is None:
                logger.error("Request-scoped OpenAI client not available")
                return None

            result = await call_func(client, *args, **kwargs)
            logger.debug(f"OpenAI embedding call successful: {call_func.__name__}")
            return result

    except Exception as e:
        logger.error(
            "OpenAI embedding call failed: operation=%s error_type=%s",
            call_func.__name__,
            type(e).__name__,
        )
        return None
