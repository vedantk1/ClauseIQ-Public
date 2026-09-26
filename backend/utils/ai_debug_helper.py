"""Content-safe structured diagnostics for backend troubleshooting.

The diagnostic logger intentionally records only an explicit allowlist of
operational metadata. User prompts, document content, request bodies,
credentials, document/person identifiers, exception messages, and tracebacks
are never persisted. The server-generated HTTP ID can correlate safe events.
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Mapping, Optional

import psutil

from middleware.request_context import current_request_id


class DebugLevel(Enum):
    """Debug severity levels for diagnostic triage."""

    CRITICAL = "CRITICAL"
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"


_SAFE_STRING_KEYS = frozenset(
    {
        "step_name",
        "status",
        "endpoint",
        "method",
        "error_type",
        "operation",
        "collection",
        "model",
        "version",
        "platform",
    }
)

_SAFE_BOOLEAN_KEYS = frozenset(
    {
        "success",
        "available",
        "healthy",
        "rag_processed",
    }
)

_SAFE_NUMBER_KEYS = frozenset(
    {
        "duration_ms",
        "document_count",
        "message_length",
        "response_length",
        "sources_count",
        "processing_time_ms",
        "chunk_count",
        "chunks_found",
        "memory_usage_percent",
        "memory_usage_mb",
        "memory_available_gb",
        "disk_usage_percent",
        "disk_free_gb",
        "cpu_percent",
        "num_threads",
        "open_files",
        "connections",
        "redacted_field_count",
        "omitted_field_count",
    }
)

_SAFE_NUMBER_LIST_KEYS = frozenset({"similarity_scores", "load_average"})
_SAFE_CONTAINER_KEYS = frozenset(
    {"details", "system_health", "process_health", "python_info"}
)

_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "body",
    "content",
    "cookie",
    "credential",
    "details",
    "document_id",
    "email",
    "exception",
    "filename",
    "message",
    "password",
    "prompt",
    "query",
    "request_data",
    "response",
    "secret",
    "session_id",
    "token",
    "traceback",
    "user_id",
)

_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,79}$")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_identifier(value: Any) -> Optional[str]:
    """Return a bounded machine identifier, never arbitrary prose."""

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not _SAFE_IDENTIFIER_RE.fullmatch(candidate):
        return None
    return candidate


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS)


def sanitize_diagnostic_context(context: Any) -> Dict[str, Any]:
    """Reduce arbitrary context to a small, content-safe metadata allowlist.

    Unknown values are omitted. Sensitive values are not retained; only their
    count is recorded so operators can see that redaction occurred.
    """

    if not isinstance(context, Mapping):
        return {}

    sanitized: Dict[str, Any] = {}
    redacted_count = 0
    omitted_count = 0

    for raw_key, value in context.items():
        if not isinstance(raw_key, str):
            omitted_count += 1
            continue

        key = raw_key.lower()

        # ``details`` is a compatibility container used by existing callers.
        # Its contents are still subjected to the same allowlist.
        if key in _SAFE_CONTAINER_KEYS and isinstance(value, Mapping):
            nested = sanitize_diagnostic_context(value)
            if nested:
                sanitized[key] = nested
            continue

        if key in _SAFE_STRING_KEYS:
            safe_value = _safe_identifier(value)
            if safe_value is not None:
                sanitized[key] = safe_value
            else:
                redacted_count += 1
            continue

        if key in _SAFE_BOOLEAN_KEYS and isinstance(value, bool):
            sanitized[key] = value
            continue

        if (
            key in _SAFE_NUMBER_KEYS
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            sanitized[key] = value
            continue

        if key in _SAFE_NUMBER_LIST_KEYS and isinstance(value, (list, tuple)):
            safe_numbers = [
                item
                for item in value[:10]
                if isinstance(item, (int, float)) and not isinstance(item, bool)
            ]
            if safe_numbers:
                sanitized[key] = safe_numbers
            elif value:
                redacted_count += 1
            continue

        if _is_sensitive_key(key):
            redacted_count += 1
            continue

        omitted_count += 1

    if redacted_count:
        sanitized["redacted_field_count"] = redacted_count
    if omitted_count:
        sanitized["omitted_field_count"] = omitted_count

    return sanitized


class AIDebugLogger:
    """Structured logger that persists operational metadata only."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("ai_debug")

    def log_system_event(
        self,
        event_type: str,
        level: DebugLevel,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        error: Optional[Exception] = None,
        user_id: Optional[str] = None,
        request_id: Optional[str] = None,
    ) -> None:
        """Log an event without retaining user content or exception details."""

        # Do not treat a caller-provided identifier (possibly a paid-attempt ID
        # or user content) as the HTTP identity. Only middleware owns that ID.
        del message, user_id, request_id

        safe_event_type = _safe_identifier(event_type) or "UNSPECIFIED_EVENT"
        log_entry: Dict[str, Any] = {
            "timestamp": _utc_timestamp(),
            "event_type": safe_event_type,
            "level": level.value,
            "message": "Diagnostic event recorded",
            "context": sanitize_diagnostic_context(context),
        }
        if http_request_id := current_request_id():
            log_entry["request_id"] = http_request_id

        if error is not None:
            log_entry["error"] = {
                "type": _safe_identifier(error.__class__.__name__)
                or "Exception"
            }

        json_log = json.dumps(log_entry, default=str)
        if level == DebugLevel.CRITICAL:
            self.logger.critical(f"JSON: {json_log}")
        elif level == DebugLevel.ERROR:
            self.logger.error(f"JSON: {json_log}")
        elif level == DebugLevel.WARNING:
            self.logger.warning(f"JSON: {json_log}")
        elif level == DebugLevel.INFO:
            self.logger.info(f"JSON: {json_log}")
        else:
            self.logger.debug(f"JSON: {json_log}")

    def log_rag_pipeline_step(
        self,
        step_name: str,
        success: bool,
        duration_ms: float,
        details: Dict[str, Any],
        user_id: Optional[str] = None,
        document_id: Optional[str] = None,
        query: Optional[str] = None,
    ) -> None:
        """Log RAG status and timing without queries or document identifiers."""

        del document_id, query
        level = DebugLevel.INFO if success else DebugLevel.ERROR
        context = {
            "step_name": step_name,
            "success": success,
            "duration_ms": duration_ms,
            "details": details,
        }

        self.log_system_event(
            event_type="RAG_PIPELINE_STEP",
            level=level,
            message="RAG pipeline step completed",
            context=context,
            user_id=user_id,
        )

    def log_api_error(
        self,
        endpoint: Optional[str] = None,
        method: Optional[str] = None,
        error: Optional[Exception] = None,
        user_id: Optional[str] = None,
        request_data: Optional[Dict[str, Any]] = None,
        error_type: Optional[str] = None,
        message: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log API failure metadata; request data and prose are discarded."""

        del request_data, message
        resolved_error_type = error_type
        if resolved_error_type is None and error is not None:
            resolved_error_type = error.__class__.__name__

        context = {
            "endpoint": endpoint,
            "method": method,
            "error_type": resolved_error_type,
            "details": details or {},
        }

        self.log_system_event(
            event_type="API_ERROR",
            level=DebugLevel.ERROR,
            message="API request failed",
            context=context,
            error=error,
            user_id=user_id,
        )

    def log_database_operation(
        self,
        operation: str,
        collection: str,
        success: bool,
        duration_ms: float,
        error: Optional[Exception] = None,
        document_count: Optional[int] = None,
    ) -> None:
        """Log database operation metadata."""

        level = DebugLevel.INFO if success else DebugLevel.ERROR
        context = {
            "operation": operation,
            "collection": collection,
            "success": success,
            "duration_ms": duration_ms,
            "document_count": document_count,
        }

        self.log_system_event(
            event_type="DATABASE_OPERATION",
            level=level,
            message="Database operation completed",
            context=context,
            error=error,
        )

    def log_chat_error(
        self,
        error_type: str,
        document_id: str,
        user_id: str,
        details: str,
        session_id: Optional[str] = None,
        error: Optional[Exception] = None,
    ) -> None:
        """Log only the classified type of a chat error."""

        del document_id, details, session_id
        self.log_system_event(
            event_type="CHAT_ERROR",
            level=DebugLevel.ERROR,
            message="Chat operation failed",
            context={"error_type": error_type},
            error=error,
            user_id=user_id,
        )

    def log_chat_session_created(
        self,
        session_id: str,
        document_id: str,
        user_id: str,
    ) -> None:
        """Record session creation without retaining identifiers."""

        del session_id, document_id
        self.log_system_event(
            event_type="CHAT_SESSION_CREATED",
            level=DebugLevel.INFO,
            message="Chat session created",
            context={"status": "created"},
            user_id=user_id,
        )

    def log_chat_message_processed(
        self,
        session_id: str,
        document_id: str,
        user_id: str,
        message_length: int,
        response_length: int,
        sources_count: int,
        processing_time_ms: Optional[float] = None,
    ) -> None:
        """Log aggregate chat metrics without message content or identifiers."""

        del session_id, document_id
        context = {
            "status": "processed",
            "message_length": message_length,
            "response_length": response_length,
            "sources_count": sources_count,
            "processing_time_ms": processing_time_ms,
        }

        self.log_system_event(
            event_type="CHAT_MESSAGE_PROCESSED",
            level=DebugLevel.INFO,
            message="Chat message processed",
            context=context,
            user_id=user_id,
        )


def get_system_diagnostics() -> Dict[str, Any]:
    """Return a content-free process health snapshot."""

    try:
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        process = psutil.Process()

        return {
            "timestamp": _utc_timestamp(),
            "system_health": {
                "memory_usage_percent": memory.percent,
                "memory_available_gb": round(memory.available / (1024**3), 2),
                "disk_usage_percent": disk.percent,
                "disk_free_gb": round(disk.free / (1024**3), 2),
                "cpu_percent": psutil.cpu_percent(),
                "load_average": (
                    os.getloadavg() if hasattr(os, "getloadavg") else None
                ),
            },
            "process_health": {
                "memory_usage_mb": round(
                    process.memory_info().rss / (1024**2), 2
                ),
                "cpu_percent": process.cpu_percent(),
                "num_threads": process.num_threads(),
                "open_files": len(process.open_files()),
                "connections": len(process.connections()),
            },
            "python_info": {
                "version": (
                    f"{psutil.sys.version_info.major}."
                    f"{psutil.sys.version_info.minor}."
                    f"{psutil.sys.version_info.micro}"
                ),
                "platform": psutil.sys.platform,
            },
        }
    except Exception as error:
        return {
            "status": "unavailable",
            "error": "Failed to get diagnostics",
            "error_type": error.__class__.__name__,
            "timestamp": _utc_timestamp(),
        }


def log_startup_diagnostics() -> None:
    """Log content-free system state at startup."""

    diagnostics = get_system_diagnostics()
    AIDebugLogger().log_system_event(
        event_type="SYSTEM_STARTUP",
        level=DebugLevel.INFO,
        message="ClauseIQ backend starting up - system diagnostics captured",
        context=diagnostics,
    )


ai_debug = AIDebugLogger()
