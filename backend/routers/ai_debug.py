"""Administrator-only, content-safe backend diagnostic endpoints."""

import glob
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException

from config.logging import get_foundational_logger
from middleware.admin import get_admin_user
from utils.ai_debug_helper import (
    DebugLevel,
    ai_debug,
    get_system_diagnostics,
    sanitize_diagnostic_context,
)


logger = get_foundational_logger(__name__)
router = APIRouter(prefix="/ai-debug", tags=["AI Assistant Debug"])

_KNOWN_LOG_FILES = frozenset(
    {"ai_debug.log", "api.log", "app.log", "auth.log", "chat.log", "error.log"}
)
_LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")
_SAFE_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,79}$")
_TIMESTAMP_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,6})?(?:Z|[+-]\d{2}:?\d{2})?\b"
)


def _safe_identifier(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not _SAFE_IDENTIFIER_RE.fullmatch(candidate):
        return None
    return candidate


def _detect_level(line: str) -> Optional[str]:
    for level in _LOG_LEVELS:
        if re.search(rf"\b{level}\b", line):
            return level
    return None


def _extract_json_entry(line: str) -> Optional[Dict[str, Any]]:
    marker = "JSON: "
    marker_index = line.find(marker)
    if marker_index < 0:
        return None

    try:
        value = json.loads(line[marker_index + len(marker) :])
    except (json.JSONDecodeError, TypeError):
        return None
    return value if isinstance(value, dict) else None


def _summarize_log_line(line: str) -> Dict[str, Any]:
    """Extract only allowlisted metadata from a log line."""

    summary: Dict[str, Any] = {}
    structured_entry = _extract_json_entry(line)

    if structured_entry is not None:
        level = _safe_identifier(structured_entry.get("level"))
        if level in _LOG_LEVELS:
            summary["level"] = level

        event_type = _safe_identifier(structured_entry.get("event_type"))
        if event_type is not None:
            summary["event_type"] = event_type

        timestamp = structured_entry.get("timestamp")
        if isinstance(timestamp, str):
            timestamp_match = _TIMESTAMP_RE.search(timestamp)
            if timestamp_match:
                summary["timestamp"] = timestamp_match.group(0)

        context = sanitize_diagnostic_context(structured_entry.get("context"))
        if context:
            summary["context"] = context

        error = structured_entry.get("error")
        if isinstance(error, dict):
            error_type = _safe_identifier(error.get("type"))
            if error_type is not None:
                summary["error_type"] = error_type

    if "level" not in summary:
        level = _detect_level(line)
        if level is not None:
            summary["level"] = level

    if "timestamp" not in summary:
        timestamp_match = _TIMESTAMP_RE.search(line)
        if timestamp_match:
            summary["timestamp"] = timestamp_match.group(0)

    return summary


def _summarize_lines(lines: Iterable[str], limit: int) -> List[Dict[str, Any]]:
    summaries = [_summarize_log_line(line) for line in lines]
    return [summary for summary in summaries if summary][-limit:]


def _error_type(error: Exception) -> str:
    return _safe_identifier(error.__class__.__name__) or "Exception"


@router.get("/health-check")
async def ai_health_check(current_user: dict = Depends(get_admin_user)):
    """Return a content-free health snapshot."""

    del current_user
    try:
        diagnostics = get_system_diagnostics()
        system_health = diagnostics.get("system_health")
        if not isinstance(system_health, dict):
            raise RuntimeError("System diagnostics unavailable")

        memory_ok = system_health["memory_usage_percent"] < 90
        disk_ok = system_health["disk_usage_percent"] < 90
        cpu_ok = system_health["cpu_percent"] < 80
        overall_health = (
            "healthy" if all([memory_ok, disk_ok, cpu_ok]) else "degraded"
        )

        return {
            "status": overall_health,
            "timestamp": datetime.utcnow().isoformat(),
            "system_diagnostics": diagnostics,
            "health_indicators": {
                "memory_healthy": memory_ok,
                "disk_healthy": disk_ok,
                "cpu_healthy": cpu_ok,
            },
            "quick_summary": (
                f"System {overall_health} - "
                f"CPU: {system_health['cpu_percent']}%, "
                f"Memory: {system_health['memory_usage_percent']}%, "
                f"Disk: {system_health['disk_usage_percent']}%"
            ),
        }
    except Exception as error:
        ai_debug.log_system_event(
            event_type="HEALTH_CHECK_FAILED",
            level=DebugLevel.ERROR,
            message="Health check endpoint failed",
            error=error,
        )
        raise HTTPException(
            status_code=500, detail="Health check failed"
        ) from error


@router.get("/recent-errors")
async def get_recent_errors(
    hours: int = 1, current_user: dict = Depends(get_admin_user)
):
    """Summarize recent error levels without returning raw log content."""

    del current_user
    try:
        error_log_path = "logs/error.log"
        if not os.path.exists(error_log_path):
            return {
                "recent_errors": [],
                "error_count": 0,
                "time_window_hours": max(1, hours),
                "message": "No error log found",
            }

        with open(error_log_path, "r", encoding="utf-8", errors="replace") as log_file:
            lines = log_file.readlines()[-100:]

        error_lines = [
            line for line in lines if _detect_level(line) in {"ERROR", "CRITICAL"}
        ]
        recent_errors = _summarize_lines(error_lines, limit=20)

        return {
            "recent_errors": recent_errors,
            "error_count": len(error_lines),
            "time_window_hours": max(1, hours),
            "scan_limit": 100,
            "summary": f"Found {len(error_lines)} recent error entries",
        }
    except Exception as error:
        ai_debug.log_system_event(
            event_type="ERROR_RETRIEVAL_FAILED",
            level=DebugLevel.ERROR,
            message="Failed to retrieve recent errors",
            error=error,
        )
        raise HTTPException(
            status_code=500, detail="Error retrieval failed"
        ) from error


@router.get("/rag-status")
async def get_rag_status(current_user: dict = Depends(get_admin_user)):
    """Return RAG availability and content-free activity metadata."""

    del current_user
    try:
        ai_log_path = "logs/app.log"
        rag_lines: List[str] = []

        if os.path.exists(ai_log_path):
            with open(ai_log_path, "r", encoding="utf-8", errors="replace") as log_file:
                lines = log_file.readlines()[-200:]
            rag_lines = [line for line in lines if "rag" in line.lower()]

        rag_service_ok = True
        rag_error_type = None
        try:
            from services.rag_service import RAGService

            RAGService()
        except Exception as error:
            rag_service_ok = False
            rag_error_type = _error_type(error)

        return {
            "rag_service_importable": rag_service_ok,
            "rag_service_error_type": rag_error_type,
            "recent_rag_activity": _summarize_lines(rag_lines, limit=10),
            "activity_count": len(rag_lines),
            "summary": (
                f"RAG service {'OK' if rag_service_ok else 'ERROR'} - "
                f"{len(rag_lines)} recent activities"
            ),
        }
    except Exception as error:
        ai_debug.log_system_event(
            event_type="RAG_STATUS_CHECK_FAILED",
            level=DebugLevel.ERROR,
            message="RAG status check failed",
            error=error,
        )
        raise HTTPException(
            status_code=500, detail="RAG status check failed"
        ) from error


@router.get("/database-status")
async def get_database_status(current_user: dict = Depends(get_admin_user)):
    """Return database health without connection details or exception text."""

    del current_user
    try:
        from database.factory import get_database_factory

        db_factory = get_database_factory()
        db_healthy = await db_factory.health_check()

        test_operation_ok = True
        test_error_type = None
        collection_count = None
        try:
            database = await db_factory.get_database()
            collections = await database.list_collection_names()
            collection_count = len(collections)
        except Exception as error:
            test_operation_ok = False
            test_error_type = _error_type(error)

        return {
            "database_healthy": db_healthy,
            "test_operation_success": test_operation_ok,
            "test_error_type": test_error_type,
            "collections_accessible": test_operation_ok,
            "collection_count": collection_count,
            "summary": (
                "Database healthy"
                if db_healthy and test_operation_ok
                else "Database issues detected"
            ),
        }
    except Exception as error:
        ai_debug.log_system_event(
            event_type="DB_STATUS_CHECK_FAILED",
            level=DebugLevel.ERROR,
            message="Database status check failed",
            error=error,
        )
        return {
            "database_healthy": False,
            "error_type": _error_type(error),
            "summary": "Database status check failed",
        }


@router.get("/log-summary")
async def get_log_summary(current_user: dict = Depends(get_admin_user)):
    """Return log counts and sanitized recent-event metadata."""

    del current_user
    try:
        log_dir = "logs"
        summary: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(),
            "log_files": {},
            "total_errors": 0,
            "total_warnings": 0,
            "recent_activity": [],
        }

        if not os.path.exists(log_dir):
            return {"error": "Log directory not found", "summary": "No logs available"}

        for log_path in glob.glob(os.path.join(log_dir, "*.log")):
            filename = os.path.basename(log_path)
            if filename not in _KNOWN_LOG_FILES:
                continue

            file_stats = os.stat(log_path)
            with open(log_path, "r", encoding="utf-8", errors="replace") as log_file:
                lines = log_file.readlines()

            errors = sum(1 for line in lines if _detect_level(line) in {"ERROR", "CRITICAL"})
            warnings = sum(1 for line in lines if _detect_level(line) == "WARNING")

            summary["log_files"][filename] = {
                "size_mb": round(file_stats.st_size / (1024**2), 2),
                "line_count": len(lines),
                "error_count": errors,
                "warning_count": warnings,
                "last_modified": datetime.fromtimestamp(file_stats.st_mtime).isoformat(),
            }
            summary["total_errors"] += errors
            summary["total_warnings"] += warnings

            for event in _summarize_lines(lines[-5:], limit=5):
                event["source"] = filename
                summary["recent_activity"].append(event)

        summary["recent_activity"] = summary["recent_activity"][-20:]
        return {
            "log_summary": summary,
            "quick_analysis": (
                f"{summary['total_errors']} errors, "
                f"{summary['total_warnings']} warnings across "
                f"{len(summary['log_files'])} log files"
            ),
        }
    except Exception as error:
        ai_debug.log_system_event(
            event_type="LOG_SUMMARY_FAILED",
            level=DebugLevel.ERROR,
            message="Log summary generation failed",
            error=error,
        )
        raise HTTPException(
            status_code=500, detail="Log summary failed"
        ) from error


