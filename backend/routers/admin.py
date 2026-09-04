"""
Admin portal routes for user and document management.
All endpoints require admin access (email in ADMIN_EMAILS env var).
"""
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, Query, Body
from pydantic import BaseModel, EmailStr, Field

from database.service import get_document_service
from middleware.admin import get_admin_user
from middleware.api_standardization import APIResponse, create_error_response
from auth import get_password_hash, validate_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


def _log_admin_exception(
    operation: str,
    error: Exception,
    level: int = logging.ERROR,
) -> None:
    """Log an operation label and exception class without exception content."""
    safe_operation = (
        operation
        if isinstance(operation, str)
        and operation.replace("_", "").isalnum()
        else "operation"
    )
    logger.log(
        level,
        "Admin operation failed: operation=%s error_type=%s",
        safe_operation,
        error.__class__.__name__,
    )


def _sanitize_operation_errors(
    errors: Any,
    stable_message: str,
) -> List[str]:
    """Preserve failure count without returning service exception messages."""
    if not isinstance(errors, list):
        return []
    return [stable_message for _ in errors]


# ================== Response Models ==================

class AdminStats(BaseModel):
    user_count: int
    document_count: int
    recent_documents_7d: int
    recent_users_7d: int
    contract_type_breakdown: List[Dict[str, Any]]


class UserListItem(BaseModel):
    id: str
    email: str
    full_name: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    preferred_model: Optional[str] = None


class UserDetail(UserListItem):
    document_count: int
    recent_documents: List[Dict[str, Any]]


class DocumentListItem(BaseModel):
    id: str
    user_id: str
    filename: str
    contract_type: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    has_pdf_file: Optional[bool] = None
    rag_processed: Optional[bool] = None
    ready_for_chat: Optional[bool] = None


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    limit: int
    offset: int
    has_more: bool


class DeleteUserResult(BaseModel):
    user_deleted: bool
    documents_deleted: int
    errors: List[str]


# ================== Request Models ==================

class CreateUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=8)


class UpdateUserRequest(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    password: Optional[str] = Field(None, min_length=8)
    preferred_model: Optional[str] = None


class BulkDeleteRequest(BaseModel):
    ids: List[str] = Field(..., min_items=1)


class BulkDeleteResult(BaseModel):
    deleted_count: int
    failed_ids: List[str]
    errors: List[str]


class CollectionInfo(BaseModel):
    name: str
    document_count: int
    indexes: List[Dict[str, Any]]
    sample_document: Optional[Dict[str, Any]] = None


class DatabaseSchema(BaseModel):
    database_name: str
    collections: List[CollectionInfo]
    total_size_mb: Optional[float] = None


class AuditLogEntry(BaseModel):
    timestamp: str
    level: str
    message: str
    source: Optional[str] = None
    user_id: Optional[str] = None
    action: Optional[str] = None


# ================== Endpoints ==================

@router.get("/stats", response_model=APIResponse[AdminStats])
async def get_admin_stats(admin_user: dict = Depends(get_admin_user)):
    """Get admin dashboard statistics."""
    try:
        service = get_document_service()
        stats = await service.get_admin_stats()

        return APIResponse(
            success=True,
            data=AdminStats(**stats),
            message="Admin stats retrieved successfully"
        )
    except Exception as error:
        _log_admin_exception("get_admin_stats", error)
        return create_error_response(
            code="ADMIN_STATS_FAILED",
            message="Failed to get admin stats"
        )


@router.get("/users", response_model=APIResponse[PaginatedResponse])
async def list_users(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None, description="Search by email or name"),
    admin_user: dict = Depends(get_admin_user)
):
    """List all users with pagination and search."""
    try:
        service = get_document_service()
        users, total = await service.list_all_users(limit=limit, offset=offset, search=search)

        # Convert to response format
        user_items = [
            UserListItem(
                id=u.get("id", ""),
                email=u.get("email", ""),
                full_name=u.get("full_name", ""),
                created_at=u.get("created_at"),
                updated_at=u.get("updated_at"),
                preferred_model=u.get("preferred_model")
            ).model_dump()
            for u in users
        ]

        return APIResponse(
            success=True,
            data=PaginatedResponse(
                items=user_items,
                total=total,
                limit=limit,
                offset=offset,
                has_more=(offset + limit) < total
            ),
            message="Users retrieved successfully"
        )
    except Exception as error:
        _log_admin_exception("list_users", error)
        return create_error_response(
            code="LIST_USERS_FAILED",
            message="Failed to list users"
        )


@router.get("/users/{user_id}", response_model=APIResponse[UserDetail])
async def get_user_detail(
    user_id: str,
    admin_user: dict = Depends(get_admin_user)
):
    """Get detailed user information including document summary."""
    try:
        service = get_document_service()
        user = await service.get_user_with_documents_admin(user_id)

        if not user:
            return create_error_response(
                code="USER_NOT_FOUND",
                message="User not found"
            )

        return APIResponse(
            success=True,
            data=UserDetail(
                id=user.get("id", ""),
                email=user.get("email", ""),
                full_name=user.get("full_name", ""),
                created_at=user.get("created_at"),
                updated_at=user.get("updated_at"),
                preferred_model=user.get("preferred_model"),
                document_count=user.get("document_count", 0),
                recent_documents=user.get("recent_documents", [])
            ),
            message="User details retrieved successfully"
        )
    except Exception as error:
        _log_admin_exception("get_user_detail", error)
        return create_error_response(
            code="GET_USER_FAILED",
            message="Failed to get user details"
        )


