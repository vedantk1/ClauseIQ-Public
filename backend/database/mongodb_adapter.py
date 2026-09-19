"""
MongoDB adapter implementation for the database interface.
Provides MongoDB-specific implementation of database operations.
"""
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
import uuid
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
from pymongo.errors import DuplicateKeyError, ConnectionFailure, OperationFailure
import logging
from .library_summary import library_item, library_projection

from .interface import (
    DatabaseInterface,
    ConnectionConfig,
    DatabaseError,
    ConnectionError,
    ValidationError,
    NotFoundError,
    DuplicateError
)

logger = logging.getLogger(__name__)


class MongoDBAdapter(DatabaseInterface):
    """MongoDB implementation of database interface."""

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self.client: Optional[AsyncIOMotorClient] = None
        self.database: Optional[AsyncIOMotorDatabase] = None

    async def connect(self) -> None:
        """Establish MongoDB connection with enhanced pool configuration."""
        try:
            self.client = AsyncIOMotorClient(
                self.config.uri,
                maxPoolSize=self.config.max_pool_size,
                minPoolSize=self.config.min_pool_size,
                maxIdleTimeMS=self.config.max_idle_time_ms,
                waitQueueTimeoutMS=self.config.wait_queue_timeout_ms,
                serverSelectionTimeoutMS=self.config.server_selection_timeout_ms,
                retryWrites=True,
                retryReads=True,
                heartbeatFrequencyMS=10000,  # 10 seconds heartbeat
                connectTimeoutMS=20000  # 20 seconds connection timeout
            )

            # Test connection
            await self.client.admin.command('ping')

            self.database = self.client[self.config.database]
            logger.info("Connected to MongoDB")

        except Exception as e:
            logger.error("MongoDB connection failed: %s", type(e).__name__)
            raise ConnectionError("Failed to connect to MongoDB") from None

    async def disconnect(self) -> None:
        """Close MongoDB connection."""
        if self.client:
            self.client.close()
            self.client = None
            self.database = None
            logger.info("Disconnected from MongoDB")

    async def health_check(self) -> Dict[str, Any]:
        """Check MongoDB health status."""
        if self.database is None:
            return {"status": "disconnected", "error": "No database connection"}

        try:
            # Check if we can ping the database
            await self.client.admin.command('ping')

            # Get some basic stats
            stats = await self.database.command("dbStats")

            return {
                "status": "healthy",
                "database": self.config.database,
                "collections": stats.get("collections", 0),
                "dataSize": stats.get("dataSize", 0),
                "indexSize": stats.get("indexSize", 0),
                "connected": True
            }
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": "Database health check failed",
                "connected": False
            }

    def _get_collection(self, collection_name: str) -> AsyncIOMotorCollection:
        """Get collection with prefix."""
        full_name = f"{self.config.collection_prefix}{collection_name}" if self.config.collection_prefix else collection_name
        return self.database[full_name]


    # Document operations
    async def save_document(self, document_data: Dict[str, Any]) -> str:
        """Save document and return document ID."""
        try:
            documents_collection = self._get_collection("documents")

            # Add timestamps
            document_data["created_at"] = datetime.utcnow().isoformat()
            document_data["updated_at"] = datetime.utcnow().isoformat()

            result = await documents_collection.insert_one(document_data)
            return str(result.inserted_id)
        except Exception as e:
            logger.error("Database document save failed: %s", type(e).__name__)
            raise DatabaseError("Failed to save document") from None

    async def get_document(self, document_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        """Get document by ID for a specific workspace."""
        try:
            documents_collection = self._get_collection("documents")
            document = await documents_collection.find_one({
                "id": document_id,
                "workspace_id": workspace_id
            })

            if document:
                document["_id"] = str(document["_id"])

            return document
        except Exception as e:
            logger.error("Database document lookup failed: %s", type(e).__name__)
            raise DatabaseError("Failed to get document") from None

    async def list_documents(
        self,
        workspace_id: str,
        limit: int = 0,
        offset: int = 0,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """List documents for the workspace with pagination and filtering."""
        try:
            documents_collection = self._get_collection("documents")

            # Build query
            query = {"$and": [{"workspace_id": workspace_id}, filters or {}]}

            # Execute query with pagination
            cursor = documents_collection.find(query).skip(offset).limit(limit)
            documents = await cursor.to_list(length=limit or None)

            # Convert ObjectIds to strings
            for doc in documents:
                doc["_id"] = str(doc["_id"])

            return documents
        except Exception as e:
            logger.error("Database document listing failed: %s", type(e).__name__)
            raise DatabaseError("Failed to list documents") from None

    async def list_document_summaries(
        self, workspace_id: str, limit: int = 0, offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """One scoped projection; no full-document, provider or key lookups."""
        try:
            cursor = self._get_collection("documents").find(
                {"workspace_id": workspace_id}, library_projection(),
            ).skip(offset).limit(limit)
            return [library_item(item) for item in await cursor.to_list(length=limit or None)]
        except Exception as error:
            logger.error("Database Library listing failed: %s", type(error).__name__)
            raise DatabaseError("Failed to list document summaries") from None

    async def update_document(self, document_id: str, workspace_id: str, update_data: Dict[str, Any]) -> bool:
        """Update document data."""
        try:
            documents_collection = self._get_collection("documents")

            # Add update timestamp
            update_data["updated_at"] = datetime.utcnow().isoformat()

            result = await documents_collection.update_one(
                {"id": document_id, "workspace_id": workspace_id},
                {"$set": update_data}
            )

            return result.modified_count > 0
        except Exception as e:
            logger.error("Database document update failed: %s", type(e).__name__)
            raise DatabaseError("Failed to update document") from None

    async def update_document_field(self, document_id: str, workspace_id: str, field_name: str, field_value) -> bool:
        """Update a specific field in a document."""
        try:
            documents_collection = self._get_collection("documents")

            result = await documents_collection.update_one(
                {"id": document_id, "workspace_id": workspace_id},
                {"$set": {
                    field_name: field_value,
                    "updated_at": datetime.utcnow().isoformat()
                }}
            )

            return result.modified_count > 0
        except Exception as e:
            logger.error("Database document field update failed: %s", type(e).__name__)
            raise DatabaseError("Failed to update document field") from None

    async def update_document_if(
        self, document_id: str, workspace_id: str,
        expected: Dict[str, Any], update_data: Dict[str, Any],
    ) -> bool:
        """Atomically update one existing document using trusted server conditions.

        Conditions must be constructed by services, never accepted as a client
        query. Keeping scope in a separate AND clause prevents a condition from
        replacing the required identity or workspace filter.
        """
        try:
            if any(key.split(".", 1)[0] in {"id", "workspace_id", "_id"}
                   for key in update_data):
                raise ValueError("Conditional updates cannot change document identity")
            updates = {**update_data, "updated_at": datetime.utcnow().isoformat()}
            result = await self._get_collection("documents").update_one(
                {"$and": [{"id": document_id, "workspace_id": workspace_id}, dict(expected)]},
                {"$set": updates},
                upsert=False,
            )
            return result.matched_count > 0
        except Exception as e:
            logger.error("Conditional document update failed: %s", type(e).__name__)
            raise DatabaseError("Failed to conditionally update document") from None

    async def delete_document(self, document_id: str, workspace_id: str) -> bool:
        """Delete document."""
        try:
            documents_collection = self._get_collection("documents")
            scope = {"id": document_id, "workspace_id": workspace_id}
            if not await documents_collection.find_one(scope, {"_id": 1}):
                return False
            await self._get_collection("user_interactions").delete_many({
                "document_id": document_id,
                "workspace_id": workspace_id,
            })
            result = await documents_collection.delete_one({
                "id": document_id,
                "workspace_id": workspace_id
            })
            return result.deleted_count > 0
        except Exception as e:
            logger.error("Database document deletion failed: %s", type(e).__name__)
            raise DatabaseError("Failed to delete document") from None

    async def create_or_get_chat_session(self, document_id: str, workspace_id: str, session_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Atomically create chat session if it doesn't exist, or return existing session."""
        try:
            documents_collection = self._get_collection("documents")

            # Use findOneAndUpdate with upsert to atomically check and create session
            result = await documents_collection.find_one_and_update(
                {
                    "id": document_id,
                    "workspace_id": workspace_id,
                    "chat_session": {"$exists": False}  # Only update if no session exists
                },
                {
                    "$set": {
                        "chat_session": session_data,
                        "updated_at": datetime.utcnow().isoformat()
                    }
                },
                return_document=True  # Return the updated document
            )

            if result:
                # Session was created successfully
                return {"created": True, "session": result.get("chat_session")}
            else:
                # Session already exists, get the existing one
                existing_doc = await documents_collection.find_one(
                    {"id": document_id, "workspace_id": workspace_id}
                )
                if existing_doc and "chat_session" in existing_doc:
                    return {"created": False, "session": existing_doc["chat_session"]}
                else:
                    # Document doesn't exist or other error
                    return None

        except Exception as e:
            logger.error("Database chat session operation failed: %s", type(e).__name__)
            raise DatabaseError("Failed to create or get chat session") from None

    async def add_chat_message_atomic(self, document_id: str, workspace_id: str, message: Dict[str, Any]) -> bool:
        """Atomically add a message to the chat session."""
        try:
            documents_collection = self._get_collection("documents")

            result = await documents_collection.update_one(
                {
                    "id": document_id,
                    "workspace_id": workspace_id,
                    "chat_session": {"$exists": True}
                },
                {
                    "$push": {"chat_session.messages": message},
                    "$set": {
                        "chat_session.updated_at": datetime.utcnow().isoformat(),
                        "updated_at": datetime.utcnow().isoformat()
                    }
                }
            )

            return result.modified_count > 0

        except Exception as e:
            logger.error("Database chat message operation failed: %s", type(e).__name__)
            raise DatabaseError("Failed to add chat message") from None

    async def clear_chat_messages(self, document_id: str, workspace_id: str) -> bool:
        """Clear all messages from the chat session while keeping the session."""
        try:
            documents_collection = self._get_collection("documents")

            result = await documents_collection.update_one(
                {
                    "id": document_id,
                    "workspace_id": workspace_id,
                    "chat_session": {"$exists": True}
                },
                {
                    "$set": {
                        "chat_session.messages": [],
                        "chat_session.updated_at": datetime.utcnow().isoformat(),
                        "updated_at": datetime.utcnow().isoformat()
                    }
                }
            )

            return result.modified_count > 0

        except Exception as e:
            logger.error("Database chat clearing failed: %s", type(e).__name__)
            return False

    # Analytics operations
    async def get_workspace_analytics(self, workspace_id: str) -> Dict[str, Any]:
        """Get analytics data for user."""
        try:
            documents_collection = self._get_collection("documents")

            # Aggregate user statistics
            pipeline = [
                {"$match": {"workspace_id": workspace_id}},
                {"$group": {
                    "_id": "$workspace_id",
                    "total_documents": {"$sum": 1},
                    "total_clauses": {"$sum": {"$size": {"$ifNull": ["$clauses", []]}}},
                    "avg_risk_score": {"$avg": "$avg_risk_score"},
                    "last_upload": {"$max": "$created_at"}
                }}
            ]

            result = await documents_collection.aggregate(pipeline).to_list(1)

            if result:
                return result[0]
            else:
                return {
                    "total_documents": 0,
                    "total_clauses": 0,
                    "avg_risk_score": 0.0,
                    "last_upload": None
                }
        except Exception as e:
            logger.error("Database analytics lookup failed: %s", type(e).__name__)
            raise DatabaseError("Failed to get user analytics") from None

    # User interaction operations
    async def get_user_interactions(self, document_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        """Get user interactions for a document."""
        try:
            interactions_collection = self._get_collection("user_interactions")
            interaction_doc = await interactions_collection.find_one({
                "document_id": document_id,
                "workspace_id": workspace_id
            })

            if interaction_doc:
                return interaction_doc.get("interactions", {})
            return None

        except Exception as e:
            logger.error("Database interaction lookup failed: %s", type(e).__name__)
            raise DatabaseError("Failed to get user interactions") from None

    async def save_user_interactions(self, document_id: str, workspace_id: str, interactions: Dict[str, Any]) -> bool:
        """Save user interactions for a document."""
        try:
            interactions_collection = self._get_collection("user_interactions")

            # Use upsert to create or update the document
            result = await interactions_collection.update_one(
                {
                    "document_id": document_id,
                    "workspace_id": workspace_id
                },
                {
                    "$set": {
                        "interactions": interactions,
                        "updated_at": datetime.now().isoformat()
                    },
                    "$setOnInsert": {
                        "created_at": datetime.now().isoformat()
                    }
                },
                upsert=True
            )

            return result.acknowledged

        except Exception as e:
            logger.error("Database interaction save failed: %s", type(e).__name__)
            raise DatabaseError("Failed to save user interactions") from None

    async def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute raw MongoDB query (for advanced operations)."""
        try:
            if not self.database:
                raise ConnectionError("Database not connected")

            # For MongoDB, we'll interpret the query as a collection name and operation
            # This is a simplified implementation - in practice, you might want to support
            # more complex query structures
            logger.warning("execute_query called with raw query - this is a simplified implementation")

            # Return empty result for now - this method is primarily for compatibility
            return {"result": "Query executed"}

        except Exception as e:
            logger.error("Database compatibility query failed: %s", type(e).__name__)
            raise DatabaseError("Failed to execute query") from None
