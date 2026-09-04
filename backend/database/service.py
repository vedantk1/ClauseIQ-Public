"""
Service layer for database operations.
Provides async document and user management operations using the database abstraction layer.
"""
import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from .factory import DatabaseFactory
from .interface import DatabaseInterface

logger = logging.getLogger(__name__)


class DocumentService:
    """Service layer for document operations using new database abstraction."""

    def __init__(self):
        self._db: Optional[DatabaseInterface] = None

    async def _get_db(self) -> DatabaseInterface:
        """Get database instance."""
        if self._db is None:
            self._db = await DatabaseFactory.get_database()
        return self._db

    # Document operations
    async def save_document(self, document_dict: Dict[str, Any]) -> str:
        """Save document and return document ID."""
        db = await self._get_db()
        return await db.save_document(document_dict)

    async def save_document_for_user(self, document_dict: Dict[str, Any], user_id: str) -> str:
        """Save document for specific user."""
        document_dict["user_id"] = user_id
        return await self.save_document(document_dict)

    async def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get document by ID."""
        db = await self._get_db()
        # For backward compatibility, we need to get the user_id somehow
        # This is a limitation of the old interface
        return await db.get_document(doc_id, "")

    async def get_document_for_user(self, doc_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get document by ID for specific user."""
        db = await self._get_db()
        return await db.get_document(doc_id, user_id)

    async def update_document_last_viewed(self, doc_id: str, user_id: str) -> bool:
        """Update the last_viewed timestamp for a document."""
        try:
            db = await self._get_db()
            current_time = datetime.utcnow().isoformat()
            return await db.update_document_field(doc_id, user_id, "last_viewed", current_time)
        except Exception as e:
            logger.error("Document last-viewed update failed: %s", type(e).__name__)
            return False

    async def get_documents_for_user(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        """Get documents for user with pagination."""
        db = await self._get_db()
        return await db.list_documents(user_id, limit, offset)

    async def delete_document(self, doc_id: str) -> bool:
        """Delete document by ID."""
        # This is a limitation - we need user_id for the new interface
        # For now, we'll implement a workaround
        logger.warning("delete_document called without user_id - this is deprecated")
        return False

    async def delete_document_for_user(self, doc_id: str, user_id: str) -> bool:
        """Delete document for specific user and clean up RAG data and PDF files."""
        try:
            # First get document to check for PDF file
            document = await self.get_document_for_user(doc_id, user_id)

            # Clean up PDF file if it exists
            pdf_file_id = document.get('pdf_file_id') if document else None
            if pdf_file_id:
                try:
                    from services.file_storage_service import get_file_storage_service
                    file_storage = get_file_storage_service()
                    await file_storage.delete_file(pdf_file_id, user_id)
                    logger.info("Cleaned up stored PDF file")
                except Exception as e:
                    logger.warning("Stored PDF cleanup failed: %s", type(e).__name__)
                    # Continue with document deletion even if PDF cleanup fails

            # Then, clean up RAG data from vector storage
            try:
                from services.rag_service import get_rag_service
                rag_service = get_rag_service()
                await rag_service.delete_document_from_rag(doc_id, user_id)
                logger.info("Cleaned up document RAG data")
            except Exception as e:
                logger.warning("Document RAG cleanup failed: %s", type(e).__name__)
                # Continue with document deletion even if RAG cleanup fails

            # Finally delete from MongoDB
            db = await self._get_db()
            result = await db.delete_document(doc_id, user_id)

            if result:
                logger.info("Deleted document successfully")

            return result

        except Exception as e:
            logger.error("Document deletion failed: %s", type(e).__name__)
            return False

    async def delete_all_documents_for_user(self, user_id: str) -> int:
        """Delete all documents for user and clean up RAG data."""
        db = await self._get_db()
        documents = await db.list_documents(user_id, limit=1000)  # Get all documents
        count = 0
        for doc in documents:
            # Use the service method to ensure RAG cleanup
            if await self.delete_document_for_user(doc["id"], user_id):
                count += 1
        return count

    async def get_documents_count(self) -> int:
        """Get total documents count."""
        # This is approximate since we need to aggregate across users
        logger.warning("get_documents_count is deprecated - use user-specific methods")
        return 0

    # User operations
    async def create_user(self, user_data: Dict[str, Any]) -> str:
        """Create new user."""
        db = await self._get_db()
        return await db.create_user(user_data)

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get user by email."""
        db = await self._get_db()
        return await db.get_user_by_email(email)

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        db = await self._get_db()
        return await db.get_user_by_id(user_id)

    async def update_user(self, user_id: str, update_data: Dict[str, Any]) -> bool:
        """Update user data."""
        db = await self._get_db()
        return await db.update_user(user_id, update_data)

    async def delete_user(self, user_id: str) -> bool:
        """Delete user."""
        db = await self._get_db()
        return await db.delete_user(user_id)

    # Convenience methods for backward compatibility
    async def update_user_password(self, email: str, new_hashed_password: str) -> bool:
        """Update user password by email."""
        user = await self.get_user_by_email(email)
        if user:
            return await self.update_user(user["id"], {"hashed_password": new_hashed_password})
        return False

    async def update_user_preferences(self, user_id: str, preferences: Dict[str, Any]) -> bool:
        """Update user preferences."""
        return await self.update_user(user_id, preferences)

    async def get_user_preferred_model(self, user_id: str) -> str:
        """
        Get the AI model to use for this user.

        Note: Model selection is now admin-controlled system-wide.
        This returns the system-configured model for all users.
        """
        # Use the admin-configured system model
        return await self.get_system_ai_model()

    # User API Key management
    async def set_user_api_key(self, user_id: str, api_key: str) -> bool:
        """
        Encrypt and store user's OpenAI API key.

        Args:
            user_id: The user's ID
            api_key: The plaintext API key to store

        Returns:
            True if successful, False otherwise
        """
        try:
            from services.encryption_service import get_encryption_service

            encryption_service = get_encryption_service()
            encrypted_key = encryption_service.encrypt(api_key)

            update_data = {
                "openai_api_key_encrypted": encrypted_key,
                "openai_api_key_set": True,
                "openai_api_key_updated_at": datetime.now().isoformat()
            }

            return await self.update_user(user_id, update_data)
        except Exception as e:
            logger.error("API key storage failed: %s", type(e).__name__)
            return False

    async def get_user_api_key(self, user_id: str) -> Optional[str]:
        """
        Get and decrypt user's OpenAI API key.

        Args:
            user_id: The user's ID

        Returns:
            Decrypted API key, or None if not set
        """
        try:
            user = await self.get_user_by_id(user_id)
            if not user or not user.get("openai_api_key_set"):
                return None

            encrypted_key = user.get("openai_api_key_encrypted")
            if not encrypted_key:
                return None

            from services.encryption_service import get_encryption_service

            encryption_service = get_encryption_service()
            return encryption_service.decrypt(encrypted_key)
        except Exception as e:
            logger.error("API key retrieval failed: %s", type(e).__name__)
            return None

    async def delete_user_api_key(self, user_id: str) -> bool:
        """
        Remove user's OpenAI API key.

        Args:
            user_id: The user's ID

        Returns:
            True if successful, False otherwise
        """
        try:
            update_data = {
                "openai_api_key_encrypted": None,
                "openai_api_key_set": False,
                "openai_api_key_updated_at": datetime.now().isoformat()
            }

            return await self.update_user(user_id, update_data)
        except Exception as e:
            logger.error("API key deletion failed: %s", type(e).__name__)
            return False

    async def has_user_api_key(self, user_id: str) -> bool:
        """
        Check if user has an OpenAI API key set.

        Args:
            user_id: The user's ID

        Returns:
            True if API key is set, False otherwise
        """
        try:
            user = await self.get_user_by_id(user_id)
            return bool(user and user.get("openai_api_key_set"))
        except Exception as e:
            logger.error("API key status check failed: %s", type(e).__name__)
            return False

    # User interaction methods
    async def get_user_interactions(self, document_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user interactions for a document."""
        db = await self._get_db()
        return await db.get_user_interactions(document_id, user_id)

    async def save_user_interaction(self, document_id: str, clause_id: str, user_id: str,
                                  note: Optional[str] = None, is_flagged: bool = False) -> Dict[str, Any]:
        """Save or update user interaction for a clause (backward compatibility)."""
        from datetime import datetime
        import uuid

        db = await self._get_db()

        # Get existing interactions
        existing_interactions = await self.get_user_interactions(document_id, user_id) or {}

        # Initialize interaction if it doesn't exist
        if clause_id not in existing_interactions:
            existing_interactions[clause_id] = {
                "clause_id": clause_id,
                "user_id": user_id,
                "notes": [],
                "is_flagged": False,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }

        interaction = existing_interactions[clause_id]

        # Handle note (for backward compatibility, replace first note or add new)
        if note is not None:
            note_obj = {
                "id": str(uuid.uuid4()),
                "text": note,
                "created_at": datetime.now().isoformat()
            }

            # Initialize notes array if it doesn't exist (migration compatibility)
            if "notes" not in interaction:
                interaction["notes"] = []
            elif "note" in interaction:
                # Migrate old single note to notes array
                if interaction["note"]:
                    old_note = {
                        "id": str(uuid.uuid4()),
                        "text": interaction["note"],
                        "created_at": interaction.get("created_at", datetime.now().isoformat())
                    }
                    interaction["notes"] = [old_note]
                else:
                    interaction["notes"] = []
                del interaction["note"]  # Remove old field

            # For backward compatibility, replace first note if exists, otherwise add
            if len(interaction["notes"]) > 0:
                interaction["notes"][0] = note_obj
            else:
                interaction["notes"].append(note_obj)

        # Update flag status
        interaction["is_flagged"] = is_flagged
        interaction["updated_at"] = datetime.now().isoformat()

        # Save to database
        await db.save_user_interactions(document_id, user_id, existing_interactions)

        return interaction

    async def add_note(self, document_id: str, clause_id: str, user_id: str, text: str) -> Dict[str, Any]:
        """Add a new note to a clause."""
        from datetime import datetime
        import uuid

        db = await self._get_db()

        # Get existing interactions
        existing_interactions = await self.get_user_interactions(document_id, user_id) or {}

        # Initialize interaction if it doesn't exist
        if clause_id not in existing_interactions:
            existing_interactions[clause_id] = {
                "clause_id": clause_id,
                "user_id": user_id,
                "notes": [],
                "is_flagged": False,
                "created_at": datetime.now().isoformat(),
                "updated_at": datetime.now().isoformat()
            }

        interaction = existing_interactions[clause_id]

        # Initialize notes array if it doesn't exist (migration compatibility)
        if "notes" not in interaction:
            interaction["notes"] = []
        elif "note" in interaction:
            # Migrate old single note to notes array
            if interaction["note"]:
                old_note = {
                    "id": str(uuid.uuid4()),
                    "text": interaction["note"],
                    "created_at": interaction.get("created_at", datetime.now().isoformat())
                }
                interaction["notes"] = [old_note]
            else:
                interaction["notes"] = []
            del interaction["note"]  # Remove old field

        # Create new note
        new_note = {
            "id": str(uuid.uuid4()),
            "text": text,
            "created_at": datetime.now().isoformat()
        }

        # Add note to array
        interaction["notes"].append(new_note)
        interaction["updated_at"] = datetime.now().isoformat()

        # Save to database
        await db.save_user_interactions(document_id, user_id, existing_interactions)

        return new_note

    async def update_note(self, document_id: str, clause_id: str, user_id: str, note_id: str, text: str) -> Dict[str, Any]:
        """Update an existing note."""
        from datetime import datetime

        db = await self._get_db()

        # Get existing interactions
        existing_interactions = await self.get_user_interactions(document_id, user_id) or {}

        if clause_id not in existing_interactions:
            raise ValueError("Interaction not found")

        interaction = existing_interactions[clause_id]

        # Find and update the note
        if "notes" not in interaction:
            raise ValueError("No notes found")

        note_found = False
        for note in interaction["notes"]:
            if note["id"] == note_id:
                note["text"] = text
                note_found = True
                break

        if not note_found:
            raise ValueError("Note not found")

        interaction["updated_at"] = datetime.now().isoformat()

        # Save to database
        await db.save_user_interactions(document_id, user_id, existing_interactions)

        # Find and return the updated note
        updated_note = None
        for note in interaction["notes"]:
            if note["id"] == note_id:
                updated_note = note
                break

        if not updated_note:
            raise ValueError("Updated note not found after save")

        return updated_note

    async def delete_note(self, document_id: str, clause_id: str, user_id: str, note_id: str) -> bool:
        """Delete a specific note."""
        from datetime import datetime

        db = await self._get_db()

        # Get existing interactions
        existing_interactions = await self.get_user_interactions(document_id, user_id) or {}

        if clause_id not in existing_interactions:
            return False

        interaction = existing_interactions[clause_id]

        # Find and remove the note
        if "notes" not in interaction:
            return False

        original_length = len(interaction["notes"])
        interaction["notes"] = [note for note in interaction["notes"] if note["id"] != note_id]

        if len(interaction["notes"]) == original_length:
            return False  # Note not found

        interaction["updated_at"] = datetime.now().isoformat()

        # Save to database
        await db.save_user_interactions(document_id, user_id, existing_interactions)

        return True

    async def delete_user_interaction(self, document_id: str, clause_id: str, user_id: str) -> bool:
        """Delete user interaction for a clause."""
        db = await self._get_db()

        # Get existing interactions
        existing_interactions = await self.get_user_interactions(document_id, user_id)
        if not existing_interactions or clause_id not in existing_interactions:
            return False

        # Remove the interaction
        del existing_interactions[clause_id]

        # Save updated interactions
        await db.save_user_interactions(document_id, user_id, existing_interactions)

        return True

    async def update_document_rag_metadata(self, doc_id: str, user_id: str, rag_data: Dict[str, Any]) -> bool:
        """Update document with RAG processing metadata."""
        db = await self._get_db()

        # Update document with RAG metadata (accept all fields from rag_data)
        rag_metadata = {
            "rag_processed": rag_data.get("rag_processed", True),
            "ready_for_chat": rag_data.get("ready_for_chat", False),
            "text_length": rag_data.get("text_length"),
            "chunk_count": rag_data.get("chunk_count", 0),
            "processing_status": rag_data.get("processing_status", "completed"),
            "processed_at": rag_data.get("processed_at"),
            "rag_vector_store_id": rag_data.get("vector_store_id"),
            "rag_file_id": rag_data.get("file_id"),
            "rag_chunk_count": rag_data.get("chunk_count", 0),
            "rag_processed_at": datetime.now().isoformat(),
            "vector_stored": rag_data.get("vector_stored", False),
            "chunk_ids": rag_data.get("chunk_ids", []),
            "embedding_model": rag_data.get("embedding_model"),
            "storage_service": rag_data.get("storage_service")
        }

        # Remove None values to avoid overwriting with null
        rag_metadata = {k: v for k, v in rag_metadata.items() if v is not None}

        # Use update operation instead of save to avoid duplicate key error
        success = await db.update_document(doc_id, user_id, rag_metadata)
        return success

    async def mark_document_for_rag_reprocessing(self, doc_id: str, user_id: str) -> bool:
        """Mark document as needing RAG reprocessing due to failure."""
        db = await self._get_db()
        document = await db.get_document(doc_id, user_id)
        if not document:
            return False

        # Mark for reprocessing
        document.update({
            "rag_processed": False,
            "rag_needs_reprocessing": True,
            "rag_last_error": datetime.now().isoformat()
        })

        await db.save_document(document)
        return True

    async def get_documents_needing_rag_processing(self, user_id: str) -> List[Dict[str, Any]]:
        """Get documents that need RAG processing."""
        # This would need to be implemented in the database interface
        # For now, return empty list
        return []

    async def get_all_documents_for_cleanup(self) -> List[Dict[str, Any]]:
        """Get all documents for cleanup operations (admin use only)."""
        db = await self._get_db()
        # This is an admin operation, so we can access all documents
        collection = db._get_collection("documents")
        cursor = collection.find({})
        documents = []
        async for doc in cursor:
            documents.append(doc)
        return documents

    async def cleanup_document_sessions(self, doc_id: str) -> bool:
        """Remove all chat sessions (legacy and foundational) from a document."""
        db = await self._get_db()
        collection = db._get_collection("documents")

        # Remove both chat_sessions array and chat_session object
        result = await collection.update_one(
            {"id": doc_id},
            {
                "$unset": {
                    "chat_sessions": "",
                    "chat_session": ""
                }
            }
        )

        return result.modified_count > 0

    # Health check
    async def get_database_info(self) -> Dict[str, Any]:
        """Get database information."""
        return await DatabaseFactory.health_check()

    async def update_document_data(self, document_id: str, user_id: str, update_data: Dict[str, Any]) -> bool:
        """Update document data safely through the service layer."""
        try:
            db = await self._get_db()
            return await db.update_document(document_id, user_id, update_data)
        except Exception as e:
            logger.error("Document update failed: %s", type(e).__name__)
            return False

    # PDF File Operations
    async def store_pdf_file(self, document_id: str, user_id: str, file_data: bytes,
                           filename: str, content_type: str = "application/pdf") -> bool:
        """Store PDF file for a document and update document metadata."""
        try:
            from services.file_storage_service import get_file_storage_service
            file_storage = get_file_storage_service()

            # Store the PDF file
            file_id = await file_storage.store_file(
                file_data=file_data,
                filename=filename,
                content_type=content_type,
                user_id=user_id,
                metadata={'document_id': document_id}
            )

            # Update document with PDF metadata
            pdf_metadata = {
                'pdf_file_id': file_id,
                'pdf_file_size': len(file_data),
                'pdf_content_type': content_type,
                'pdf_stored_at': datetime.now().isoformat(),
                'has_pdf_file': True
            }

            # Update document
            db = await self._get_db()
            success = await db.update_document(document_id, user_id, pdf_metadata)

            if success:
                logger.info("Stored PDF file successfully")
            else:
                # Rollback file storage if document update fails
                await file_storage.delete_file(file_id, user_id)
                raise Exception("Failed to update document with PDF metadata")

            return success

        except Exception as e:
            logger.error("PDF file storage failed: %s", type(e).__name__)
            return False

    async def get_pdf_file(self, document_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get PDF file for a document."""
        try:
            # First get document to get PDF file ID
            document = await self.get_document_for_user(document_id, user_id)
            if not document or not document.get('has_pdf_file'):
                return None

            pdf_file_id = document.get('pdf_file_id')
            if not pdf_file_id:
                return None

            # Get file from storage
            from services.file_storage_service import get_file_storage_service
            file_storage = get_file_storage_service()

            return await file_storage.get_file(pdf_file_id, user_id)

        except Exception as e:
            logger.error("PDF file retrieval failed: %s", type(e).__name__)
            return None

    async def get_pdf_file_stream(self, document_id: str, user_id: str):
        """Get PDF file stream for efficient downloading."""
        try:
            # First get document to get PDF file ID
            document = await self.get_document_for_user(document_id, user_id)
            if not document or not document.get('has_pdf_file'):
                return None, None

            pdf_file_id = document.get('pdf_file_id')
            if not pdf_file_id:
                return None, None

            # Get file metadata and stream
            from services.file_storage_service import get_file_storage_service
            file_storage = get_file_storage_service()

            metadata = await file_storage.get_file_metadata(pdf_file_id, user_id)
            stream = await file_storage.get_file_stream(pdf_file_id, user_id)

            return metadata, stream

        except Exception as e:
            logger.error("PDF file stream failed: %s", type(e).__name__)
            return None, None

    async def has_pdf_file(self, document_id: str, user_id: str) -> bool:
        """Check if document has a PDF file."""
        try:
            document = await self.get_document_for_user(document_id, user_id)
            return document.get('has_pdf_file', False) if document else False
        except Exception as e:
            logger.error("PDF file status check failed: %s", type(e).__name__)
            return False

    # Atomic operations for race condition prevention
    async def create_or_get_chat_session(self, document_id: str, user_id: str, session_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Atomically create chat session if it doesn't exist, or return existing session."""
        db = await self._get_db()
        return await db.create_or_get_chat_session(document_id, user_id, session_data)

    async def add_chat_message_atomic(self, document_id: str, user_id: str, message: Dict[str, Any]) -> bool:
        """Atomically add a message to the chat session."""
        db = await self._get_db()
        return await db.add_chat_message_atomic(document_id, user_id, message)

    async def clear_chat_messages(self, document_id: str, user_id: str) -> bool:
        """Clear all messages from the chat session."""
        db = await self._get_db()
        return await db.clear_chat_messages(document_id, user_id)

    async def update_clause_rewrite(self, document_id: str, clause_id: str, user_id: str, rewrite_suggestion: str) -> Optional[Dict[str, Any]]:
        """Update a clause with a rewrite suggestion."""
        try:
            db = await self._get_db()

            # Get the current document
            document = await db.get_document(document_id, user_id)
            if not document:
                raise ValueError("Document not found")

            # Find and update the specific clause
            clauses = document.get("clauses", [])
            updated_clause = None

            for clause in clauses:
                if clause.get("id") == clause_id:
                    clause["rewrite_suggestion"] = rewrite_suggestion
                    clause["rewrite_generated_at"] = datetime.utcnow().isoformat()
                    updated_clause = clause
                    break

            if not updated_clause:
                raise ValueError("Clause not found")

            # Update the document with the modified clauses
            success = await db.update_document_field(document_id, user_id, "clauses", clauses)

            if success:
                return updated_clause
            else:
                raise Exception("Failed to update document with rewrite suggestion")

        except Exception as e:
            logger.error("Clause rewrite update failed: %s", type(e).__name__)
            raise

    # Note: Document-based PDF methods are above in the "PDF File Operations" section
    # The methods below provide direct file storage access if needed

    # ================== ADMIN OPERATIONS ==================
    # These methods are for admin portal use only

    async def list_all_users(self, limit: int = 50, offset: int = 0, search: Optional[str] = None) -> tuple[List[Dict[str, Any]], int]:
        """List all users with pagination and optional search. Returns (users, total_count)."""
        try:
            db = await self._get_db()
            collection = db._get_collection("users")

            # Build query
            query = {}
            if search:
                # Case-insensitive search on email and full_name
                query["$or"] = [
                    {"email": {"$regex": search, "$options": "i"}},
                    {"full_name": {"$regex": search, "$options": "i"}}
                ]

            # Get total count
            total_count = await collection.count_documents(query)

            # Get paginated results
            cursor = collection.find(query).skip(offset).limit(limit).sort("created_at", -1)
            users = []
            async for user in cursor:
                # Remove sensitive fields
                user.pop("hashed_password", None)
                user["_id"] = str(user["_id"])
                users.append(user)

            return users, total_count

        except Exception as e:
            logger.error("Admin user listing failed: %s", type(e).__name__)
            return [], 0

    async def get_admin_stats(self) -> Dict[str, Any]:
        """Get admin dashboard statistics."""
        try:
            db = await self._get_db()
            users_collection = db._get_collection("users")
            documents_collection = db._get_collection("documents")

            # Get counts
            user_count = await users_collection.count_documents({})
            document_count = await documents_collection.count_documents({})

            # Get documents created in last 7 days
            from datetime import timedelta
            seven_days_ago = (datetime.utcnow() - timedelta(days=7)).isoformat()
            recent_documents = await documents_collection.count_documents({
                "created_at": {"$gte": seven_days_ago}
            })

            # Get users created in last 7 days
            recent_users = await users_collection.count_documents({
                "created_at": {"$gte": seven_days_ago}
            })

            # Get document breakdown by contract type
            contract_type_pipeline = [
                {"$group": {"_id": "$contract_type", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
                {"$limit": 10}
            ]
            contract_types = await documents_collection.aggregate(contract_type_pipeline).to_list(10)

            return {
                "user_count": user_count,
                "document_count": document_count,
                "recent_documents_7d": recent_documents,
                "recent_users_7d": recent_users,
                "contract_type_breakdown": [
                    {"type": item["_id"] or "Unknown", "count": item["count"]}
                    for item in contract_types
                ]
            }

        except Exception as e:
            logger.error("Admin statistics lookup failed: %s", type(e).__name__)
            return {
                "user_count": 0,
                "document_count": 0,
                "recent_documents_7d": 0,
                "recent_users_7d": 0,
                "contract_type_breakdown": []
            }

    async def list_all_documents_admin(
        self,
        limit: int = 50,
        offset: int = 0,
        user_id_filter: Optional[str] = None,
        search: Optional[str] = None
    ) -> tuple[List[Dict[str, Any]], int]:
        """List all documents for admin with pagination. Returns (documents, total_count)."""
        try:
            db = await self._get_db()
            collection = db._get_collection("documents")

            # Build query
            query = {}
            if user_id_filter:
                query["user_id"] = user_id_filter
            if search:
                query["$or"] = [
                    {"filename": {"$regex": search, "$options": "i"}},
                    {"contract_type": {"$regex": search, "$options": "i"}}
                ]

            # Get total count
            total_count = await collection.count_documents(query)

            # Get paginated results (exclude large fields for listing)
            cursor = collection.find(
                query,
                {
                    "id": 1,
                    "user_id": 1,
                    "filename": 1,
                    "contract_type": 1,
                    "created_at": 1,
                    "updated_at": 1,
                    "has_pdf_file": 1,
                    "rag_processed": 1,
                    "ready_for_chat": 1
                }
            ).skip(offset).limit(limit).sort("created_at", -1)

            documents = []
            async for doc in cursor:
                doc["_id"] = str(doc["_id"])
                documents.append(doc)

            return documents, total_count

        except Exception as e:
            logger.error("Admin document listing failed: %s", type(e).__name__)
            return [], 0

    async def get_user_with_documents_admin(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user details with their document summary for admin view."""
        try:
            user = await self.get_user_by_id(user_id)
            if not user:
                return None

            # Remove sensitive fields
            user.pop("hashed_password", None)

            # Get user's documents count and recent documents
            db = await self._get_db()
            documents_collection = db._get_collection("documents")

            document_count = await documents_collection.count_documents({"user_id": user_id})

            recent_docs_cursor = documents_collection.find(
                {"user_id": user_id},
                {"id": 1, "filename": 1, "contract_type": 1, "created_at": 1}
            ).sort("created_at", -1).limit(5)

            recent_documents = []
            async for doc in recent_docs_cursor:
                doc["_id"] = str(doc["_id"])
                recent_documents.append(doc)

            user["document_count"] = document_count
            user["recent_documents"] = recent_documents

            return user

        except Exception as e:
            logger.error("Admin user detail lookup failed: %s", type(e).__name__)
            return None

    async def delete_user_cascade(self, user_id: str, admin_user_id: str) -> Dict[str, Any]:
        """
        Delete user and all their data (documents, RAG data, files).
        Returns summary of deleted items.
        """
        if user_id == admin_user_id:
            raise ValueError("Admin cannot delete themselves")

        result = {
            "user_deleted": False,
            "documents_deleted": 0,
            "errors": []
        }

        try:
            # First delete all user's documents (this handles RAG and PDF cleanup)
            documents_deleted = await self.delete_all_documents_for_user(user_id)
            result["documents_deleted"] = documents_deleted

            # Delete user interactions
            try:
                db = await self._get_db()
                interactions_collection = db._get_collection("user_interactions")
                await interactions_collection.delete_many({"user_id": user_id})
            except Exception as e:
                result["errors"].append("Failed to delete user interactions")

            # Finally delete the user
            user_deleted = await self.delete_user(user_id)
            result["user_deleted"] = user_deleted

            logger.info("Admin user deletion completed")

            return result

        except Exception as e:
            logger.error("Admin user deletion failed: %s", type(e).__name__)
            result["errors"].append("User deletion failed")
            return result

    async def delete_document_admin(self, doc_id: str, user_id: str) -> bool:
        """Delete document as admin (uses existing service method with proper cleanup)."""
        return await self.delete_document_for_user(doc_id, user_id)

    # ================== SYSTEM CONFIG OPERATIONS ==================
    # For storing system-wide application configuration

    async def get_system_config(self, key: str) -> Optional[Dict[str, Any]]:
        """Get a system configuration by key."""
        try:
            db = await self._get_db()
            collection = db._get_collection("system_config")
            config = await collection.find_one({"key": key})
            if config:
                config["_id"] = str(config["_id"])
            return config
        except Exception as e:
            logger.error("System configuration lookup failed: %s", type(e).__name__)
            return None

    async def set_system_config(self, key: str, data: Dict[str, Any], admin_user_id: str) -> bool:
        """Set a system configuration. Creates or updates."""
        try:
            db = await self._get_db()
            collection = db._get_collection("system_config")

            config_data = {
                "key": key,
                **data,
                "updated_at": datetime.now().isoformat(),
                "updated_by": admin_user_id
            }

            # Upsert the config
            result = await collection.update_one(
                {"key": key},
                {"$set": config_data},
                upsert=True
            )

            return result.acknowledged
        except Exception as e:
            logger.error("System configuration update failed: %s", type(e).__name__)
            return False

    async def delete_system_config(self, key: str) -> bool:
        """Delete a system configuration."""
        try:
            db = await self._get_db()
            collection = db._get_collection("system_config")
            result = await collection.delete_one({"key": key})
            return result.deleted_count > 0
        except Exception as e:
            logger.error("System configuration deletion failed: %s", type(e).__name__)
            return False

    # System AI Model configuration
    async def set_system_ai_model(self, model_id: str, admin_user_id: str) -> bool:
        """
        Set the system-wide AI model for all users.

        Args:
            model_id: The OpenAI model ID to use (e.g., 'gpt-5', 'gpt-5-mini')
            admin_user_id: ID of the admin making the change

        Returns:
            True if successful, False otherwise
        """
        try:
            from ai_models.models import AIModelConfig

            # Validate the model ID
            if not AIModelConfig.is_valid_model(model_id):
                logger.error("Invalid system AI model ID")
                return False

            return await self.set_system_config("system_ai_model", {
                "model_id": model_id,
                "configured_at": datetime.now().isoformat()
            }, admin_user_id)
        except Exception as e:
            logger.error("System AI model update failed: %s", type(e).__name__)
            return False

    async def get_system_ai_model(self) -> str:
        """
        Get the system-wide AI model.

        Returns:
            The configured model ID, or the default model if not configured.
        """
        try:
            config = await self.get_system_config("system_ai_model")
            if config and config.get("model_id"):
                return config["model_id"]

            # Return default model if not configured
            from ai_models.models import AIModelConfig
            return AIModelConfig.get_default_model()
        except Exception as e:
            logger.error("System AI model lookup failed: %s", type(e).__name__)
            from ai_models.models import AIModelConfig
            return AIModelConfig.get_default_model()

    async def get_system_ai_model_config(self) -> Optional[Dict[str, Any]]:
        """
        Get the full system AI model configuration including metadata.

        Returns:
            Dict with model_id, configured_at, and updated_by, or None if not configured.
        """
        return await self.get_system_config("system_ai_model")

    # Query Gate Model configuration (for conversation context gate)
    async def set_query_gate_model(self, model_id: str, admin_user_id: str) -> bool:
        """
        Set the query gate model used for conversation context detection.

        Args:
            model_id: The OpenAI model ID to use (e.g., 'gpt-5', 'gpt-5-nano')
            admin_user_id: ID of the admin making the change

        Returns:
            True if successful, False otherwise
        """
        try:
            from ai_models.models import AIModelConfig

            # Validate the model ID
            if not AIModelConfig.is_valid_model(model_id):
                logger.error("Invalid query gate model ID")
                return False

            return await self.set_system_config("query_gate_model", {
                "model_id": model_id,
                "configured_at": datetime.now().isoformat()
            }, admin_user_id)
        except Exception as e:
            logger.error("Query gate model update failed: %s", type(e).__name__)
            return False

    async def get_query_gate_model(self) -> str:
        """
        Get the query gate model for conversation context detection.

        Returns:
            The configured model ID, or gpt-5-nano as default (fast & cheap for gate calls).
        """
        try:
            config = await self.get_system_config("query_gate_model")
            if config and config.get("model_id"):
                return config["model_id"]

            # Return default lightweight model for gate calls
            return "gpt-5-nano"
        except Exception as e:
            logger.error("Query gate model lookup failed: %s", type(e).__name__)
            return "gpt-5-nano"

    async def get_query_gate_model_config(self) -> Optional[Dict[str, Any]]:
        """
        Get the full query gate model configuration including metadata.

        Returns:
            Dict with model_id, configured_at, and updated_by, or None if not configured.
        """
        return await self.get_system_config("query_gate_model")

    # Document Auto-Delete configuration
    async def set_auto_delete_config(self, days: int, admin_user_id: str) -> bool:
        """
        Configure the auto-delete period for user documents.

        Args:
            days: Number of days after which documents are auto-deleted (0 to disable)
            admin_user_id: ID of the admin making the change

        Returns:
            True if successful, False otherwise
        """
        return await self.set_system_config("document_auto_delete", {
            "enabled": days > 0,
            "days": days,
            "configured_at": datetime.now().isoformat()
        }, admin_user_id)

    async def get_auto_delete_config(self) -> Dict[str, Any]:
        """
        Get the auto-delete configuration.

        Returns:
            Dict with 'enabled' (bool), 'days' (int), and metadata
            Defaults to enabled=True, days=30 if not configured
        """
        config = await self.get_system_config("document_auto_delete")
        if not config:
            # Return default configuration
            return {
                "enabled": True,
                "days": 30,
                "configured_at": None,
                "updated_by": None
            }
        return {
            "enabled": config.get("enabled", True),
            "days": config.get("days", 30),
            "configured_at": config.get("configured_at"),
            "updated_by": config.get("updated_by")
        }

    # User Document Limit configuration
    async def set_document_limit_config(self, max_documents: int, admin_user_id: str) -> bool:
        """
        Configure the maximum number of documents a user can store.

        Args:
            max_documents: Maximum documents per user (0 for unlimited)
            admin_user_id: ID of the admin making the change

        Returns:
            True if successful, False otherwise
        """
        return await self.set_system_config("user_document_limit", {
            "enabled": max_documents > 0,
            "max_documents": max_documents,
            "configured_at": datetime.now().isoformat()
        }, admin_user_id)

    async def get_document_limit_config(self) -> Dict[str, Any]:
        """
        Get the document limit configuration.

        Returns:
            Dict with 'enabled' (bool), 'max_documents' (int), and metadata
            Defaults to enabled=True, max_documents=10 if not configured
        """
        config = await self.get_system_config("user_document_limit")
        if not config:
            # Return default configuration
            return {
                "enabled": True,
                "max_documents": 10,
                "configured_at": None,
                "updated_by": None
            }
        return {
            "enabled": config.get("enabled", True),
            "max_documents": config.get("max_documents", 10),
            "configured_at": config.get("configured_at"),
            "updated_by": config.get("updated_by")
        }

    async def get_user_document_count(self, user_id: str) -> int:
        """Get the number of documents a user has stored."""
        try:
            db = await self._get_db()
            collection = db._get_collection("documents")
            return await collection.count_documents({"user_id": user_id})
        except Exception as e:
            logger.error("User document count failed: %s", type(e).__name__)
            return 0

    async def can_user_upload_document(self, user_id: str) -> tuple[bool, str]:
        """
        Check if a user can upload another document.

        Returns:
            Tuple of (can_upload, message)
        """
        config = await self.get_document_limit_config()

        if not config.get("enabled", True):
            return True, "Document limit is disabled"

        max_docs = config.get("max_documents", 10)
        current_count = await self.get_user_document_count(user_id)

        if current_count >= max_docs:
            return False, f"Document limit reached. You have {current_count}/{max_docs} documents. Please delete some documents to upload more."

        return True, f"You have {current_count}/{max_docs} documents"

    # UI Settings configuration
    async def set_ui_settings(self, settings: Dict[str, Any], admin_user_id: str) -> bool:
        """
        Configure UI settings like toast notifications.

        Args:
            settings: Dict with UI settings (e.g., toast_notifications_enabled)
            admin_user_id: ID of the admin making the change

        Returns:
            True if successful, False otherwise
        """
        current = await self.get_ui_settings()
        updated = {**current, **settings, "configured_at": datetime.now().isoformat()}
        return await self.set_system_config("ui_settings", updated, admin_user_id)

    async def get_ui_settings(self) -> Dict[str, Any]:
        """
        Get UI settings configuration.

        Returns:
            Dict with UI settings
            Defaults to toast_notifications_enabled=True if not configured
        """
        config = await self.get_system_config("ui_settings")
        if not config:
            return {
                "toast_notifications_enabled": True,
                "configured_at": None,
                "updated_by": None
            }
        return {
            "toast_notifications_enabled": config.get("toast_notifications_enabled", True),
            "configured_at": config.get("configured_at"),
            "updated_by": config.get("updated_by")
        }

    async def get_expired_documents(self, days: int) -> List[Dict[str, Any]]:
        """
        Get documents that are older than the specified number of days.

        Args:
            days: Number of days after which documents are considered expired

        Returns:
            List of expired documents
        """
        try:
            from datetime import timedelta

            db = await self._get_db()
            collection = db._get_collection("documents")

            # Calculate the cutoff date
            cutoff_date = (datetime.utcnow() - timedelta(days=days)).isoformat()

            # Build query
            query = {
                "$or": [
                    {"created_at": {"$lt": cutoff_date}},
                    {"upload_date": {"$lt": cutoff_date}}  # Fallback for older documents
                ]
            }

            # Get expired documents
            cursor = collection.find(
                query,
                {"id": 1, "user_id": 1, "filename": 1, "created_at": 1, "upload_date": 1}
            )

            documents = []
            async for doc in cursor:
                doc["_id"] = str(doc["_id"])
                documents.append(doc)

            return documents

        except Exception as e:
            logger.error("Expired document lookup failed: %s", type(e).__name__)
            return []

    async def cleanup_expired_documents(self) -> Dict[str, Any]:
        """
        Delete documents that have exceeded the auto-delete period.

        Returns:
            Dict with cleanup statistics
        """
        result = {
            "deleted_count": 0,
            "failed_count": 0,
            "errors": [],
            "run_at": datetime.now().isoformat()
        }

        try:
            # Get auto-delete configuration
            config = await self.get_auto_delete_config()

            if not config.get("enabled"):
                logger.info("Document auto-delete is disabled, skipping cleanup")
                result["skipped"] = True
                result["reason"] = "Auto-delete is disabled"
                return result

            days = config.get("days", 30)
            if days <= 0:
                logger.info("Auto-delete days is 0 or negative, skipping cleanup")
                result["skipped"] = True
                result["reason"] = "Auto-delete days must be positive"
                return result

            # Get expired documents
            expired_docs = await self.get_expired_documents(days)

            if not expired_docs:
                logger.info(f"No documents older than {days} days found for cleanup")
                return result

            logger.info(f"Found {len(expired_docs)} documents older than {days} days for cleanup")

            # Delete each expired document
            for doc in expired_docs:
                try:
                    doc_id = doc.get("id")
                    user_id = doc.get("user_id")

                    if doc_id and user_id:
                        success = await self.delete_document_for_user(doc_id, user_id)
                        if success:
                            result["deleted_count"] += 1
                            logger.info("Auto-deleted expired document")
                        else:
                            result["failed_count"] += 1
                            result["errors"].append("Failed to delete an expired document")
                    else:
                        result["failed_count"] += 1
                        result["errors"].append("Expired document metadata is incomplete")

                except Exception as e:
                    result["failed_count"] += 1
                    result["errors"].append("Failed to delete an expired document")
                    logger.error("Expired document deletion failed: %s", type(e).__name__)

            logger.info(f"Auto-delete cleanup completed: {result['deleted_count']} deleted, {result['failed_count']} failed")

            return result

        except Exception as e:
            logger.error("Document cleanup failed: %s", type(e).__name__)
            result["errors"].append("Document cleanup failed")
            return result

    # ============ Password Reset Token Tracking (FND-002) ============

    async def is_reset_token_consumed(self, jti: str) -> bool:
        """Check if a password reset token jti has been consumed."""
        try:
            db = await self._get_db()
            collection = db._get_collection("consumed_reset_tokens")
            doc = await collection.find_one({"jti": jti})
            return doc is not None
        except Exception as e:
            logger.error("Reset token consumption check failed: %s", type(e).__name__)
            # Fail closed — treat as consumed if we can't verify
            return True

    async def consume_reset_token(self, jti: str) -> None:
        """Mark a password reset token jti as consumed (one-time use)."""
        try:
            from datetime import datetime, timezone
            db = await self._get_db()
            collection = db._get_collection("consumed_reset_tokens")
            await collection.insert_one({
                "jti": jti,
                "consumed_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as e:
            logger.error("Reset token update failed: %s", type(e).__name__)


# Global singleton instance
_document_service = None

def get_document_service() -> DocumentService:
    """Get async document service instance (singleton)."""
    global _document_service
    if _document_service is None:
        _document_service = DocumentService()
    return _document_service
