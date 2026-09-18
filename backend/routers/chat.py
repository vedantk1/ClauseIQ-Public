"""
Chat API Router for ClauseIQ Document Conversations.

Clean foundational architecture - ONE SESSION PER DOCUMENT.

Provides REST endpoints for document chat functionality:
- Get/create THE session for a document
- Send messages and get AI responses
- Retrieve chat history
- Chat system health

SECURITY:
- All API requests pass the local browser boundary
- Document and session operations remain scoped to the local workspace
- Proper error handling and validation
"""
from typing import Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field

from workspace import get_workspace_id
from middleware.api_standardization import APIResponse, create_success_response_with_request, create_error_response_with_request
from middleware.versioning import versioned_response
from services.chat_service import get_chat_service
from services.qdrant_vector_service import get_qdrant_vector_service
from config.logging import get_foundational_logger, log_exception
from database.service import get_document_service
from routers.serialization import without_legacy_owner_fields

# 🚀 FOUNDATIONAL LOGGING: Proper chat logger
logger = get_foundational_logger("chat")

router = APIRouter(tags=["chat"])

# Request/Response Models
class SendMessageRequest(BaseModel):
    """Request to send a message to THE document session."""
    message: str = Field(..., min_length=1, max_length=2000, description="Message content")

class ChatMessageResponse(BaseModel):
    """Response model for a chat message."""
    role: str
    content: str
    timestamp: str
    id: str
    sources: list = []
    model_used: Optional[str] = None  # Add model_used field

class SendMessageResponse(BaseModel):
    """Response for sending a message."""
    message: ChatMessageResponse
    session_id: str

class SessionResponse(BaseModel):
    """Response for getting/creating THE session."""
    session_id: str
    document_id: str
    workspace_id: str
    created_at: str
    updated_at: str
    message_count: int
    messages: list = []

class ChatHistoryResponse(BaseModel):
    """Response for chat history."""
    session_id: str
    messages: list
    created_at: str
    updated_at: str

class HealthResponse(BaseModel):
    """Response for health check."""
    chat_service: str
    rag_service: str
    vector_storage: str
    timestamp: str


# 🚀 FOUNDATIONAL ENDPOINTS

@router.post("/{document_id}/session", response_model=APIResponse[SessionResponse])
async def get_or_create_session(
    document_id: str,
    request: Request,
    workspace_id: str = Depends(get_workspace_id)
):
    """
    🎯 FOUNDATIONAL: Get or create THE single session for a document.

    Simple, clean architecture - no session management complexity!
    """
    try:
        logger.info("Chat operation started: operation=get_or_create_session")

        chat_service = get_chat_service()
        result = await chat_service.get_or_create_session(document_id, workspace_id)

        if not result["success"]:
            logger.warning(
                "Chat operation failed: operation=get_or_create_session"
            )
            error_message = str(result.get("error", "")).lower()
            if "not found" in error_message or "access denied" in error_message:
                raise HTTPException(
                    status_code=404,
                    detail="Document not found or access denied",
                )
            if "not ready" in error_message:
                raise HTTPException(
                    status_code=422,
                    detail="Document is not ready for chat",
                )
            raise HTTPException(
                status_code=400,
                detail="Failed to get or create chat session",
            )

        session = result["session"]

        response_data = SessionResponse(
            session_id=session["session_id"],
            document_id=session["document_id"],
            workspace_id=session["workspace_id"],
            created_at=session["created_at"],
            updated_at=session["updated_at"],
            message_count=len(session.get("messages", [])),
            messages=without_legacy_owner_fields(session.get("messages", []))
        )

        logger.info("Chat operation completed: operation=get_or_create_session")
        return create_success_response_with_request(
            data=response_data,
            message="Session ready",
            request=request
        )

    except HTTPException:
        raise
    except Exception as error:
        log_exception(logger, "get_or_create_session", error)
        raise HTTPException(
            status_code=500,
            detail="Failed to get or create session",
        ) from None