@router.post("/test-components")
async def test_system_components(current_user: dict = Depends(get_admin_user)):
    """Test major components without returning exception messages."""

    del current_user
    results: Dict[str, Any] = {
        "timestamp": datetime.utcnow().isoformat(),
        "component_tests": {},
        "overall_status": "unknown",
    }

    try:
        from database.factory import get_database_factory

        db_factory = get_database_factory()
        db_healthy = await db_factory.health_check()
        results["component_tests"]["database"] = {
            "status": "PASS" if db_healthy else "FAIL",
            "healthy": db_healthy,
        }
    except Exception as error:
        results["component_tests"]["database"] = {
            "status": "ERROR",
            "error_type": _error_type(error),
        }

    try:
        from services.rag_service import RAGService

        rag_service = RAGService()
        rag_available = await rag_service.is_available()
        results["component_tests"]["rag_service"] = {
            "status": "PASS" if rag_available else "FAIL",
            "available": rag_available,
        }
    except Exception as error:
        results["component_tests"]["rag_service"] = {
            "status": "ERROR",
            "error_type": _error_type(error),
        }

    try:
        from services.chat_service import get_chat_service

        chat_service = get_chat_service()
        chat_available = await chat_service.is_available()
        results["component_tests"]["chat_service"] = {
            "status": "PASS" if chat_available else "FAIL",
            "available": chat_available,
        }
    except Exception as error:
        results["component_tests"]["chat_service"] = {
            "status": "ERROR",
            "error_type": _error_type(error),
        }

    component_tests = results["component_tests"]
    passed_tests = [
        test for test in component_tests.values() if test["status"] == "PASS"
    ]

    if len(passed_tests) == len(component_tests):
        results["overall_status"] = "ALL SYSTEMS HEALTHY"
    elif passed_tests:
        results["overall_status"] = (
            f"PARTIAL: {len(passed_tests)}/{len(component_tests)} components healthy"
        )
    else:
        results["overall_status"] = "CRITICAL: All components failing"

    return results
