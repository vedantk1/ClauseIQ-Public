"""Content-safe request, response, error, and security logging."""

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from middleware.api_standardization import create_error_response
from middleware.request_context import current_request_id, request_context

_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,79}$")
_SAFE_SECURITY_STRING_FIELDS = frozenset(
    {"error_type", "limit_type", "method", "reason", "status"}
)
_SAFE_SECURITY_NUMBER_FIELDS = frozenset(
    {"activity_count", "attempt_count", "limit", "status_code"}
)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_token(value: Any, fallback: str) -> str:
    if isinstance(value, str):
        candidate = value.strip()
        if _SAFE_TOKEN_RE.fullmatch(candidate):
            return candidate
    return fallback


def _safe_security_metadata(details: Any) -> Dict[str, Any]:
    """Reduce arbitrary security details to categorical operational metadata."""

    if not isinstance(details, Mapping):
        return {}

    metadata: Dict[str, Any] = {}
    redacted_count = 0

    for raw_key, value in details.items():
        if not isinstance(raw_key, str):
            redacted_count += 1
            continue

        key = raw_key.lower()
        if key in _SAFE_SECURITY_STRING_FIELDS:
            safe_value = _safe_token(value, "redacted")
            if safe_value != "redacted":
                metadata[key] = safe_value
            else:
                redacted_count += 1
            continue

        if (
            key in _SAFE_SECURITY_NUMBER_FIELDS
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            metadata[key] = value
            continue

        if key == "validation_results" and isinstance(value, Mapping):
            metadata["validation_match_count"] = sum(
                1 for matched in value.values() if matched is True
            )
            redacted_count += len(value)
            continue

        redacted_count += 1

    if redacted_count:
        metadata["redacted_field_count"] = redacted_count

    return metadata


class StructuredLogger:
    """Structured API logger that excludes request and user content."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("clauseiq_api")

    def log_request(
        self,
        request_id: str,
        request: Request,
        user_id: Optional[str] = None,
    ) -> None:
        """Log request lifecycle metadata without paths, headers, IPs, or IDs."""

        del user_id
        log_data = {
            "event": "request_start",
            "request_id": _safe_token(request_id, "unknown"),
            "method": _safe_token(request.method, "UNKNOWN"),
            "timestamp": _utc_timestamp(),
        }
        self.logger.info(json.dumps(log_data))

    def log_response(
        self,
        request_id: str,
        status_code: int,
        duration: float,
        response_size: int = 0,
    ) -> None:
        """Log aggregate response metadata."""

        log_data = {
            "event": "request_complete",
            "request_id": _safe_token(request_id, "unknown"),
            "status_code": status_code,
            "duration_ms": round(duration * 1000, 2),
            "response_size_bytes": response_size,
            "timestamp": _utc_timestamp(),
        }
        self.logger.info(json.dumps(log_data))

    def log_error(
        self,
        request_id: str,
        error: Exception,
        request: Request,
        user_id: Optional[str] = None,
    ) -> None:
        """Log only exception class and safe request lifecycle metadata."""

        del user_id
        log_data = {
            "event": "request_error",
            "request_id": _safe_token(request_id, "unknown"),
            "error_type": _safe_token(error.__class__.__name__, "Exception"),
            "method": _safe_token(request.method, "UNKNOWN"),
            "timestamp": _utc_timestamp(),
        }
        if isinstance(error, HTTPException):
            log_data["status_code"] = error.status_code
        self.logger.error(json.dumps(log_data))


structured_logger = StructuredLogger()


async def logging_middleware(request: Request, call_next):
    """Track request lifecycle without persisting request or user content."""
    with request_context(request) as request_id:
        return await _log_request(request, call_next, request_id)


async def _log_request(request: Request, call_next, request_id: str):
    start_time = time.perf_counter()

    structured_logger.log_request(request_id, request)

    request.state.start_time = start_time

    try:
        response = await call_next(request)
        duration = time.perf_counter() - start_time

        response_size = 0
        if hasattr(response, "body"):
            response_size = len(response.body)

        structured_logger.log_response(
            request_id,
            response.status_code,
            duration,
            response_size,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Correlation-ID"] = request_id
        response.headers["X-Response-Time"] = f"{duration * 1000:.2f}ms"
        return response
    except HTTPException as http_error:
        structured_logger.log_error(request_id, http_error, request)
        structured_logger.log_response(
            request_id,
            http_error.status_code,
            time.perf_counter() - start_time,
        )
        raise
    except Exception as error:
        structured_logger.log_error(request_id, error, request)
        duration = time.perf_counter() - start_time
        structured_logger.log_response(request_id, 500, duration)

        return JSONResponse(
            status_code=500,
            content=create_error_response(
                code="INTERNAL_SERVER_ERROR",
                message="An unexpected error occurred",
                correlation_id=request_id,
            ).model_dump(),
            headers={
                "X-Request-ID": request_id,
                "X-Correlation-ID": request_id,
                "X-Response-Time": f"{duration * 1000:.2f}ms",
            },
        )


class SecurityLogger:
    """Security event logger that records classifications, not identities."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("clauseiq_security")

    def log_suspicious_activity(
        self, event_type: str, details: Dict[str, Any]
    ) -> None:
        """Log a security classification and allowlisted aggregate metadata."""

        log_data = {
            "event": "security_alert",
            "type": _safe_token(event_type, "security_event"),
            "metadata": _safe_security_metadata(details),
            "timestamp": _utc_timestamp(),
        }
        if request_id := current_request_id():
            log_data["request_id"] = request_id
        self.logger.warning(json.dumps(log_data))

    def log_auth_failure(
        self,
        client_ip: str,
        attempted_email: str,
        reason: str = "authentication_failed",
    ) -> None:
        """Record an authentication-failure category without identity data."""

        del client_ip, attempted_email
        self.log_suspicious_activity("auth_failure", {"reason": reason})

    def log_rate_limit_hit(
        self, client_ip: str, endpoint: str, limit_type: str
    ) -> None:
        """Record a rate-limit category without IP or concrete URL values."""

        del client_ip, endpoint
        self.log_suspicious_activity(
            "rate_limit_exceeded", {"limit_type": limit_type}
        )

    def log_blocked_ip(self, client_ip: str, reason: str) -> None:
        """Record an IP-block category without persisting the IP address."""

        del client_ip
        self.log_suspicious_activity("ip_blocked", {"reason": reason})


security_logger = SecurityLogger()

__all__ = ["logging_middleware", "security_logger", "structured_logger"]