@router.delete("/users/{user_id}", response_model=APIResponse[DeleteUserResult])
async def delete_user(
    user_id: str,
    admin_user: dict = Depends(get_admin_user)
):
    """Delete user and all their data (documents, RAG data, files)."""
    try:
        # Prevent admin from deleting themselves
        if user_id == admin_user.get("id"):
            return create_error_response(
                code="CANNOT_DELETE_SELF",
                message="Admin cannot delete themselves"
            )

        service = get_document_service()
        result = await service.delete_user_cascade(user_id, admin_user.get("id"))

        if not result["user_deleted"] and not result["documents_deleted"]:
            return create_error_response(
                code="USER_NOT_FOUND",
                message="User not found or already deleted"
            )

        return APIResponse(
            success=True,
            data=DeleteUserResult(
                **{
                    **result,
                    "errors": _sanitize_operation_errors(
                        result.get("errors"),
                        "Related cleanup failed",
                    ),
                }
            ),
            message="User and associated data deleted successfully"
        )
    except ValueError as error:
        _log_admin_exception("delete_user", error)
        return create_error_response(
            code="DELETE_USER_FAILED",
            message="Failed to delete user"
        )
    except Exception as error:
        _log_admin_exception("delete_user", error)
        return create_error_response(
            code="DELETE_USER_FAILED",
            message="Failed to delete user"
        )


@router.get("/documents", response_model=APIResponse[PaginatedResponse])
async def list_documents(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user_id: Optional[str] = Query(default=None, description="Filter by user ID"),
    search: Optional[str] = Query(default=None, description="Search by filename or contract type"),
    admin_user: dict = Depends(get_admin_user)
):
    """List all documents with pagination and filters."""
    try:
        service = get_document_service()
        documents, total = await service.list_all_documents_admin(
            limit=limit,
            offset=offset,
            user_id_filter=user_id,
            search=search
        )

        # Convert to response format
        doc_items = [
            DocumentListItem(
                id=d.get("id", ""),
                user_id=d.get("user_id", ""),
                filename=d.get("filename", ""),
                contract_type=d.get("contract_type"),
                created_at=d.get("created_at"),
                updated_at=d.get("updated_at"),
                has_pdf_file=d.get("has_pdf_file"),
                rag_processed=d.get("rag_processed"),
                ready_for_chat=d.get("ready_for_chat")
            ).model_dump()
            for d in documents
        ]

        return APIResponse(
            success=True,
            data=PaginatedResponse(
                items=doc_items,
                total=total,
                limit=limit,
                offset=offset,
                has_more=(offset + limit) < total
            ),
            message="Documents retrieved successfully"
        )
    except Exception as error:
        _log_admin_exception("list_documents", error)
        return create_error_response(
            code="LIST_DOCUMENTS_FAILED",
            message="Failed to list documents"
        )


@router.delete("/documents/{doc_id}", response_model=APIResponse[dict])
async def delete_document(
    doc_id: str,
    user_id: str = Query(..., description="User ID who owns the document"),
    admin_user: dict = Depends(get_admin_user)
):
    """Delete a specific document (requires user_id for proper cleanup)."""
    try:
        service = get_document_service()
        success = await service.delete_document_admin(doc_id, user_id)

        if not success:
            return create_error_response(
                code="DOCUMENT_NOT_FOUND",
                message="Document not found or already deleted"
            )

        logger.info("Admin operation completed: operation=delete_document")

        return APIResponse(
            success=True,
            data={"deleted": True, "document_id": doc_id},
            message="Document deleted successfully"
        )
    except Exception as error:
        _log_admin_exception("delete_document", error)
        return create_error_response(
            code="DELETE_DOCUMENT_FAILED",
            message="Failed to delete document"
        )


@router.get("/check-access", response_model=APIResponse[dict])
async def check_admin_access(admin_user: dict = Depends(get_admin_user)):
    """Check if current user has admin access. Used by frontend to show/hide admin UI."""
    return APIResponse(
        success=True,
        data={
            "is_admin": True,
            "email": admin_user.get("email"),
            "user_id": admin_user.get("id")
        },
        message="Admin access confirmed"
    )


# ================== User CRUD Operations ==================

@router.post("/users", response_model=APIResponse[UserListItem])
async def create_user(
    request: CreateUserRequest,
    admin_user: dict = Depends(get_admin_user)
):
    """Create a new user (admin only)."""
    try:
        # Validate password strength
        if not validate_password(request.password):
            return create_error_response(
                code="WEAK_PASSWORD",
                message="Password must be at least 8 characters with letters and numbers"
            )

        service = get_document_service()

        # Check if user already exists
        existing_user = await service.get_user_by_email(request.email)
        if existing_user:
            return create_error_response(
                code="USER_EXISTS",
                message="A user with this email already exists"
            )

        # Create user
        import uuid
        user_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()

        user_data = {
            "id": user_id,
            "email": request.email.lower(),
            "full_name": request.full_name,
            "hashed_password": get_password_hash(request.password),
            "created_at": now,
            "updated_at": now,
            "preferred_model": "gpt-5"
        }

        await service.create_user(user_data)

        logger.info("Admin operation completed: operation=create_user")

        return APIResponse(
            success=True,
            data=UserListItem(
                id=user_id,
                email=request.email.lower(),
                full_name=request.full_name,
                created_at=now,
                updated_at=now,
                preferred_model="gpt-4.1"
            ),
            message="User created successfully"
        )
    except Exception as error:
        _log_admin_exception("create_user", error)
        return create_error_response(
            code="CREATE_USER_FAILED",
            message="Failed to create user"
        )


