"""
Document processing utilities.
"""
import os
import uuid
import logging
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional
from fastapi import UploadFile, HTTPException
from config.environments import get_environment_config
from models.common import Clause, ClauseType, RiskLevel, ContractType
from services.ai.generation import AIRequestError

logger = logging.getLogger(__name__)


# Get settings instance
settings = get_environment_config()
MAX_FILE_SIZE_BYTES = settings.file_upload.max_file_size_mb * 1024 * 1024


def validate_file(file: UploadFile):
    """Validate uploaded file for size, type, and security."""
    # Check file size
    if hasattr(file, 'size') and file.size and file.size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size allowed: {settings.file_upload.max_file_size_mb}MB"
        )

    # Check file type if filename is provided
    if file.filename:
        # Check for unsafe filename patterns
        if '..' in file.filename or '/' in file.filename or '\\' in file.filename:
            raise HTTPException(
                status_code=400,
                detail="Invalid filename - path traversal characters not allowed"
            )

        # Check file extension
        if not any(file.filename.lower().endswith(ext) for ext in settings.file_upload.allowed_file_types):
            raise HTTPException(
                status_code=400,
                detail=f"File type not supported. Allowed types: {', '.join(settings.file_upload.allowed_file_types)}"
            )


async def process_document_with_llm(document_text: str, filename: str = "", model: str = None) -> Tuple[ContractType, List[Clause]]:
    """
    Process a document using LLM-based analysis.

    Raises:
        Exception: When AI is not available or LLM processing fails

    Returns:
        Tuple of (contract_type, clauses)
    """
    # Get model from settings if not provided
    if model is None:
        from config.environments import get_environment_config
        config = get_environment_config()
        model = config.ai.default_model

    # MIGRATED: Using new modular AI services for better maintainability
    from services.ai_service import (
        detect_contract_type,
        extract_clauses_with_llm,
    )
    from services.ai.client_manager import is_ai_available  # New modular import

    if not is_ai_available():
        raise Exception("AI processing is not available. Please check OpenAI API configuration.")

    try:
        # Step 1: Detect contract type
        logger.info("Detecting contract type")
        contract_type = await detect_contract_type(document_text, filename, model)
        logger.info("Contract type detected")

        # Step 2: Extract clauses using LLM
        logger.info("Extracting clauses with LLM")
        clauses = await extract_clauses_with_llm(document_text, contract_type, model)
        logger.info("Extracted %s clauses", len(clauses))

        return contract_type, clauses

    except AIRequestError:
        raise
    except Exception as e:
        logger.error("LLM document processing failed: %s", type(e).__name__)
        # Re-raise the exception instead of falling back to heuristics
        raise RuntimeError("AI analysis failed") from None


def is_llm_processing_available() -> bool:
    """Check if LLM-based document processing is available."""
    # MIGRATED: Using new modular AI client manager
    from services.ai.client_manager import is_ai_available
    return is_ai_available()


def calculate_risk_summary(clauses: List[Clause]) -> Dict[str, int]:
    """
    Calculate risk summary from list of clauses.

    Args:
        clauses: List of Clause objects

    Returns:
        Dictionary with counts of high, medium, and low risk clauses
    """
    return {
        "high": sum(1 for clause in clauses if clause.risk_level == RiskLevel.HIGH),
        "medium": sum(1 for clause in clauses if clause.risk_level == RiskLevel.MEDIUM),
        "low": sum(1 for clause in clauses if clause.risk_level == RiskLevel.LOW)
    }


