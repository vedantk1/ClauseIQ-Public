"""Non-destructive, restartable migration from account ownership to one workspace.

The application must finish this preflight before serving local data. Original
owner fields, accounts, credentials, document IDs, and file pointers are kept.
An ambiguous legacy installation requires an explicit operator decision; it is
never silently combined into the local workspace.
"""
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from qdrant_client import AsyncQdrantClient

from config.environments import get_environment_config
from database.factory import DatabaseFactory
from workspace import WORKSPACE_ID


MIGRATION_ID = "local-workspace-v1"


class WorkspaceMigrationError(RuntimeError):
    """An actionable startup failure that contains no document or account data."""


def _inspect_scope(value: dict, owners: set[str], *, require_owner: bool = True) -> None:
    workspace_id = value.get("workspace_id")
    user_id = value.get("user_id")
    if workspace_id is not None and workspace_id != WORKSPACE_ID:
        raise WorkspaceMigrationError(
            "Workspace migration stopped: data belongs to another workspace. "
            "Back up the installation and select the data to import explicitly."
        )
    if user_id is not None:
        if not isinstance(user_id, str) or not user_id.strip():
            raise WorkspaceMigrationError("Workspace migration stopped: malformed legacy ownership.")
        owners.add(user_id)
    if require_owner and workspace_id != WORKSPACE_ID and not user_id:
        raise WorkspaceMigrationError(
            "Workspace migration stopped: unowned legacy data was found. "
            "Back up the installation and resolve its ownership before retrying."
        )


def _inspect_nested(value: Any, owners: set[str]) -> None:
    if isinstance(value, dict):
        if "user_id" in value or "workspace_id" in value:
            _inspect_scope(value, owners, require_owner=False)
        for child in value.values():
            _inspect_nested(child, owners)
    elif isinstance(value, list):
        for child in value:
            _inspect_nested(child, owners)


def _migrated_context(value: Any, *, scope_root: bool = False) -> Any:
    """Add a workspace marker while preserving every original field."""
    value = deepcopy(value)
    if isinstance(value, dict):
        for key, child in list(value.items()):
            value[key] = _migrated_context(child)
        if scope_root or "user_id" in value:
            value["workspace_id"] = WORKSPACE_ID
    elif isinstance(value, list):
        value = [_migrated_context(child, scope_root=scope_root) for child in value]
    return value


async def initialize_workspace(db=None, vector_client=None) -> dict[str, Any]:
    """Preflight all stores, then migrate a zero-or-one-owner installation.

    Returns only workspace_id, legacy_user_id, and migrated. The caller may use
    legacy_user_id internally to copy a legacy encrypted key; do not expose it
    through the workspace API or logs. Optional clients support isolated tests.
    """
    db = db if db is not None else await DatabaseFactory.get_database()
    config = get_environment_config().qdrant
    owns_client = vector_client is None
    if owns_client:
        vector_client = AsyncQdrantClient(
            host=config.host, port=config.port, api_key=config.api_key, timeout=10
        )
    try:
        return await _initialize_workspace(db, vector_client, config.collection_name)
    except WorkspaceMigrationError:
        raise
    except Exception:
        raise WorkspaceMigrationError(
            "Workspace initialization could not finish. Check MongoDB and Qdrant, "
            "then restart. Existing data is preserved and partial migration is safe to retry."
        ) from None
    finally:
        if owns_client:
            await vector_client.close()


