"""Privacy regressions for retained lifecycle and local health handlers."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from routers import health as health_router


@pytest.mark.parametrize("relative_path", ["main.py", "routers/health.py"])
def test_lifecycle_handlers_do_not_serialize_exception_details(relative_path):
    source = (Path(__file__).resolve().parents[1] / relative_path).read_text()

    assert "logger.exception(" not in source
    assert "exc_info=True" not in source
    assert "str(e)" not in source
    assert "str(error)" not in source


@pytest.mark.asyncio
async def test_database_health_errors_remain_generic(monkeypatch):
    private_detail = "PRIVATE_DATABASE_ERROR_SENTINEL"
    factory = SimpleNamespace(health_check=AsyncMock(side_effect=RuntimeError(private_detail)))
    monkeypatch.setattr(health_router, "get_database_factory", lambda: factory)

    response = await health_router.database_health(SimpleNamespace(state=SimpleNamespace()))

    assert response.success is False
    assert response.error["message"] == "Database health check failed"
    assert private_detail not in response.model_dump_json()