def build_document_data(
    doc_id: str,
    filename: str,
    extracted_text: str,
    clauses: List[Clause],
    contract_type: ContractType,
    workspace_id: str,
    ai_structured_summary: Optional[Dict[str, Any]] = None,
    analysis_generation: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build document data dictionary for storage.

    Args:
        doc_id: Document ID
        filename: Original filename
        extracted_text: Extracted text content
        clauses: List of analyzed clauses
        contract_type: Detected contract type
        workspace_id: User ID
        ai_structured_summary: Optional AI-generated summary

    Returns:
        Document data dictionary ready for storage
    """
    risk_summary = calculate_risk_summary(clauses)

    return {
        "id": doc_id,
        "filename": filename,
        "upload_date": datetime.now().isoformat(),
        "text": extracted_text,
        "ai_structured_summary": ai_structured_summary,
        "analysis_generation": analysis_generation,
        "clauses": [clause.dict() for clause in clauses],
        "risk_summary": risk_summary,
        "contract_type": contract_type.value if contract_type else None,
        "workspace_id": workspace_id
    }


async def process_and_save_analyzed_document(
    doc_id: str,
    filename: str,
    extracted_text: str,
    clauses: List[Clause],
    contract_type: ContractType,
    workspace_id: str,
    ai_structured_summary: Optional[Dict[str, Any]],
    file_content: Optional[bytes] = None,
    content_type: str = "application/pdf",
    analysis_generation: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[str]]:
    """Attach analysis to a fresh, confirmed source, then optionally index it.

    Source import owns the bytes and document identity. The legacy byte/MIME
    arguments remain accepted for call compatibility but never store or replace
    a file. A conditional update prevents overwriting existing analysis.
    """
    from database.service import get_document_service
    from services.rag_service import get_rag_service

    service = get_document_service()

    # Save generated work before any optional embeddings/vector dependency.
    try:
        imported = await service.get_document_for_workspace(doc_id, workspace_id)
        if (
            not imported
            or not imported.get("source_revision_id")
            or imported.get("source_status") != "stored"
            or imported.get("has_pdf_file") is not True
            or imported.get("extraction_status") != "complete"
            or imported.get("analysis_status") != "processing"
            or imported.get("clauses") is not None
            or imported.get("text") != extracted_text
        ):
            return False, "A confirmed stored original is required before saving analysis"
        document_data = {
            "ai_structured_summary": ai_structured_summary,
            "analysis_generation": analysis_generation,
            "clauses": [clause.model_dump() for clause in clauses],
            "risk_summary": calculate_risk_summary(clauses),
            "contract_type": contract_type.value if contract_type else None,
            "analysis_status": "ready", "analysis_error": None,
            "rag_processed": False, "ready_for_chat": False,
        }
        saved = await service.update_document_if(
            doc_id, workspace_id,
            {"source_revision_id": imported["source_revision_id"], "source_status": "stored",
             "has_pdf_file": True, "extraction_status": "complete", "analysis_status": "processing",
             "clauses": None},
            document_data,
        )
        if not saved:
            return False, "Failed to save document"
    except Exception as save_error:
        logger.error("Document analysis save failed: %s", type(save_error).__name__)
        return False, "Failed to save document"

    try:
        rag_service = get_rag_service()
        logger.info("Starting RAG processing")

        rag_data = await rag_service.process_document_for_rag(
            document_id=doc_id,
            text=extracted_text,
            filename=imported["filename"],
            workspace_id=workspace_id
        )

        # Indexing is optional; failure never erases the already saved analysis.
        if rag_data:
            rag_metadata = {
                "rag_processed": True,
                "vector_stored": rag_data.get("vector_stored", False),
                "chunk_count": rag_data.get("chunk_count", 0),
                "chunk_ids": rag_data.get("chunk_ids", []),
                "embedding_model": rag_data.get("embedding_model"),
                "rag_processed_at": rag_data.get("processed_at"),
                "storage_service": rag_data.get("storage_service"),
                "ready_for_chat": bool(rag_data.get("vector_stored", False)),
            }
            if not await service.update_document_if(
                doc_id, workspace_id,
                {"source_revision_id": imported["source_revision_id"], "analysis_status": "ready"},
                rag_metadata,
            ):
                logger.warning("RAG metadata could not be saved")
            logger.info("Document processed for RAG with %s chunks", rag_data.get("chunk_count", 0))
        else:
            logger.warning("RAG processing returned no data")

    except Exception as rag_error:
        # RAG processing failure should not break document analysis
        logger.warning("RAG processing failed: %s", type(rag_error).__name__)
    return True, None
