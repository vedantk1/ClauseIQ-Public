"""
Document management routes.
"""
import uuid
import logging
from datetime import datetime
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Response, Query
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from auth import get_current_user, verify_token
from database.service import get_document_service
from middleware.api_standardization import APIResponse
from middleware.versioning import versioned_response
from services.document_service import validate_file
from services.ai.text_extractor import get_text_extractor
from models.document import (
    DocumentListResponse,
    DocumentDetailResponse
)


router = APIRouter(tags=["documents"])
logger = logging.getLogger(__name__)

# PDF authentication now uses standard header auth only (FND-003: removed query-token path)
async def get_current_user_for_pdf(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=True))
):
    """Get current user for PDF viewing - uses Authorization header only."""
    from database.service import get_document_service

    auth_token = credentials.credentials

    if not auth_token:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Provide Authorization header."
        )

    # Verify token (sync function - no await needed)
    payload = verify_token(auth_token)
    if payload is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token"
        )

    user_id = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=401,
            detail="Invalid token payload"
        )

    # Get user from database
    service = get_document_service()
    user = await service.get_user_by_id(user_id)

    if user is None:
        raise HTTPException(
            status_code=401,
            detail="User not found"
        )

    return user


@router.post("/extract-text/", response_model=APIResponse[dict])
@versioned_response("1.0")
async def extract_text(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    """Extract text from uploaded PDF file."""
    try:
        validate_file(file)

        # Read file content
        content = await file.read()

        # Use TextExtractor service for extraction
        text_extractor = get_text_extractor()
        try:
            extracted_text = await text_extractor.extract_text(content, file.filename)

            return APIResponse(
                success=True,
                data={"text": extracted_text, "filename": file.filename},
                message="Text extracted successfully"
            )

        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Failed to extract text from PDF",
            )
        except Exception as extraction_error:
            logger.error(
                "PDF text extraction failed: %s",
                type(extraction_error).__name__,
            )
            raise HTTPException(
                status_code=500,
                detail="Failed to extract text from PDF",
            )

    except HTTPException:
        raise
    except Exception as validation_error:
        logger.error(
            "PDF validation failed: %s",
            type(validation_error).__name__,
        )
        raise HTTPException(
            status_code=400,
            detail="File validation failed",
        )


@router.get("/documents/", response_model=APIResponse[DocumentListResponse])
@versioned_response("1.0")
async def list_documents(current_user: dict = Depends(get_current_user)):
    """Get list of documents for the current user."""
    try:
        service = get_document_service()
        user_docs = await service.get_documents_for_user(current_user["id"])

        response_data = DocumentListResponse(documents=user_docs)
        return APIResponse(
            success=True,
            data=response_data,
            message="Documents retrieved successfully"
        )
    except Exception as e:
        logger.error("Document list retrieval failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve documents",
        )


@router.get("/documents/{document_id}", response_model=APIResponse[DocumentDetailResponse])
@versioned_response("1.0")
async def retrieve_document(document_id: str, current_user: dict = Depends(get_current_user)):
    """Get a specific document by ID."""
    try:
        service = get_document_service()
        document = await service.get_document_for_user(document_id, current_user["id"])

        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        response_data = DocumentDetailResponse(**document)
        return APIResponse(
            success=True,
            data=response_data,
            message="Document retrieved successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Document retrieval failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to retrieve document",
        )


@router.post("/documents/{document_id}/view", response_model=APIResponse[dict])
@versioned_response("1.0")
async def track_document_view(document_id: str, current_user: dict = Depends(get_current_user)):
    """Track that a document has been viewed by updating the last_viewed timestamp."""
    try:
        service = get_document_service()

        # First verify the document exists and belongs to the user
        document = await service.get_document_for_user(document_id, current_user["id"])
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Update the last_viewed timestamp
        success = await service.update_document_last_viewed(document_id, current_user["id"])

        if success:
            return APIResponse(
                success=True,
                data={"last_viewed": datetime.now().isoformat()},
                message="Document view tracked successfully"
            )
        else:
            raise HTTPException(
                status_code=500,
                detail="Failed to track document view",
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Document view tracking failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to track document view",
        )


@router.delete("/documents/{document_id}", response_model=APIResponse[dict])
@versioned_response("1.0")
async def delete_document(document_id: str, current_user: dict = Depends(get_current_user)):
    """Delete a specific document."""
    try:
        service = get_document_service()

        # First check if the document exists and belongs to the user
        document = await service.get_document_for_user(document_id, current_user["id"])
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Delete the document
        success = await service.delete_document_for_user(document_id, current_user["id"])
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to delete document",
            )

        return APIResponse(
            success=True,
            data={"message": "Document deleted successfully"},
            message="Document deleted successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Document deletion failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete document",
        )