@router.put("/users/{user_id}", response_model=APIResponse[UserListItem])
async def update_user(
    user_id: str,
    request: UpdateUserRequest,
    admin_user: dict = Depends(get_admin_user)
):
    """Update an existing user (admin only)."""
    try:
        service = get_document_service()

        # Get existing user
        user = await service.get_user_by_id(user_id)
        if not user:
            return create_error_response(
                code="USER_NOT_FOUND",
                message="User not found"
            )

        # Build update data
        update_data = {"updated_at": datetime.utcnow().isoformat()}

        if request.email is not None:
            # Check if email is already taken by another user
            existing = await service.get_user_by_email(request.email)
            if existing and existing.get("id") != user_id:
                return create_error_response(
                    code="EMAIL_TAKEN",
                    message="This email is already in use by another user"
                )
            update_data["email"] = request.email.lower()

        if request.full_name is not None:
            update_data["full_name"] = request.full_name

        if request.password is not None:
            if not validate_password(request.password):
                return create_error_response(
                    code="WEAK_PASSWORD",
                    message="Password must be at least 8 characters with letters and numbers"
                )
            update_data["hashed_password"] = get_password_hash(request.password)

        if request.preferred_model is not None:
            update_data["preferred_model"] = request.preferred_model

        # Update user
        success = await service.update_user(user_id, update_data)

        if not success:
            return create_error_response(
                code="UPDATE_FAILED",
                message="Failed to update user"
            )

        # Get updated user
        updated_user = await service.get_user_by_id(user_id)

        logger.info("Admin operation completed: operation=update_user")

        return APIResponse(
            success=True,
            data=UserListItem(
                id=updated_user.get("id", ""),
                email=updated_user.get("email", ""),
                full_name=updated_user.get("full_name", ""),
                created_at=updated_user.get("created_at"),
                updated_at=updated_user.get("updated_at"),
                preferred_model=updated_user.get("preferred_model")
            ),
            message="User updated successfully"
        )
    except Exception as error:
        _log_admin_exception("update_user", error)
        return create_error_response(
            code="UPDATE_USER_FAILED",
            message="Failed to update user"
        )


# ================== Bulk Operations ==================

@router.post("/users/bulk-delete", response_model=APIResponse[BulkDeleteResult])
async def bulk_delete_users(
    request: BulkDeleteRequest,
    admin_user: dict = Depends(get_admin_user)
):
    """Delete multiple users and all their data."""
    deleted_count = 0
    failed_ids = []
    errors = []

    for user_id in request.ids:
        try:
            # Prevent admin from deleting themselves
            if user_id == admin_user.get("id"):
                failed_ids.append(user_id)
                errors.append("Cannot delete the current administrator")
                continue

            service = get_document_service()
            result = await service.delete_user_cascade(user_id, admin_user.get("id"))

            if result["user_deleted"]:
                deleted_count += 1
            else:
                failed_ids.append(user_id)
                if result.get("errors"):
                    errors.append("User deletion failed")
        except Exception as error:
            failed_ids.append(user_id)
            errors.append("User deletion failed")
            _log_admin_exception("bulk_delete_user", error)

    logger.info(
        "Admin operation completed: operation=bulk_delete_users deleted_count=%s",
        deleted_count,
    )

    return APIResponse(
        success=True,
        data=BulkDeleteResult(
            deleted_count=deleted_count,
            failed_ids=failed_ids,
            errors=errors
        ),
        message=f"Deleted {deleted_count} users"
    )


@router.post("/documents/bulk-delete", response_model=APIResponse[BulkDeleteResult])
async def bulk_delete_documents(
    request: BulkDeleteRequest = Body(...),
    user_id: str = Query(..., description="User ID who owns the documents"),
    admin_user: dict = Depends(get_admin_user)
):
    """Delete multiple documents."""
    deleted_count = 0
    failed_ids = []
    errors = []

    service = get_document_service()

    for doc_id in request.ids:
        try:
            success = await service.delete_document_admin(doc_id, user_id)
            if success:
                deleted_count += 1
            else:
                failed_ids.append(doc_id)
        except Exception as error:
            failed_ids.append(doc_id)
            errors.append("Document deletion failed")
            _log_admin_exception("bulk_delete_document", error)

    logger.info(
        "Admin operation completed: operation=bulk_delete_documents deleted_count=%s",
        deleted_count,
    )

    return APIResponse(
        success=True,
        data=BulkDeleteResult(
            deleted_count=deleted_count,
            failed_ids=failed_ids,
            errors=errors
        ),
        message=f"Deleted {deleted_count} documents"
    )


# ================== Database Schema Viewer ==================

