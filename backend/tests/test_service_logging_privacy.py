"""Privacy regressions for database, vector, and storage service diagnostics."""

import ast
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from database.interface import ConnectionConfig, DatabaseBackend, DatabaseError
from database import mongodb_adapter as mongodb_adapter_module
from database.mongodb_adapter import MongoDBAdapter
from routers import documents as documents_router
from services import document_service
from services import ai_service
from services.ai import client_manager


PRIVATE_CONTENT = "NOT_A_REAL_PRIVATE_CONTENT_SENTINEL"

BACKEND_DIR = Path(__file__).resolve().parents[1]
SERVICE_SOURCES = tuple(
    str(path.relative_to(BACKEND_DIR))
    for path in sorted(BACKEND_DIR.rglob("*.py"))
    if path.parts[-2] != "tests"
    and "venv" not in path.parts
    and "logs" not in path.parts
)

SENSITIVE_NAMES = {
    "admin_user_id",
    "clause_id",
    "content",
    "doc_id",
    "document_id",
    "document_text",
    "email",
    "enhanced_query",
    "file_id",
    "filename",
    "host",
    "client_ip",
    "final_query",
    "pdf_file_id",
    "query",
    "text",
    "to_email",
    "user_id",
    "workspace_id",
}


def _logger_or_print_call(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name):
        return node.func.id == "print"
    return (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "logger"
    )


def _direct_sensitive_value(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return node.id in SENSITIVE_NAMES
    if isinstance(node, ast.Compare):
        return False
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in {"len", "type"}:
            return False
    return any(_direct_sensitive_value(child) for child in ast.iter_child_nodes(node))


def _raw_exception_string(node: ast.AST) -> bool:
    # Inspect executable calls, not comments documenting why conversion is unsafe.
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == "str"
        and bool(node.args) and isinstance(node.args[0], ast.Name)
        and re.fullmatch(r"(?:e|exc|error|[A-Za-z_]+_error)", node.args[0].id) is not None
    )


def test_exception_string_guard_distinguishes_comments_from_calls():
    safe = ast.parse('# Never retain str(error).\nlogger.warning("Failure: %s", type(error).__name__)')
    assert not any(_raw_exception_string(node) for node in ast.walk(safe))
    for expression in ("str(error)", "str ( exc )", "str(provider_error)", "logger.warning(str(e))"):
        assert any(_raw_exception_string(node) for node in ast.walk(ast.parse(expression)))


@pytest.mark.parametrize("relative_path", SERVICE_SOURCES)
def test_service_logs_do_not_render_private_runtime_values(relative_path):
    source_path = BACKEND_DIR / relative_path
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert not any(_raw_exception_string(node) for node in ast.walk(tree))
    assert "query_preview" not in source
    assert "traceback.format_exc" not in source
    assert "exc_info=True" not in source

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _logger_or_print_call(node):
            continue
        for argument in node.args:
            values = (
                [part.value for part in argument.values if isinstance(part, ast.FormattedValue)]
                if isinstance(argument, ast.JoinedStr)
                else [argument]
            )
            assert not any(_direct_sensitive_value(value) for value in values), (
                f"{relative_path}:{node.lineno} logs a private runtime value"
            )


class _FailingCollection:
    async def find_one(self, _query):
        raise RuntimeError(PRIVATE_CONTENT)


class _FailingDatabase:
    def __getitem__(self, _name):
        return _FailingCollection()


@pytest.mark.asyncio
async def test_mongodb_errors_hide_driver_details_from_logs_and_callers():
    adapter = MongoDBAdapter(
        ConnectionConfig(
            backend=DatabaseBackend.MONGODB,
            uri="mongodb://localhost:27017",
            database="test",
        )
    )
    adapter.database = _FailingDatabase()

    with patch.object(
        mongodb_adapter_module.logger,
        "error",
    ) as mock_error:
        with pytest.raises(DatabaseError) as raised:
            await adapter.get_document("private-document", "local")

    assert str(raised.value) == "Failed to get document"
    assert PRIVATE_CONTENT not in repr(mock_error.call_args)
    assert "RuntimeError" in repr(mock_error.call_args)


@pytest.mark.asyncio
async def test_document_analysis_errors_hide_provider_details(monkeypatch, caplog):
    monkeypatch.setattr(client_manager, "is_ai_available", lambda: True)
    monkeypatch.setattr(
        ai_service,
        "detect_contract_type",
        AsyncMock(side_effect=RuntimeError(PRIVATE_CONTENT)),
    )

    with pytest.raises(RuntimeError) as raised:
        await document_service.process_document_with_llm(
            "private contract content",
            "private-contract.pdf",
        )

    assert str(raised.value) == "AI analysis failed"
    assert PRIVATE_CONTENT not in caplog.text






@pytest.mark.asyncio
async def test_document_route_errors_hide_storage_details(monkeypatch, caplog):
    class FailingService:
        async def get_document_summaries_for_workspace(self, _workspace_id):
            raise RuntimeError(PRIVATE_CONTENT)

    monkeypatch.setattr(
        documents_router,
        "get_document_service",
        lambda: FailingService(),
    )

    with pytest.raises(HTTPException) as raised:
        await documents_router.list_documents(workspace_id="local")

    assert raised.value.status_code == 500
    assert raised.value.detail == "Failed to retrieve documents"
    assert PRIVATE_CONTENT not in caplog.text