@router.delete("/documents", response_model=APIResponse[dict])
@versioned_response("1.0")
async def delete_all_documents(current_user: dict = Depends(get_current_user)):
    """Delete all documents for the current user."""
    try:
        service = get_document_service()

        success = await service.delete_all_documents_for_user(current_user["id"])
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to delete documents",
            )

        return APIResponse(
            success=True,
            data={"message": "All documents deleted successfully"},
            message="All documents deleted successfully"
        )
    except Exception as e:
        logger.error("Bulk document deletion failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete documents",
        )


# PDF File Operations

@router.get("/documents/{document_id}/pdf")
async def download_pdf(
    document_id: str,
    current_user: dict = Depends(get_current_user_for_pdf)
):
    """Download the original PDF file for a document."""
    try:
        service = get_document_service()

        # First check if document exists and belongs to user
        document = await service.get_document_for_user(document_id, current_user["id"])
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Check if document has PDF file
        if not document.get('has_pdf_file', False):
            raise HTTPException(status_code=404, detail="PDF file not available for this document")

        # Get PDF file metadata and stream
        metadata, stream = await service.get_pdf_file_stream(document_id, current_user["id"])

        if not metadata or not stream:
            raise HTTPException(status_code=404, detail="PDF file not found")

        # Prepare response headers
        headers = {
            'Content-Type': metadata.get('content_type', 'application/pdf'),
            'Content-Length': str(metadata.get('file_size', 0)),
            'Content-Disposition': f'attachment; filename="{metadata.get("filename", "document.pdf")}"',
            'Cache-Control': 'private, max-age=3600',  # Cache for 1 hour
            'X-Document-ID': document_id
        }

        # Return streaming response
        return StreamingResponse(
            stream,
            media_type=metadata.get('content_type', 'application/pdf'),
            headers=headers
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("PDF download failed: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Failed to download PDF")


@router.head("/documents/{document_id}/pdf")
async def check_pdf_exists(document_id: str, current_user: dict = Depends(get_current_user)):
    """Check if PDF file exists for a document (HEAD request)."""
    try:
        service = get_document_service()

        # Check if document exists and belongs to user
        document = await service.get_document_for_user(document_id, current_user["id"])
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Check if document has PDF file
        has_pdf = await service.has_pdf_file(document_id, current_user["id"])

        if not has_pdf:
            raise HTTPException(status_code=404, detail="PDF file not available")

        # Return headers only
        return Response(
            status_code=200,
            headers={
                'Content-Type': 'application/pdf',
                'X-Has-PDF': 'true',
                'X-Document-ID': document_id
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("PDF availability check failed: %s", type(e).__name__)
        raise HTTPException(status_code=500, detail="Failed to check PDF")


@router.get("/documents/{document_id}/pdf/metadata", response_model=APIResponse[dict])
@versioned_response("1.0")
async def get_pdf_metadata(document_id: str, current_user: dict = Depends(get_current_user)):
    """Get PDF file metadata without downloading the file."""
    try:
        service = get_document_service()

        # Check if document exists and belongs to user
        document = await service.get_document_for_user(document_id, current_user["id"])
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")

        # Check if document has PDF file
        if not document.get('has_pdf_file', False):
            raise HTTPException(
                status_code=404,
                detail="PDF file not available for this document",
            )

        # Get PDF file metadata
        from services.file_storage_service import get_file_storage_service
        file_storage = get_file_storage_service()

        pdf_file_id = document.get('pdf_file_id')
        if not pdf_file_id:
            raise HTTPException(status_code=404, detail="PDF file not found")

        metadata = await file_storage.get_file_metadata(pdf_file_id, current_user["id"])

        if not metadata:
            raise HTTPException(status_code=404, detail="PDF file metadata not found")

        # Prepare response data
        response_data = {
            'document_id': document_id,
            'pdf_file_id': pdf_file_id,
            'filename': metadata.get('filename'),
            'content_type': metadata.get('content_type'),
            'file_size': metadata.get('file_size'),
            'upload_date': metadata.get('upload_date').isoformat() if metadata.get('upload_date') else None,
            'checksum': metadata.get('checksum'),
            'has_pdf_file': True
        }

        return APIResponse(
            success=True,
            data=response_data,
            message="PDF metadata retrieved successfully"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("PDF metadata retrieval failed: %s", type(e).__name__)
        raise HTTPException(
            status_code=500,
            detail="Failed to get PDF metadata",
        )