def sanitize_mongo_value(value, max_length: int = 200):
    """Describe a MongoDB value's shape without returning its content."""
    from bson import ObjectId

    del max_length  # Retained for compatibility with older internal callers.

    if isinstance(value, ObjectId):
        return "[object_id]"
    if isinstance(value, dict):
        return {str(key): sanitize_mongo_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return {
            "type": "array",
            "length": len(value),
            "item_schema": sanitize_mongo_value(value[0]) if value else None,
        }
    if isinstance(value, bytes):
        return {"type": "binary", "size_bytes": len(value)}
    if isinstance(value, datetime):
        return "[datetime]"
    if value is None:
        return "[null]"
    if isinstance(value, bool):
        return "[boolean]"
    if isinstance(value, int):
        return "[integer]"
    if isinstance(value, float):
        return "[number]"
    if isinstance(value, str):
        return "[string]"
    return "[value]"


def sanitize_mongo_document(doc: dict, redact_fields: list = None) -> dict:
    """Return field names and value shapes without returning record content."""
    if redact_fields is None:
        redact_fields = [
            "hashed_password",
            "password",
            "access_token",
            "refresh_token",
            "openai_api_key_encrypted",
            "verification_token",
            "reset_token",
        ]

    redacted = {field.casefold() for field in redact_fields}
    return {
        str(key): (
            "[redacted]"
            if str(key).casefold() in redacted
            else sanitize_mongo_value(value)
        )
        for key, value in doc.items()
    }


@router.get("/database/schema", response_model=APIResponse[DatabaseSchema])
async def get_database_schema(admin_user: dict = Depends(get_admin_user)):
    """Get database schema information (collections, indexes, sample documents)."""
    try:
        service = get_document_service()
        db = await service._get_db()

        # Access the underlying MongoDB database (MongoDBAdapter has .database attribute)
        mongo_db = db.database

        collections_info = []
        collection_names = await mongo_db.list_collection_names()

        for coll_name in collection_names:
            try:
                collection = mongo_db[coll_name]

                # Get document count
                doc_count = await collection.count_documents({})

                # Get indexes
                indexes = []
                async for idx in collection.list_indexes():
                    indexes.append({
                        "name": idx.get("name"),
                        "keys": dict(idx.get("key", {})),
                        "unique": idx.get("unique", False)
                    })

                # Get sample document (with sensitive fields removed)
                sample_doc = None
                if doc_count > 0:
                    raw_sample = await collection.find_one()
                    if raw_sample:
                        sample_doc = sanitize_mongo_document(raw_sample)

                collections_info.append(CollectionInfo(
                    name=coll_name,
                    document_count=doc_count,
                    indexes=indexes,
                    sample_document=sample_doc
                ))
            except Exception as error:
                _log_admin_exception(
                    "get_collection_schema",
                    error,
                    level=logging.WARNING,
                )
                collections_info.append(CollectionInfo(
                    name=coll_name,
                    document_count=0,
                    indexes=[],
                    sample_document=None
                ))

        # Get database stats for size info
        db_name = os.getenv("MONGODB_DATABASE", "clauseiq")

        return APIResponse(
            success=True,
            data=DatabaseSchema(
                database_name=db_name,
                collections=sorted(collections_info, key=lambda x: x.name),
                total_size_mb=None  # Could add db.stats() call if needed
            ),
            message="Database schema retrieved successfully"
        )
    except Exception as error:
        _log_admin_exception("get_database_schema", error)
        return create_error_response(
            code="SCHEMA_FETCH_FAILED",
            message="Failed to get database schema"
        )


@router.get("/database/collection/{collection_name}", response_model=APIResponse[PaginatedResponse])
async def browse_collection(
    collection_name: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    admin_user: dict = Depends(get_admin_user)
):
    """Browse documents in a specific collection."""
    try:
        service = get_document_service()
        db = await service._get_db()
        mongo_db = db.database

        collection = mongo_db[collection_name]

        # Get total count
        total = await collection.count_documents({})

        # Get documents with pagination
        cursor = collection.find({}).skip(offset).limit(limit).sort("_id", -1)

        documents = []
        async for doc in cursor:
            # Sanitize document using the helper function
            sanitized = sanitize_mongo_document(doc)
            documents.append(sanitized)

        return APIResponse(
            success=True,
            data=PaginatedResponse(
                items=documents,
                total=total,
                limit=limit,
                offset=offset,
                has_more=(offset + limit) < total
            ),
            message=f"Retrieved {len(documents)} documents from {collection_name}"
        )
    except Exception as error:
        _log_admin_exception("browse_collection", error)
        return create_error_response(
            code="BROWSE_FAILED",
            message="Failed to browse collection"
        )


# ================== Audit Logs ==================

_SAFE_LOG_SOURCES = frozenset(
    {
        "ai_debug",
        "api",
        "app",
        "auth",
        "chat",
        "clauseiq_api",
        "error",
        "foundational.logging",
        "root",
    }
)
_SAFE_LOG_TOKEN_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,79}$"


def _safe_log_token(value: Any) -> Optional[str]:
    """Return a bounded diagnostic token, never arbitrary log prose."""
    import re

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not re.fullmatch(_SAFE_LOG_TOKEN_PATTERN, candidate):
        return None
    return candidate


