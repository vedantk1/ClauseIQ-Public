"""Pin a local installation to its database name before startup writes."""
import json
import os
import stat
import tempfile
from pathlib import Path

from workspace import WORKSPACE_ID


class WorkspaceBindingError(RuntimeError):
    """A safe, actionable startup failure; never contains credential values."""


def _read_binding(path: Path) -> dict:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "r") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise ValueError("Not a regular file")
            value = json.loads(handle.read(4097))
        if (not isinstance(value, dict) or set(value) != {"version", "database", "collection_prefix"}
                or value["version"] != 1 or not isinstance(value["database"], str)
                or not value["database"] or not isinstance(value["collection_prefix"], str)):
            raise ValueError("Invalid binding")
        return value
    except FileNotFoundError:
        raise
    except (OSError, ValueError, TypeError):
        raise WorkspaceBindingError(
            "Cannot read local database-binding.json. Restore the workspace state; "
            "do not replace it or re-enter the API key to bypass this check."
        ) from None


async def ensure_workspace_database_binding(settings, database) -> None:
    """Refuse retargeting, preserving all database/credential state on failure.

    The marker deliberately stores only database name and collection prefix,
    not a URI, credential, machine identity or document content.
    """
    directory = Path(settings.workspace_state_dir)
    if not directory.is_absolute():
        directory = Path(__file__).resolve().parents[1] / directory
    path = directory / "database-binding.json"
    expected = {"version": 1, "database": settings.mongodb_database,
                "collection_prefix": settings.mongodb_collection_prefix}
    try:
        existing = _read_binding(path)
    except FileNotFoundError:
        # An older installation may have a credential file but no binding yet.
        # Do not bind that state to an empty/other database by accident. An
        # explicit key removal leaves a dated tombstone and remains legitimate.
        if (directory / "credential.key").exists():
            record = await database._get_collection("workspace_credentials").find_one(
                {"id": WORKSPACE_ID, "$or": [
                    {"encrypted_key": {"$exists": True, "$nin": ["", None]}},
                    {"updated_at": {"$exists": True, "$nin": ["", None]}},
                ]}, {"_id": 1})
            if not record:
                raise WorkspaceBindingError(
                    "Local credential state exists, but the selected database has no saved "
                    "credential or removal record. Check MONGODB_DATABASE and "
                    "MONGODB_COLLECTION_PREFIX before starting; no migration was performed."
                )
        try:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            descriptor, candidate = tempfile.mkstemp(prefix=".database-binding-", dir=directory)
            try:
                with os.fdopen(descriptor, "w") as handle:
                    json.dump(expected, handle, sort_keys=True)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    os.link(candidate, path)
                except FileExistsError:
                    pass  # Another starter won; validate its choice below.
            finally:
                os.unlink(candidate)
            existing = _read_binding(path)
        except OSError:
            raise WorkspaceBindingError("Cannot persist local database binding; startup stopped.") from None
    if existing != expected:
        raise WorkspaceBindingError(
            "Configured MongoDB database or collection prefix differs from this installation's "
            "database-binding.json. Restore the original configuration. For an intentionally "
            "separate installation, use separate workspace state and stores; do not delete "
            "the binding to bypass this check."
        )