@router.post("/{document_id}/message", response_model=APIResponse[SendMessageResponse])
async def send_message(
    document_id: str,
    message_data: SendMessageRequest,
    request: Request,
    workspace_id: str = Depends(get_workspace_id)
):
    """
    🎯 FOUNDATIONAL: Send message to THE document session.

    No session_id needed - just send to THE session!
    Requires an OpenAI API key in workspace settings.
    """
    try:
        logger.info("Chat operation started: operation=send_message")

        # Check if workspace has an API key set
        doc_service = get_document_service()
        workspace_api_key = await doc_service.get_workspace_api_key(workspace_id)
        if not workspace_api_key:
            raise HTTPException(
                status_code=400,
                detail="Please add your OpenAI API key in Settings before using chat."
            )

        # Use the workspace API key for all AI operations
        from services.ai.client_manager import workspace_openai_client

        async with workspace_openai_client(workspace_api_key):
            chat_service = get_chat_service()
            result = await chat_service.send_message(
                document_id=document_id,
                workspace_id=workspace_id,
                message=message_data.message
            )

            if not result["success"]:
                logger.warning("Chat operation failed: operation=send_message")
                error_message = str(result.get("error", "")).lower()
                if "not found" in error_message:
                    raise HTTPException(
                        status_code=404,
                        detail="Document not found",
                    )
                if "not ready" in error_message or "not available" in error_message:
                    raise HTTPException(
                        status_code=503,
                        detail="Chat is not currently available for this document",
                    )
                raise HTTPException(
                    status_code=400,
                    detail="Failed to send message",
                )

            message = result["message"]

            response_data = SendMessageResponse(
                message=ChatMessageResponse(
                    role=message["role"],
                    content=message["content"],
                    timestamp=message["timestamp"],
                    id=message["id"],
                    sources=message.get("sources", []),
                    model_used=message.get("model_used")  # Include model_used field
                ),
                session_id=result["session_id"]
            )

            logger.info("Chat operation completed: operation=send_message")
            return create_success_response_with_request(
                data=response_data,
                message="Message sent successfully",
                request=request
            )

    except HTTPException:
        raise
    except Exception as error:
        log_exception(logger, "send_message", error)
        raise HTTPException(
            status_code=500,
            detail="Failed to send message",
        ) from None


@router.get("/{document_id}/history", response_model=APIResponse[ChatHistoryResponse])
async def get_chat_history(
    document_id: str,
    request: Request,
    workspace_id: str = Depends(get_workspace_id)
):
    """
    🎯 FOUNDATIONAL: Get chat history for THE document session.
    """
    try:
        logger.info("Chat operation started: operation=get_chat_history")

        chat_service = get_chat_service()
        result = await chat_service.get_session_history(document_id, workspace_id)

        if not result["success"]:
            logger.warning(
                "Chat operation failed: operation=get_chat_history"
            )
            error_message = str(result.get("error", "")).lower()
            if "not found" in error_message:
                raise HTTPException(
                    status_code=404,
                    detail="Document or chat history not found",
                )
            raise HTTPException(
                status_code=400,
                detail="Failed to get chat history",
            )

        response_data = ChatHistoryResponse(
            session_id=result["session_id"],
            messages=without_legacy_owner_fields(result["messages"]),
            created_at=result["created_at"],
            updated_at=result["updated_at"]
        )

        logger.info(
            "Chat operation completed: operation=get_chat_history message_count=%s",
            len(result["messages"]),
        )
        return create_success_response_with_request(
            data=response_data,
            message="Chat history retrieved successfully",
            request=request
        )

    except HTTPException:
        raise
    except Exception as error:
        log_exception(logger, "get_chat_history", error)
        raise HTTPException(
            status_code=500,
            detail="Failed to get chat history",
        ) from None