@router.get("/logs", response_model=APIResponse[PaginatedResponse])
async def get_audit_logs(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    level: Optional[str] = Query(default=None, description="Filter by log level (INFO, WARNING, ERROR)"),
    search: Optional[str] = Query(default=None, description="Search safe log metadata"),
    admin_user: dict = Depends(get_admin_user)
):
    """Get content-safe audit metadata from application log files."""
    del admin_user

    try:
        from pathlib import Path

        logs_dir = Path("logs")
        log_entries = []

        if logs_dir.exists():
            log_files = sorted(
                logs_dir.glob("*.log"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )

            for log_file in log_files[:5]:
                try:
                    with open(
                        log_file,
                        "r",
                        encoding="utf-8",
                        errors="replace",
                    ) as file_handle:
                        lines = file_handle.readlines()

                    for line in reversed(lines):
                        line = line.strip()
                        if not line:
                            continue

                        entry = parse_log_line(line)
                        if not entry:
                            continue

                        if level and entry.get("level") != level.upper():
                            continue

                        if search:
                            safe_search_text = " ".join(
                                str(entry.get(field, ""))
                                for field in (
                                    "level",
                                    "source",
                                    "action",
                                    "event_type",
                                    "stage",
                                    "status",
                                    "error_type",
                                )
                            ).lower()
                            if search.lower() not in safe_search_text:
                                continue

                        log_entries.append(entry)
                        if len(log_entries) >= offset + limit + 100:
                            break
                except Exception as error:
                    _log_admin_exception(
                        "read_audit_log",
                        error,
                        level=logging.WARNING,
                    )

        if not log_entries:
            log_entries = [
                {
                    "timestamp": datetime.utcnow().isoformat(),
                    "level": "INFO",
                    "message": "No audit metadata is available.",
                    "source": "admin",
                    "action": None,
                }
            ]

        total = len(log_entries)
        paginated = log_entries[offset:offset + limit]

        return APIResponse(
            success=True,
            data=PaginatedResponse(
                items=paginated,
                total=total,
                limit=limit,
                offset=offset,
                has_more=(offset + limit) < total
            ),
            message=f"Retrieved {len(paginated)} log entries"
        )
    except Exception as error:
        _log_admin_exception("get_audit_logs", error)
        return create_error_response(
            code="LOGS_FETCH_FAILED",
            message="Failed to get audit logs"
        )


def parse_log_line(line: str) -> Optional[Dict[str, Any]]:
    """Parse a log line into content-safe structured metadata."""
    import json
    import re

    pattern = (
        r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[,\.]\d+)"
        r"\s*-\s*([^\s]+)\s*-\s*"
        r"(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s*-\s*(.+)$"
    )
    match = re.match(pattern, line)
    if not match:
        return None

    timestamp, raw_source, level, raw_message = match.groups()
    timestamp = timestamp.replace(",", ".")
    source = _safe_log_token(raw_source)
    if source not in _SAFE_LOG_SOURCES:
        source = "application"

    # Function prefixes are useful only for parsing; they are never returned.
    function_match = re.match(r"^\[([^\]]+)\]\s*-?\s*(.+)$", raw_message)
    if function_match:
        raw_message = function_match.group(2)

    action = None
    action_keywords = {
        "login": ("login", "logged in", "authentication"),
        "logout": ("logout", "logged out"),
        "create": ("created", "create", "new"),
        "update": ("updated", "update", "modified"),
        "delete": ("deleted", "delete", "removed"),
        "upload": ("uploaded", "upload"),
        "analyze": ("analysis", "analyzed", "processing"),
    }
    message_lower = raw_message.lower()
    for action_name, keywords in action_keywords.items():
        if any(keyword in message_lower for keyword in keywords):
            action = action_name
            break

    entry: Dict[str, Any] = {
        "timestamp": timestamp,
        "level": level,
        "message": "Log entry recorded",
        "source": source,
        "action": action,
    }

    json_marker = "JSON: "
    marker_index = raw_message.find(json_marker)
    if marker_index >= 0:
        try:
            payload = json.loads(raw_message[marker_index + len(json_marker):])
        except (json.JSONDecodeError, TypeError):
            payload = None

        if isinstance(payload, dict):
            event_type = _safe_log_token(payload.get("event_type"))
            if event_type:
                entry["event_type"] = event_type

            context = payload.get("context")
            if isinstance(context, dict):
                stage = _safe_log_token(context.get("step_name"))
                status = _safe_log_token(context.get("status"))
                duration_ms = context.get("duration_ms")

                if stage:
                    entry["stage"] = stage
                if status:
                    entry["status"] = status
                if (
                    isinstance(duration_ms, (int, float))
                    and not isinstance(duration_ms, bool)
                ):
                    entry["duration_ms"] = duration_ms

            error = payload.get("error")
            if isinstance(error, dict):
                error_type = _safe_log_token(error.get("type"))
                if error_type:
                    entry["error_type"] = error_type

    return entry


# ================== System AI Model Configuration ==================

class SystemAIModelConfig(BaseModel):
    """System AI model configuration response."""
    model_id: str
    model_name: str
    model_description: str
    configured_at: Optional[str] = None
    updated_by: Optional[str] = None


