"""Local database continuity guards; no real credentials or provider calls."""
import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from services.workspace_binding import ensure_workspace_database_binding, WorkspaceBindingError


@pytest.fixture
def binding(tmp_path):
    settings = SimpleNamespace(workspace_state_dir=str(tmp_path / "state"),
                               mongodb_database="original", mongodb_collection_prefix="")
    collection = SimpleNamespace(find_one=AsyncMock(return_value=None))
    database = SimpleNamespace(_get_collection=lambda name: collection)
    return settings, database, collection, Path(settings.workspace_state_dir) / "database-binding.json"


@pytest.mark.asyncio
async def test_binding_survives_restart_without_rewrite(binding):
    settings, database, collection, path = binding
    await ensure_workspace_database_binding(settings, database)
    original = path.read_bytes()
    modified = path.stat().st_mtime_ns
    await ensure_workspace_database_binding(settings, database)
    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == modified
    assert json.loads(original) == {"version": 1, "database": "original", "collection_prefix": ""}
    assert path.stat().st_mode & 0o777 == 0o600
    collection.find_one.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [("mongodb_database", "other"), ("mongodb_collection_prefix", "other_")])
async def test_retargeting_fails_without_rebinding_or_database_writes(binding, field, value):
    settings, database, collection, path = binding
    await ensure_workspace_database_binding(settings, database)
    original = path.read_bytes()
    setattr(settings, field, value)
    with pytest.raises(WorkspaceBindingError, match="differs"):
        await ensure_workspace_database_binding(settings, database)
    assert path.read_bytes() == original
    collection.find_one.assert_not_awaited()


@pytest.mark.asyncio
async def test_older_credential_state_cannot_be_bound_to_an_empty_database(binding):
    settings, database, collection, path = binding
    path.parent.mkdir()
    key = path.parent / "credential.key"
    key.write_text("synthetic-marker-not-an-encryption-key")
    with pytest.raises(WorkspaceBindingError, match="no saved credential"):
        await ensure_workspace_database_binding(settings, database)
    assert not path.exists()
    assert key.read_text() == "synthetic-marker-not-an-encryption-key"
    # Query only presence metadata: no key contents are read or projected.
    assert collection.find_one.call_args.args[1] == {"_id": 1}


@pytest.mark.asyncio
async def test_existing_credential_or_deliberate_removal_can_bootstrap_binding(binding):
    settings, database, collection, path = binding
    path.parent.mkdir()
    (path.parent / "credential.key").touch()
    collection.find_one.return_value = {"_id": "synthetic-record"}
    await ensure_workspace_database_binding(settings, database)
    assert path.exists()
    query = collection.find_one.call_args.args[0]
    assert query["id"] == "local"
    assert {"updated_at": {"$exists": True, "$nin": ["", None]}} in query["$or"]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["{broken", "[]", '{"version":2}', '{"version":1,"database":"","collection_prefix":""}'])
async def test_corrupt_binding_fails_closed_and_is_preserved(binding, raw):
    settings, database, _, path = binding
    path.parent.mkdir()
    path.write_text(raw)
    with pytest.raises(WorkspaceBindingError, match="Cannot read"):
        await ensure_workspace_database_binding(settings, database)
    assert path.read_text() == raw


@pytest.mark.asyncio
async def test_binding_symlinks_are_not_followed(binding):
    settings, database, _, path = binding
    path.parent.mkdir()
    target = path.parent / "other.json"
    target.write_text('{}')
    path.symlink_to(target)
    with pytest.raises(WorkspaceBindingError, match="Cannot read"):
        await ensure_workspace_database_binding(settings, database)
    assert target.read_text() == '{}'


@pytest.mark.asyncio
async def test_competing_starter_cannot_silently_choose_another_database(binding, monkeypatch):
    from services import workspace_binding
    settings, database, _, path = binding

    def competing_link(source, target):
        Path(target).write_text(json.dumps({"version": 1, "database": "other", "collection_prefix": ""}))
        raise FileExistsError()

    monkeypatch.setattr(workspace_binding.os, "link", competing_link)
    with pytest.raises(WorkspaceBindingError, match="differs"):
        await ensure_workspace_database_binding(settings, database)
    assert json.loads(path.read_text())["database"] == "other"
    assert not list(path.parent.glob(".database-binding-*"))


def test_startup_checks_binding_before_migration_credentials_or_cleanup():
    tree = ast.parse((Path(__file__).parents[1] / "main.py").read_text())
    lifecycle = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "lifespan")
    calls = {node.func.id: node.lineno for node in ast.walk(lifecycle)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert calls["ensure_workspace_database_binding"] < calls["initialize_workspace"]
    assert calls["ensure_workspace_database_binding"] < calls["get_workspace_service"]
    assert calls["ensure_workspace_database_binding"] < calls["run_startup_cleanup"]