async def _initialize_workspace(db, vector_client, vector_collection: str) -> dict[str, Any]:
    markers = db._get_collection("workspace_migrations")
    marker = await markers.find_one({"id": MIGRATION_ID})
    owners: set[str] = set()
    if marker and marker.get("legacy_user_id"):
        owners.add(marker["legacy_user_id"])
    plans: list[tuple[Any, Any, dict]] = []
    document_ids: set[str] = set()
    file_references: dict[str, str] = {}

    # Include empty accounts: their saved credentials must not be arbitrarily
    # selected even when only one account happens to own a document.
    async for account in db._get_collection("users").find({}, {"id": 1}):
        owner = account.get("id")
        if not isinstance(owner, str) or not owner.strip():
            raise WorkspaceMigrationError("Workspace migration stopped: malformed legacy account.")
        owners.add(owner)

    documents = db._get_collection("documents")
    async for document in documents.find({}, {
        "id": 1, "pdf_file_id": 1,
        "user_id": 1, "workspace_id": 1, "chat_session": 1, "chat_sessions": 1,
    }):
        _inspect_scope(document, owners)
        document_id = document.get("id")
        if not isinstance(document_id, str) or not document_id or document_id in document_ids:
            raise WorkspaceMigrationError(
                "Workspace migration stopped: missing or duplicate document identity. "
                "Back up the installation and resolve these records before retrying."
            )
        document_ids.add(document_id)
        if document.get("pdf_file_id"):
            file_id = str(document["pdf_file_id"])
            if file_id in file_references:
                raise WorkspaceMigrationError("Workspace migration stopped: multiple documents reference the same PDF.")
            file_references[file_id] = document_id
        updates = {"workspace_id": WORKSPACE_ID} if document.get("workspace_id") != WORKSPACE_ID else {}
        for field in ("chat_session", "chat_sessions"):
            if document.get(field) is not None:
                _inspect_nested(document[field], owners)
                context = document[field]
                if field == "chat_sessions" and isinstance(context, dict):
                    if not all(isinstance(session, dict) for session in context.values()):
                        raise WorkspaceMigrationError("Workspace migration stopped: malformed legacy chat sessions.")
                    migrated = {key: _migrated_context(session, scope_root=True) for key, session in context.items()}
                elif field == "chat_session" and isinstance(context, dict):
                    migrated = _migrated_context(context, scope_root=True)
                elif field == "chat_sessions" and isinstance(context, list) and all(isinstance(session, dict) for session in context):
                    migrated = _migrated_context(context, scope_root=True)
                else:
                    raise WorkspaceMigrationError("Workspace migration stopped: malformed legacy chat sessions.")
                if migrated != document[field]:
                    updates[field] = migrated
        if updates:
            plans.append((documents, document["_id"], updates))

    interactions = db._get_collection("user_interactions")
    async for record in interactions.find({}, {"user_id": 1, "workspace_id": 1, "interactions": 1}):
        _inspect_scope(record, owners)
        context = record.get("interactions")
        if context is not None and (
            not isinstance(context, dict) or not all(isinstance(value, dict) for value in context.values())
        ):
            raise WorkspaceMigrationError("Workspace migration stopped: malformed legacy document interactions.")
        _inspect_nested(context, owners)
        updates = {"workspace_id": WORKSPACE_ID} if record.get("workspace_id") != WORKSPACE_ID else {}
        migrated = {
            key: _migrated_context(value, scope_root=True)
            for key, value in (context or {}).items()
        }
        if context is not None and migrated != context:
            updates["interactions"] = migrated
        if updates:
            plans.append((interactions, record["_id"], updates))

    # GridFS uses a fixed bucket, not the configurable ordinary-collection prefix.
    files = db.database["pdf_files.files"]
    async for record in files.find({}, {"metadata": 1}):
        metadata = record.get("metadata") or {}
        _inspect_scope(metadata, owners)
        updates = {}
        if metadata.get("workspace_id") != WORKSPACE_ID:
            updates["metadata.workspace_id"] = WORKSPACE_ID
        referencing_document = file_references.get(str(record["_id"]))
        if referencing_document:
            if metadata.get("document_id") and metadata["document_id"] != referencing_document:
                raise WorkspaceMigrationError("Workspace migration stopped: a PDF pointer conflicts with its document metadata.")
            if not metadata.get("document_id"):
                updates["metadata.document_id"] = referencing_document
        if updates:
            plans.append((files, record["_id"], updates))

    # Do not call the normal vector-service initializer: it creates a collection
    # and indexes, which would be a write before preflight has succeeded.
    collections = await vector_client.get_collections()
    collection_names = {collection.name for collection in collections.collections}
    # Earlier releases ignored QDRANT_COLLECTION and always used this name.
    # A newly honored override must not strand that existing vector library.
    if vector_collection != "clauseiq-vectors" and "clauseiq-vectors" in collection_names:
        legacy_collection = await vector_client.get_collection("clauseiq-vectors")
        if legacy_collection.points_count:
            raise WorkspaceMigrationError(
                "Workspace migration stopped: existing vectors use the legacy collection. "
                "Set QDRANT_COLLECTION=clauseiq-vectors to preserve this library, or "
                "explicitly migrate it before choosing another collection."
            )
    vector_ids = []
    has_collection = vector_collection in collection_names
    if has_collection:
        offset = None
        while True:
            points, offset = await vector_client.scroll(
                collection_name=vector_collection,
                limit=256,
                offset=offset,
                with_payload=["user_id", "workspace_id"],
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                _inspect_scope(payload, owners)
                if payload.get("workspace_id") != WORKSPACE_ID:
                    vector_ids.append(point.id)
            if offset is None:
                break

    if len(owners) > 1:
        raise WorkspaceMigrationError(
            "Workspace migration stopped: multiple legacy accounts or owners were found. "
            "No migration changes were made. Back up this installation and explicitly "
            "select one account's data for a separate local workspace."
        )
    legacy_user_id = next(iter(owners), None)
    # All stores have now been inspected. These are additive, idempotent writes;
    # interrupted runs are re-inspected and safely resume on next startup.
    if not marker:
        retention = await db._get_collection("system_config").find_one({"key": "document_auto_delete"})
        await markers.update_one({"id": MIGRATION_ID}, {"$setOnInsert": {
            "id": MIGRATION_ID,
            "legacy_user_id": legacy_user_id,
            "previous_retention": retention,
            "status": "pending",
            "started_at": datetime.now(timezone.utc).isoformat(),
        }}, upsert=True)
    if not marker or marker.get("status") != "complete":
        # Old installations enabled expiry by default. It must not run merely
        # because an operator opened the new personal library.
        await db._get_collection("system_config").update_one(
            {"key": "document_auto_delete"},
            {"$set": {"key": "document_auto_delete", "enabled": False, "days": 0}},
            upsert=True,
        )
    for collection, record_id, updates in plans:
        await collection.update_one({"_id": record_id}, {"$set": updates})
    for start in range(0, len(vector_ids), 256):
        await vector_client.set_payload(
            collection_name=vector_collection,
            payload={"workspace_id": WORKSPACE_ID},
            points=vector_ids[start:start + 256],
            wait=True,
        )
    migrated = bool(plans or vector_ids or not marker or marker.get("status") != "complete")
    if has_collection and migrated:
        await vector_client.create_payload_index(
            collection_name=vector_collection, field_name="workspace_id", field_schema="keyword", wait=True
        )
    if migrated:
        await markers.update_one({"id": MIGRATION_ID}, {"$set": {
            "status": "complete",
            "legacy_user_id": legacy_user_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }})
    return {"workspace_id": WORKSPACE_ID, "legacy_user_id": legacy_user_id, "migrated": migrated}