class SetSystemAIModelRequest(BaseModel):
    """Request to set system AI model."""
    model_id: str = Field(..., description="The OpenAI model ID to use system-wide")


class AvailableAIModel(BaseModel):
    """Available AI model for selection."""
    id: str
    name: str
    description: str
    is_current: bool = False


class AvailableAIModelsResponse(BaseModel):
    """Response listing all available AI models."""
    models: List[AvailableAIModel]
    current_model_id: str


@router.get("/ai-model", response_model=APIResponse[SystemAIModelConfig])
async def get_system_ai_model(admin_user: dict = Depends(get_admin_user)):
    """Get the current system-wide AI model configuration."""
    try:
        from ai_models.models import AIModelConfig

        service = get_document_service()
        config = await service.get_system_ai_model_config()

        # Get current model ID
        model_id = config.get("model_id") if config else None
        if not model_id:
            model_id = AIModelConfig.get_default_model()

        # Get model details
        try:
            model = AIModelConfig.get_model_by_id(model_id)
            model_name = model.name
            model_description = model.description
        except ValueError:
            # Model ID in config is no longer valid, use default
            model_id = AIModelConfig.get_default_model()
            model = AIModelConfig.get_model_by_id(model_id)
            model_name = model.name
            model_description = model.description

        return APIResponse(
            success=True,
            data=SystemAIModelConfig(
                model_id=model_id,
                model_name=model_name,
                model_description=model_description,
                configured_at=config.get("configured_at") if config else None,
                updated_by=config.get("updated_by") if config else None
            ),
            message="System AI model configuration retrieved"
        )
    except Exception as error:
        _log_admin_exception("get_system_ai_model", error)
        return create_error_response(
            code="AI_MODEL_GET_FAILED",
            message="Failed to get system AI model"
        )


@router.get("/ai-model/available", response_model=APIResponse[AvailableAIModelsResponse])
async def get_available_ai_models(admin_user: dict = Depends(get_admin_user)):
    """Get list of all available AI models that can be selected."""
    try:
        from ai_models.models import AIModelConfig

        service = get_document_service()
        current_model_id = await service.get_system_ai_model()

        models = [
            AvailableAIModel(
                id=model.id,
                name=model.name,
                description=model.description,
                is_current=(model.id == current_model_id)
            )
            for model in AIModelConfig.get_available_models()
        ]

        return APIResponse(
            success=True,
            data=AvailableAIModelsResponse(
                models=models,
                current_model_id=current_model_id
            ),
            message="Available AI models retrieved"
        )
    except Exception as error:
        _log_admin_exception("get_available_ai_models", error)
        return create_error_response(
            code="AI_MODELS_GET_FAILED",
            message="Failed to get available AI models"
        )


@router.put("/ai-model", response_model=APIResponse[SystemAIModelConfig])
async def set_system_ai_model(
    request: SetSystemAIModelRequest,
    admin_user: dict = Depends(get_admin_user)
):
    """Set the system-wide AI model for all users."""
    try:
        from ai_models.models import AIModelConfig

        # Validate the model ID
        if not AIModelConfig.is_valid_model(request.model_id):
            valid_models = AIModelConfig.get_model_ids()
            return create_error_response(
                code="INVALID_MODEL",
                message=f"Invalid model ID. Valid options: {', '.join(valid_models)}"
            )

        service = get_document_service()
        success = await service.set_system_ai_model(request.model_id, admin_user.get("id"))

        if not success:
            return create_error_response(
                code="AI_MODEL_SET_FAILED",
                message="Failed to save system AI model configuration"
            )

        # Get model details for response
        model = AIModelConfig.get_model_by_id(request.model_id)

        logger.info("Admin operation completed: operation=set_system_ai_model")

        return APIResponse(
            success=True,
            data=SystemAIModelConfig(
                model_id=request.model_id,
                model_name=model.name,
                model_description=model.description,
                configured_at=datetime.utcnow().isoformat(),
                updated_by=admin_user.get("email")
            ),
            message=f"System AI model set to {model.name}"
        )
    except Exception as error:
        _log_admin_exception("set_system_ai_model", error)
        return create_error_response(
            code="AI_MODEL_SET_FAILED",
            message="Failed to set system AI model"
        )


# ================== Query Gate Model Configuration ==================

class QueryGateModelConfig(BaseModel):
    """Query gate model configuration response."""
    model_id: str
    model_name: str
    model_description: str
    configured_at: Optional[str] = None
    updated_by: Optional[str] = None


class SetQueryGateModelRequest(BaseModel):
    """Request to set query gate model."""
    model_id: str = Field(..., description="The OpenAI model ID to use for query gate")