@router.get("/{document_id}/status", response_model=APIResponse[dict])
async def get_chat_status(
    document_id: str,
    request: Request,
    workspace_id: str = Depends(get_workspace_id)
):
    """Check if a document is ready for chat."""
    try:
        logger.info("Chat operation started: operation=get_chat_status")

        chat_service = get_chat_service()

        # Try to get or create session to check document status
        result = await chat_service.get_or_create_session(document_id, workspace_id)

        if result["success"]:
            session = result["session"]
            status_data = {
                "ready": True,
                "chat_available": True,  # Frontend expects this field
                "ready_for_chat": True,  # Frontend expects this field
                "rag_processed": True,   # Frontend expects this field
                "processing_status": "ready",  # Frontend expects this field
                "session_id": session["session_id"],
                "message_count": len(session.get("messages", [])),
                "last_updated": session["updated_at"],
                "chunk_count": 0,  # Could be populated from document
                "text_length": 0   # Could be populated from document
            }
            logger.info(
                "Chat operation completed: operation=get_chat_status status=ready"
            )
        else:
            service_error = str(result.get("error", "")).lower()
            if "not found" in service_error or "access denied" in service_error:
                reason = "Document not found or access denied"
            elif "not ready" in service_error:
                reason = "Document is not ready for chat"
            else:
                reason = "Chat is unavailable for this document"

            status_data = {
                "ready": False,
                "chat_available": False,
                "ready_for_chat": False,
                "rag_processed": False,
                "processing_status": "error",
                "reason": reason,
                "error": reason,
            }
            logger.info(
                "Chat operation completed: operation=get_chat_status status=unavailable"
            )

        return create_success_response_with_request(
            data=status_data,
            message="Chat status retrieved",
            request=request
        )

    except HTTPException:
        raise
    except Exception as error:
        log_exception(logger, "get_chat_status", error)
        raise HTTPException(
            status_code=500,
            detail="Failed to get chat status",
        ) from None


@router.get("/health", response_model=APIResponse[HealthResponse])
async def get_health_status(request: Request):
    """Get health status of chat-related services."""
    try:
        logger.info("🏥 Checking chat system health")

        chat_service = get_chat_service()
        vector_service = get_qdrant_vector_service()

        # Check chat service
        chat_available = await chat_service.is_available()
        chat_status = "healthy" if chat_available else "unhealthy"

        # Check RAG service
        rag_available = await chat_service.rag_service.is_available()
        rag_status = "healthy" if rag_available else "unhealthy"

        # Check vector storage (Qdrant)
        try:
            await vector_service.get_total_storage_usage()
            vector_status = "healthy"
        except Exception:
            vector_status = "unhealthy"

        response_data = HealthResponse(
            chat_service=chat_status,
            rag_service=rag_status,
            vector_storage=vector_status,
            timestamp=datetime.utcnow().isoformat()
        )

        overall_status = "All systems healthy" if all([
            chat_status == "healthy",
            rag_status == "healthy",
            vector_status == "healthy"
        ]) else "Some systems experiencing issues"

        logger.info(
            "Chat operation completed: operation=health_check status=%s",
            "healthy" if "All systems" in overall_status else "degraded",
        )
        return create_success_response_with_request(
            data=response_data,
            message=overall_status,
            request=request
        )

    except HTTPException:
        raise
    except Exception as error:
        log_exception(logger, "health_check", error)
        raise HTTPException(
            status_code=500,
            detail="Health check failed",
        ) from None


@router.delete("/{document_id}/history", response_model=APIResponse[Dict[str, Any]])
async def clear_chat_history(
    document_id: str,
    request: Request,
    workspace_id: str = Depends(get_workspace_id)
) -> APIResponse[Dict[str, Any]]:
    """
    🗑️ Clear chat history for a document.

    Removes all messages from the chat session while keeping the session structure.
    """
    try:
        logger.info("Chat operation started: operation=clear_chat_history")

        chat_service = get_chat_service()
        result = await chat_service.clear_chat_history(document_id, workspace_id)

        if result["success"]:
            logger.info(
                "Chat operation completed: operation=clear_chat_history "
                "message_count=%s",
                result["data"]["messages_cleared"],
            )
            return create_success_response_with_request(
                data=result["data"],
                message=f"Chat history cleared ({result['data']['messages_cleared']} messages removed)",
                request=request
            )
        else:
            logger.warning(
                "Chat operation failed: operation=clear_chat_history"
            )
            raise HTTPException(
                status_code=400,
                detail="Failed to clear chat history",
            )

    except HTTPException:
        raise
    except Exception as error:
        log_exception(logger, "clear_chat_history", error)
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from None
