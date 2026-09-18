"""
Chat Service for ClauseIQ Document Conversations.

Clean foundational architecture - ONE SESSION PER DOCUMENT.

FEATURES:
- Single session management per document
- Message history persistence in MongoDB
- Integration with RAG service for intelligent responses
- Source attribution and transparency
- Workspace isolation and security
- 🤖 AI-friendly debug logging for troubleshooting
"""
import logging
import uuid
from typing import List, Dict, Any, Optional
from datetime import datetime

from database.service import get_document_service
from services.rag_service import get_rag_service, ChatMessage, ChatSession
from services.ai.generation import AIRequestError, generation_metadata

# 🤖 AI DEBUG INTEGRATION
from utils.ai_debug_helper import ai_debug, DebugLevel

logger = logging.getLogger(__name__)

class ChatService:
    """Service for managing document chat functionality."""

    def __init__(self):
        self.doc_service = get_document_service()
        self.rag_service = get_rag_service()

    async def is_available(self) -> bool:
        """Check if chat service is available."""
        return await self.rag_service.is_available()

    # 🚀 FOUNDATIONAL ARCHITECTURE: ONE SESSION PER DOCUMENT
    async def get_or_create_session(self, document_id: str, workspace_id: str) -> Dict[str, Any]:
        """
        🎯 FOUNDATIONAL METHOD: Get or create THE single session for a document.

        This implements the core architectural principle:
        ONE SESSION PER DOCUMENT - No more session chaos!

        Returns THE session for this document, creating it if needed.
        """
        try:
            # Verify user owns the document
            document = await self.doc_service.get_document_for_workspace(document_id, workspace_id)
            if not document:
                ai_debug.log_api_error(
                    endpoint="chat_session",
                    error_type="document_not_found",
                    message="Document not found or access denied",
                    details={"status": "failed"}
                )
                return {
                    "success": False,
                    "error": "Document not found or access denied"
                }

            # Check if document has RAG enabled
            if not document.get("rag_processed", False):
                ai_debug.log_api_error(
                    endpoint="chat_session",
                    error_type="rag_not_processed",
                    message="Document not ready for chat",
                    details={"status": "not_ready"}
                )
                return {
                    "success": False,
                    "error": "Document is not ready for chat. Please wait for processing to complete."
                }

            # 🎯 FOUNDATIONAL: Atomically get or create THE session (race condition free!)
            session_id = str(uuid.uuid4())
            now = datetime.utcnow().isoformat()

            session_data = {
                "session_id": session_id,
                "document_id": document_id,
                "workspace_id": workspace_id,
                "messages": [],
                "created_at": now,
                "updated_at": now
            }

            # Use atomic operation to prevent race conditions
            session_result = await self.doc_service.create_or_get_chat_session(
                document_id, workspace_id, session_data
            )

            if not session_result:
                ai_debug.log_api_error(
                    endpoint="chat_session",
                    error_type="session_creation_failed",
                    message="Failed to create or get chat session",
                    details={"status": "failed"}
                )
                return {
                    "success": False,
                    "error": "Failed to create chat session"
                }

            # Check if session was created or already existed
            if session_result["created"]:
                logger.info("Created new document chat session")
            else:
                logger.info("Retrieved existing document chat session")

            session = session_result["session"]
            ai_debug.log_system_event(
                event_type="CHAT_SESSION_CREATED",
                level=DebugLevel.INFO,
                message="Created new document chat session",
                context={"status": "created"}
            )

            return {
                "success": True,
                "session": session
            }

        except Exception as e:
            logger.error("Chat session operation failed: %s", type(e).__name__)
            ai_debug.log_system_event(
                event_type="CHAT_ERROR",
                level=DebugLevel.ERROR,
                message="Chat operation failed",
                context={"error_type": "unexpected_error"},
                error=e,
            )
            return {
                "success": False,
                "error": "Failed to get or create chat session"
            }

    async def send_message(
        self,
        document_id: str,
        workspace_id: str,
        message: str
    ) -> Dict[str, Any]:
        """
        🎯 FOUNDATIONAL METHOD: Send message to THE document session.

        Clean, simple architecture - no session_id needed!
        """
        try:
            # Get or create THE session
            session_result = await self.get_or_create_session(document_id, workspace_id)
            if not session_result["success"]:
                return session_result

            session = session_result["session"]

            # Get document for processing
            document = await self.doc_service.get_document_for_workspace(document_id, workspace_id)
            if not document:
                return {
                    "success": False,
                    "error": "Document not found"
                }

            # Process the message
            return await self._process_message_foundational(document, session, message, workspace_id)

        except AIRequestError:
            raise
        except Exception as e:
            logger.error("Chat message send failed: %s", type(e).__name__)
            ai_debug.log_system_event(
                event_type="CHAT_ERROR",
                level=DebugLevel.ERROR,
                message="Chat operation failed",
                context={"error_type": "send_message_error"},
                error=e,
            )
            return {
                "success": False,
                "error": "Failed to send message"
            }

    async def get_session_history(self, document_id: str, workspace_id: str) -> Dict[str, Any]:
        """
        🎯 FOUNDATIONAL METHOD: Get chat history for THE document session.
        """
        try:
            session_result = await self.get_or_create_session(document_id, workspace_id)
            if not session_result["success"]:
                return session_result

            session = session_result["session"]

            return {
                "success": True,
                "session_id": session["session_id"],
                "messages": session.get("messages", []),
                "created_at": session["created_at"],
                "updated_at": session["updated_at"]
            }

        except Exception as e:
            logger.error("Chat history retrieval failed: %s", type(e).__name__)
            return {
                "success": False,
                "error": "Failed to get session history"
            }

    async def _process_message_foundational(self, document: dict, session: dict, message: str, workspace_id: str) -> Dict[str, Any]:
        """Process message using foundational architecture (single session)."""
        import time

        try:
            document_id = document["id"]
            session_id = session["session_id"]

            # Get user's preferred model early for use throughout the process
            workspace_model = await self.doc_service.get_workspace_model(workspace_id)
            # Fail before helper-model or embedding spend when the main model
            # selection or its completion budget cannot be used.
            generation_metadata(workspace_model, "chat")
            logger.info("Chat model selected: %s", workspace_model)

            # Create user message
            user_message = {
                "id": str(uuid.uuid4()),
                "role": "user",
                "content": message,
                "timestamp": datetime.utcnow().isoformat()
            }

            # Add user message to session atomically
            await self.doc_service.add_chat_message_atomic(document_id, workspace_id, user_message)

            # 🚀 STEP 1: Service Availability Check
            step_start = time.time()
            if not await self.rag_service.is_available():
                ai_debug.log_rag_pipeline_step(
                    step_name="service_availability",
                    success=False,
                    duration_ms=round((time.time() - step_start) * 1000, 2),
                    details={"error": "RAG service not available"}
                )
                return {
                    "success": False,
                    "error": "AI service is currently unavailable. Please try again later."
                }

            availability_time = round((time.time() - step_start) * 1000, 2)
            ai_debug.log_rag_pipeline_step(
                step_name="service_availability",
                success=True,
                duration_ms=availability_time,
                details={"status": "available"}
            )

            # 🚀 STEP 2: Document RAG Status Check
            step_start = time.time()
            if not document.get("rag_processed", False):
                ai_debug.log_rag_pipeline_step(
                    step_name="document_rag_status",
                    success=False,
                    duration_ms=round((time.time() - step_start) * 1000, 2),
                    details={"error": "Document not RAG processed"}
                )
                return {
                    "success": False,
                    "error": "Document is not ready for chat. Please wait for processing to complete."
                }

            rag_status_time = round((time.time() - step_start) * 1000, 2)
            ai_debug.log_rag_pipeline_step(
                step_name="document_rag_status",
                success=True,
                duration_ms=rag_status_time,
                details={"rag_processed": True, "chunk_count": document.get("rag_chunk_count", 0)}
            )

            # 🚀 STEP 3: Vector Retrieval
            step_start = time.time()
            conversation_history = [
                {
                    "role": msg["role"],
                    "content": msg["content"]
                }
                for msg in session["messages"][-10:]  # Last 10 messages for context
            ]

            rag_result = await self.rag_service.retrieve_relevant_chunks(
                message, document_id, workspace_id, conversation_history
            )

            retrieval_time = round((time.time() - step_start) * 1000, 2)

            if not rag_result or not rag_result.get("chunks"):
                ai_debug.log_rag_pipeline_step(
                    step_name="vector_retrieval",
                    success=False,
                    duration_ms=retrieval_time,
                    details={"status": "no_relevant_chunks"}
                )

                # Create fallback response
                assistant_message = {
                    "id": str(uuid.uuid4()),
                    "role": "assistant",
                    "content": "I couldn't find relevant information in the document to answer your question. Please try rephrasing your question or asking about a different topic covered in the document.",
                    "timestamp": datetime.utcnow().isoformat(),
                    "sources": [],
                    "model_used": None,
                }
            else:
                relevant_chunks = rag_result["chunks"]
                enhanced_query = rag_result.get("enhanced_query", message)

                ai_debug.log_rag_pipeline_step(
                    step_name="vector_retrieval",
                    success=True,
                    duration_ms=retrieval_time,
                    details={
                        "query_rewritten": enhanced_query != message,
                        "chunks_found": len(relevant_chunks),
                        "similarity_scores": [chunk.get("similarity_score", 0) for chunk in relevant_chunks[:3]]
                    }
                )

                # 🚀 STEP 4: LLM Response Generation
                step_start = time.time()
                response_result = await self._generate_ai_response(document, message, conversation_history, relevant_chunks, enhanced_query, workspace_model)
                generation_time = round((time.time() - step_start) * 1000, 2)

                if response_result.get("success", False):
                    model_used = response_result.get("model", workspace_model or "unknown")  # Fallback to workspace_model
                    ai_debug.log_rag_pipeline_step(
                        step_name="llm_generation",
                        success=True,
                        duration_ms=generation_time,
                        details={
                            "response_length": len(response_result["content"]),
                            "sources_included": len(response_result.get("sources", [])),
                            "model": model_used
                        }
                    )

                    logger.info("Chat response generated: model=%s", model_used)

                    assistant_message = {
                        "id": str(uuid.uuid4()),
                        "role": "assistant",
                        "content": response_result["content"],
                        "timestamp": datetime.utcnow().isoformat(),
                        "sources": response_result.get("sources", []),
                        "model_used": model_used,
                        "generation": response_result.get("generation"),
                    }
                else:
                    ai_debug.log_rag_pipeline_step(
                        step_name="llm_generation",
                        success=False,
                        duration_ms=generation_time,
                        details={"status": "generation_failed"}
                    )

                    raise AIRequestError("Chat response generation failed. Please retry.")

            # Add assistant message to session atomically
            update_result = await self.doc_service.add_chat_message_atomic(document_id, workspace_id, assistant_message)

            if not update_result:
                logger.warning("Failed to save assistant chat message")

            # Log successful chat completion
            ai_debug.log_system_event(
                event_type="CHAT_MESSAGE_PROCESSED",
                level=DebugLevel.INFO,
                message="Chat message processed",
                context={
                    "status": "processed",
                    "message_length": len(message),
                    "response_length": len(assistant_message["content"]),
                    "sources_count": len(assistant_message.get("sources", [])),
                },
            )

            return {
                "success": True,
                "message": assistant_message,
                "session_id": session_id
            }

        except AIRequestError:
            raise
        except Exception as e:
            logger.error("Chat message processing failed: %s", type(e).__name__)
            ai_debug.log_system_event(
                event_type="CHAT_ERROR",
                level=DebugLevel.ERROR,
                message="Chat operation failed",
                context={"error_type": "message_processing_error"},
                error=e,
            )
            return {
                "success": False,
                "error": "Failed to process message"
            }

    async def _generate_ai_response(self, document: dict, message: str, conversation_history: list, relevant_chunks: list, enhanced_query: str = None, workspace_model: str = None) -> dict:
        """Generate AI response using the RAG service."""
        try:
            # Format context from relevant chunks
            context_text = "\n\n".join([
                f"Source {i+1}:\n{chunk['content']}"
                for i, chunk in enumerate(relevant_chunks[:5])
            ])

            # Build conversation context
            recent_messages = conversation_history[-6:] if len(conversation_history) > 6 else conversation_history
            conversation_context = ""
            if recent_messages:
                conversation_context = "Previous conversation:\n"
                for msg in recent_messages[:-1]:  # Exclude the current message
                    role = "User" if msg["role"] == "user" else "Assistant"
                    conversation_context += f"{role}: {msg['content']}\n"
                conversation_context += "\n"

            # Create prompt
            prompt = f"""You are an AI assistant helping users understand legal documents. Answer the user's question based on the provided document context.

{conversation_context}Document Context:
{context_text}

User Question: {message}

Please provide a clear, helpful answer based on the document content. If the context doesn't contain enough information to answer the question, say so clearly."""

            # Get AI response from RAG service with user's preferred model
            logger.info(f"🎯 [CHAT MODEL] Using AI model '{workspace_model}' for chat response")

            ai_response = await self.rag_service.generate_rag_response(
                query=message,
                relevant_chunks=relevant_chunks,
                enhanced_query=enhanced_query,
                model=workspace_model
            )

            if ai_response and ai_response.get("response") and not ai_response.get("error"):
                # Format sources for transparency
                sources = []
                for i, chunk in enumerate(relevant_chunks[:3]):
                    sources.append({
                        "chunk_id": chunk.get("chunk_id", f"chunk_{i+1}"),
                        "text_preview": chunk["content"][:200] + "..." if len(chunk["content"]) > 200 else chunk["content"],
                        "similarity_score": chunk.get("similarity_score", 0)
                    })

                return {
                    "success": True,
                    "content": ai_response["response"],
                    "sources": sources,
                    "model": ai_response.get("model", workspace_model or "unknown"),
                    "generation": ai_response.get("generation"),
                }
            else:
                return {
                    "success": False,
                    "model": workspace_model or "unknown",
                    "error": ai_response.get("error", "Failed to generate response") if ai_response else "No response from AI service"
                }

        except AIRequestError:
            raise
        except Exception as e:
            logger.error("Chat AI response generation failed: %s", type(e).__name__)
            return {
                "success": False,
                "model": workspace_model or "unknown",
                "error": "Failed to generate AI response"
            }

    async def clear_chat_history(self, document_id: str, workspace_id: str) -> Dict[str, Any]:
        """Clear all messages from a chat session while keeping the session structure."""
        try:
            logger.info("Clearing document chat history")

            # First, get the current session to count messages before clearing
            session_result = await self.get_or_create_session(document_id, workspace_id)
            if not session_result["success"]:
                return {
                    "success": False,
                    "error": "Failed to get current session"
                }

            session = session_result["session"]
            session_id = session["session_id"]
            messages_count = len(session.get("messages", []))

            # Clear messages from the session
            clear_result = await self.doc_service.clear_chat_messages(document_id, workspace_id)

            if not clear_result:
                logger.error("Failed to clear chat session messages")
                return {
                    "success": False,
                    "error": "Failed to clear chat history"
                }

            logger.info("Cleared %s chat messages", messages_count)

            return {
                "success": True,
                "data": {
                    "session_id": session_id,
                    "messages_cleared": messages_count
                }
            }

        except Exception as e:
            logger.error("Chat history clearing failed: %s", type(e).__name__)
            return {
                "success": False,
                "error": "Failed to clear chat history"
            }

# Global singleton instance
_chat_service = None

def get_chat_service() -> ChatService:
    """Get global chat service instance (singleton)."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