@router.get("/query-gate-model", response_model=APIResponse[QueryGateModelConfig])
async def get_query_gate_model(admin_user: dict = Depends(get_admin_user)):
    """Get the current query gate model configuration."""
    try:
        from ai_models.models import AIModelConfig

        service = get_document_service()
        config = await service.get_query_gate_model_config()

        # Get current model ID
        model_id = config.get("model_id") if config else None
        if not model_id:
            model_id = "gpt-4o-mini"  # Default for gate calls

        # Get model details
        try:
            model = AIModelConfig.get_model_by_id(model_id)
            model_name = model.name
            model_description = model.description
        except ValueError:
            # Model ID in config is no longer valid, use default
            model_id = "gpt-4o-mini"
            model = AIModelConfig.get_model_by_id(model_id)
            model_name = model.name
            model_description = model.description

        return APIResponse(
            success=True,
            data=QueryGateModelConfig(
                model_id=model_id,
                model_name=model_name,
                model_description=model_description,
                configured_at=config.get("configured_at") if config else None,
                updated_by=config.get("updated_by") if config else None
            ),
            message="Query gate model configuration retrieved"
        )
    except Exception as error:
        _log_admin_exception("get_query_gate_model", error)
        return create_error_response(
            code="QUERY_GATE_MODEL_GET_FAILED",
            message="Failed to get query gate model"
        )


@router.put("/query-gate-model", response_model=APIResponse[QueryGateModelConfig])
async def set_query_gate_model(
    request: SetQueryGateModelRequest,
    admin_user: dict = Depends(get_admin_user)
):
    """Set the query gate model for conversation context detection."""
    try:
        from ai_models.models import AIModelConfig

        # Validate the model ID
        if not AIModelConfig.is_valid_model(request.model_id):
            valid_models = AIModelConfig.get_model_ids()
            return create_error_response(
                code="INVALID_MODEL",
                message=f"Invalid model ID. Valid options: {', '.join(valid_models)}"
            )

        service = get_document_service()
        success = await service.set_query_gate_model(request.model_id, admin_user.get("id"))

        if not success:
            return create_error_response(
                code="QUERY_GATE_MODEL_SET_FAILED",
                message="Failed to save query gate model configuration"
            )

        # Get model details for response
        model = AIModelConfig.get_model_by_id(request.model_id)

        logger.info("Admin operation completed: operation=set_query_gate_model")

        return APIResponse(
            success=True,
            data=QueryGateModelConfig(
                model_id=request.model_id,
                model_name=model.name,
                model_description=model.description,
                configured_at=datetime.utcnow().isoformat(),
                updated_by=admin_user.get("email")
            ),
            message=f"Query gate model set to {model.name}"
        )
    except Exception as error:
        _log_admin_exception("set_query_gate_model", error)
        return create_error_response(
            code="QUERY_GATE_MODEL_SET_FAILED",
            message="Failed to set query gate model"
        )


# ================== Document Auto-Delete Configuration ==================

class AutoDeleteConfig(BaseModel):
    """Auto-delete configuration response."""
    enabled: bool
    days: int
    configured_at: Optional[str] = None
    updated_by: Optional[str] = None


class SetAutoDeleteRequest(BaseModel):
    """Request to set auto-delete configuration."""
    days: int = Field(..., ge=0, le=365, description="Days until documents are auto-deleted (0 to disable)")


class AutoDeleteCleanupResult(BaseModel):
    """Result of running auto-delete cleanup."""
    deleted_count: int
    failed_count: int
    errors: List[str]
    run_at: str
    skipped: Optional[bool] = None
    reason: Optional[str] = None


@router.get("/settings/auto-delete", response_model=APIResponse[AutoDeleteConfig])
async def get_auto_delete_config(admin_user: dict = Depends(get_admin_user)):
    """Get the document auto-delete configuration."""
    try:
        service = get_document_service()
        config = await service.get_auto_delete_config()

        return APIResponse(
            success=True,
            data=AutoDeleteConfig(**config),
            message="Auto-delete configuration retrieved"
        )
    except Exception as error:
        _log_admin_exception("get_auto_delete_config", error)
        return create_error_response(
            code="AUTO_DELETE_CONFIG_FAILED",
            message="Failed to get auto-delete configuration"
        )


@router.put("/settings/auto-delete", response_model=APIResponse[AutoDeleteConfig])
async def set_auto_delete_config(
    request: SetAutoDeleteRequest,
    admin_user: dict = Depends(get_admin_user)
):
    """
    Set the document auto-delete configuration.

    - Set days to 0 to disable auto-delete
    - Documents older than the specified days will be automatically deleted
    """
    try:
        service = get_document_service()
        success = await service.set_auto_delete_config(
            days=request.days,
            admin_user_id=admin_user.get("id")
        )

        if not success:
            return create_error_response(
                code="AUTO_DELETE_CONFIG_FAILED",
                message="Failed to save auto-delete configuration"
            )

        # Get updated config
        config = await service.get_auto_delete_config()

        logger.info(
            "Admin operation completed: operation=set_auto_delete_config "
            "enabled=%s days=%s",
            request.days > 0,
            request.days,
        )

        return APIResponse(
            success=True,
            data=AutoDeleteConfig(**config),
            message=f"Auto-delete {'enabled' if request.days > 0 else 'disabled'} successfully"
        )
    except Exception as error:
        _log_admin_exception("set_auto_delete_config", error)
        return create_error_response(
            code="AUTO_DELETE_CONFIG_FAILED",
            message="Failed to set auto-delete configuration"
        )


@router.post("/settings/auto-delete/run-cleanup", response_model=APIResponse[AutoDeleteCleanupResult])
async def run_auto_delete_cleanup(admin_user: dict = Depends(get_admin_user)):
    """
    Manually trigger the auto-delete cleanup process.

    This will delete all documents older than the configured number of days.
    """
    try:
        service = get_document_service()

        result = await service.cleanup_expired_documents()

        logger.info(
            "Admin operation completed: operation=run_auto_delete_cleanup "
            "deleted_count=%s failed_count=%s",
            result.get("deleted_count", 0),
            result.get("failed_count", 0),
        )

        return APIResponse(
            success=True,
            data=AutoDeleteCleanupResult(
                **{
                    **result,
                    "errors": _sanitize_operation_errors(
                        result.get("errors"),
                        "Document cleanup failed",
                    ),
                }
            ),
            message=f"Cleanup completed: {result.get('deleted_count', 0)} documents deleted"
        )
    except Exception as error:
        _log_admin_exception("run_auto_delete_cleanup", error)
        return create_error_response(
            code="AUTO_DELETE_CLEANUP_FAILED",
            message="Failed to run cleanup"
        )


# ================== User Document Limit Configuration ==================

class DocumentLimitConfig(BaseModel):
    """Document limit configuration response."""
    enabled: bool
    max_documents: int
    configured_at: Optional[str] = None
    updated_by: Optional[str] = None


class SetDocumentLimitRequest(BaseModel):
    """Request to set document limit configuration."""
    max_documents: int = Field(..., ge=0, le=1000, description="Max documents per user (0 for unlimited)")


@router.get("/settings/document-limit", response_model=APIResponse[DocumentLimitConfig])
async def get_document_limit_config(admin_user: dict = Depends(get_admin_user)):
    """Get the current document limit configuration."""
    try:
        service = get_document_service()
        config = await service.get_document_limit_config()

        return APIResponse(
            success=True,
            data=DocumentLimitConfig(**config),
            message="Document limit configuration retrieved"
        )
    except Exception as error:
        _log_admin_exception("get_document_limit_config", error)
        return create_error_response(
            code="DOCUMENT_LIMIT_GET_FAILED",
            message="Failed to get document limit config"
        )


@router.put("/settings/document-limit", response_model=APIResponse[DocumentLimitConfig])
async def set_document_limit_config(
    request: SetDocumentLimitRequest,
    admin_user: dict = Depends(get_admin_user)
):
    """
    Set the maximum number of documents a user can store.

    - Set to 0 to disable the limit (unlimited documents)
    - Default is 10 documents per user
    """
    try:
        service = get_document_service()
        success = await service.set_document_limit_config(
            request.max_documents,
            admin_user.get("id")
        )

        if not success:
            return create_error_response(
                code="DOCUMENT_LIMIT_SET_FAILED",
                message="Failed to save document limit configuration"
            )

        logger.info(
            "Admin operation completed: operation=set_document_limit_config "
            "max_documents=%s",
            request.max_documents,
        )

        config = await service.get_document_limit_config()

        return APIResponse(
            success=True,
            data=DocumentLimitConfig(**config),
            message=f"Document limit set to {request.max_documents} per user" if request.max_documents > 0 else "Document limit disabled (unlimited)"
        )
    except Exception as error:
        _log_admin_exception("set_document_limit_config", error)
        return create_error_response(
            code="DOCUMENT_LIMIT_SET_FAILED",
            message="Failed to set document limit"
        )


# ================== UI Settings Configuration ==================

class UISettingsConfig(BaseModel):
    """UI settings configuration response."""
    toast_notifications_enabled: bool
    configured_at: Optional[str] = None
    updated_by: Optional[str] = None


class SetUISettingsRequest(BaseModel):
    """Request to set UI settings."""
    toast_notifications_enabled: bool = Field(..., description="Whether to show toast notifications to users")


@router.get("/settings/ui", response_model=APIResponse[UISettingsConfig])
async def get_ui_settings(admin_user: dict = Depends(get_admin_user)):
    """Get the current UI settings configuration."""
    try:
        service = get_document_service()
        config = await service.get_ui_settings()

        return APIResponse(
            success=True,
            data=UISettingsConfig(**config),
            message="UI settings retrieved"
        )
    except Exception as error:
        _log_admin_exception("get_ui_settings", error)
        return create_error_response(
            code="UI_SETTINGS_GET_FAILED",
            message="Failed to get UI settings"
        )


@router.put("/settings/ui", response_model=APIResponse[UISettingsConfig])
async def set_ui_settings(
    request: SetUISettingsRequest,
    admin_user: dict = Depends(get_admin_user)
):
    """Set UI settings like toast notifications."""
    try:
        service = get_document_service()
        success = await service.set_ui_settings(
            {"toast_notifications_enabled": request.toast_notifications_enabled},
            admin_user.get("id")
        )

        if not success:
            return create_error_response(
                code="UI_SETTINGS_SET_FAILED",
                message="Failed to save UI settings"
            )

        logger.info(
            "Admin operation completed: operation=set_ui_settings enabled=%s",
            request.toast_notifications_enabled,
        )

        config = await service.get_ui_settings()

        return APIResponse(
            success=True,
            data=UISettingsConfig(**config),
            message=f"Toast notifications {'enabled' if request.toast_notifications_enabled else 'disabled'}"
        )
    except Exception as error:
        _log_admin_exception("set_ui_settings", error)
        return create_error_response(
            code="UI_SETTINGS_SET_FAILED",
            message="Failed to set UI settings"
        )
