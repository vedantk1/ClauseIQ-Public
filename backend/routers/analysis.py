"""
Document analysis routes.
"""
import uuid
import logging
from fastapi import APIRouter, File, UploadFile, HTTPException, Depends, Request
from pydantic import BaseModel
from workspace import get_workspace_id
from database.service import get_document_service
from middleware.api_standardization import APIResponse, create_success_response, create_error_response
from middleware.versioning import versioned_response
from services.document_service import (
    validate_file,
    process_document_with_llm,
    calculate_risk_summary,
    process_and_save_analyzed_document
)
from services.ai.text_extractor import get_text_extractor
# PHASE 3 MIGRATION: Main AI functions still from ai_service for stability
from services.ai_service import generate_structured_document_summary, generate_clause_rewrite
from services.ai.generation import AIRequestError, generation_metadata
from models.document import AnalyzeDocumentResponse
from models.interaction import UserInteractionRequest, NoteRequest
from routers.serialization import without_legacy_owner_fields
from clauseiq_types.common import RiskLevel, Clause, RiskSummary, ContractType


logger = logging.getLogger(__name__)
router = APIRouter(tags=["analysis"])


async def _require_document(service, document_id: str, workspace_id: str):
    document = await service.get_document_for_workspace(document_id, workspace_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


async def _require_clause(service, document_id: str, clause_id: str, workspace_id: str):
    document = await _require_document(service, document_id, workspace_id)
    if not any(clause.get("id") == clause_id for clause in (document.get("clauses") or [])):
        raise HTTPException(status_code=404, detail="Clause not found in document")
    return document


@router.post("/analyze/", response_model=APIResponse[dict])
@versioned_response
async def analyze_document(
    request: Request,
    file: UploadFile = File(...),
    workspace_id: str = Depends(get_workspace_id)
):
    """Analyze document and extract clauses with AI summaries."""
    correlation_id = getattr(request.state, 'correlation_id', None)

    try:
        validate_file(file)
        service = get_document_service()

        # Check if workspace has an API key set
        workspace_api_key = await service.get_workspace_api_key(workspace_id)
        if not workspace_api_key:
            return create_error_response(
                code="API_KEY_REQUIRED",
                message="Please add your OpenAI API key in Settings before analyzing documents.",
                correlation_id=correlation_id
            )

        # Read file content
        content = await file.read()

        # Use TextExtractor service for extraction
        text_extractor = get_text_extractor()
        try:
            extracted_text = await text_extractor.extract_text(content, file.filename)
        except ValueError:
            return create_error_response(
                code="PDF_EXTRACTION_FAILED",
                message="Failed to extract text from PDF",
                correlation_id=correlation_id
            )
        except Exception as extraction_error:
            logger.error("PDF text extraction failed: %s", type(extraction_error).__name__)
            return create_error_response(
                code="PDF_EXTRACTION_FAILED",
                message="Failed to extract text from PDF",
                correlation_id=correlation_id
            )

        # Get workspace model
        workspace_model = await service.get_workspace_model(workspace_id)
        analysis_generation = {
            operation: generation_metadata(workspace_model, operation)
            for operation in ("classification", "extraction", "summary")
        }

        # Use the workspace API key for all AI operations in this request
        from services.ai.client_manager import workspace_openai_client

        async with workspace_openai_client(workspace_api_key):
            contract_type, clauses = await process_document_with_llm(
                extracted_text, file.filename, workspace_model
            )

            # Generate contract-type-specific structured summary for improved UI display
            ai_structured_summary = await generate_structured_document_summary(
                extracted_text, file.filename, workspace_model, contract_type
            )

            # Generate document ID
            doc_id = str(uuid.uuid4())

            # Process RAG and save document (consolidated business logic)
            # RAG uses embeddings which also require OpenAI
            success, error = await process_and_save_analyzed_document(
                doc_id=doc_id,
                filename=file.filename,
                extracted_text=extracted_text,
                clauses=clauses,
                contract_type=contract_type,
                workspace_id=workspace_id,
                ai_structured_summary=ai_structured_summary,
                file_content=content,
                content_type=file.content_type or "application/pdf",
                analysis_generation=analysis_generation,
            )

        if not success:
            return create_error_response(
                code="DOCUMENT_SAVE_FAILED",
                message=error or "Failed to save document",
                correlation_id=correlation_id
            )

        # Calculate risk summary for response
        risk_summary = calculate_risk_summary(clauses)

        # Return response with ALL required fields for frontend
        response_data = {
            "id": doc_id,
            "workspace_id": workspace_id,
            "filename": file.filename,
            "summary": ai_structured_summary.get("overview", "Document processed successfully") if ai_structured_summary else "Document processed successfully",
            "ai_structured_summary": ai_structured_summary,
            "analysis_generation": analysis_generation,
            "clauses": clauses,
            "total_clauses": len(clauses),
            "risk_summary": risk_summary,
            "full_text": extracted_text,
            "contract_type": contract_type.value if contract_type else None,
            "message": "Document analyzed successfully"
        }

        return create_success_response(
            data=response_data,
            correlation_id=correlation_id
        )

    except AIRequestError as error:
        raise HTTPException(status_code=error.status_code, detail=error.public_message) from None
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Document analysis failed: %s", type(e).__name__)
        return create_error_response(
            code="DOCUMENT_ANALYSIS_FAILED",
            message="An error occurred while analyzing the document",
            correlation_id=correlation_id
        )


@router.get("/documents/{document_id}/clauses", response_model=APIResponse[dict])
@versioned_response
async def get_document_clauses(
    document_id: str,
    request: Request,
    workspace_id: str = Depends(get_workspace_id)
):
    """Get clauses for a specific document."""
    correlation_id = getattr(request.state, 'correlation_id', None)

    try:
        service = get_document_service()

        # Get the document
        document = await service.get_document_for_workspace(document_id, workspace_id)
        if not document:
            return create_error_response(
                code="DOCUMENT_NOT_FOUND",
                message="Document not found",
                correlation_id=correlation_id
            )

        # Viewing saved analysis never starts a new provider request.
        analyzed_clauses = document.get("clauses") or []
        risk_summary = document.get("risk_summary") or {
            level: sum(clause.get("risk_level") == level for clause in analyzed_clauses)
            for level in ("high", "medium", "low")
        }

        response_data = {
            "clauses": analyzed_clauses,
            "total_clauses": len(analyzed_clauses),
            "risk_summary": risk_summary,
            "document_id": document_id
        }

        return create_success_response(
            data=response_data,
            correlation_id=correlation_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Document clause retrieval failed: %s", type(e).__name__)
        return create_error_response(
            code="CLAUSE_RETRIEVAL_FAILED",
            message="An error occurred while retrieving clauses",
            correlation_id=correlation_id
        )


# User Interaction Endpoints for Notes and Flags
@router.get("/documents/{document_id}/interactions", response_model=APIResponse[dict])
@versioned_response
async def get_document_interactions(
    document_id: str,
    request: Request,
    workspace_id: str = Depends(get_workspace_id)
):
    """Get all user interactions (notes and flags) for a document."""
    correlation_id = getattr(request.state, 'correlation_id', None)

    try:
        service = get_document_service()
        await _require_document(service, document_id, workspace_id)
        interactions = await service.get_user_interactions(document_id, workspace_id)

        return create_success_response(
            data={"interactions": without_legacy_owner_fields(interactions or {})},
            correlation_id=correlation_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("User interaction retrieval failed: %s", type(e).__name__)
        return create_error_response(
            code="INTERACTION_RETRIEVAL_FAILED",
            message="Failed to retrieve user interactions",
            correlation_id=correlation_id
        )


@router.put("/documents/{document_id}/interactions/{clause_id}", response_model=APIResponse[dict])
@versioned_response
async def save_clause_interaction(
    document_id: str,
    clause_id: str,
    request: Request,
    interaction_data: UserInteractionRequest,
    workspace_id: str = Depends(get_workspace_id)
):
    """Save or update user interaction (note and/or flag) for a specific clause."""
    correlation_id = getattr(request.state, 'correlation_id', None)

    try:
        service = get_document_service()

        await _require_clause(service, document_id, clause_id, workspace_id)

        # Validate interaction data
        note = interaction_data.note
        is_flagged = interaction_data.is_flagged

        # Save the interaction
        saved_interaction = await service.save_user_interaction(
            document_id=document_id,
            clause_id=clause_id,
            workspace_id=workspace_id,
            note=note,
            is_flagged=is_flagged
        )

        return create_success_response(
            data={"interaction": without_legacy_owner_fields(saved_interaction)},
            meta={"message": "Interaction saved successfully"},
            correlation_id=correlation_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("User interaction save failed: %s", type(e).__name__)
        return create_error_response(
            code="INTERACTION_SAVE_FAILED",
            message="Failed to save user interaction",
            correlation_id=correlation_id
        )


@router.delete("/documents/{document_id}/interactions/{clause_id}", response_model=APIResponse[dict])
@versioned_response
async def delete_clause_interaction(
    document_id: str,
    clause_id: str,
    request: Request,
    workspace_id: str = Depends(get_workspace_id)
):
    """Delete user interaction for a specific clause."""
    correlation_id = getattr(request.state, 'correlation_id', None)

    try:
        service = get_document_service()

        await _require_clause(service, document_id, clause_id, workspace_id)

        await service.delete_user_interaction(
            document_id=document_id,
            clause_id=clause_id,
            workspace_id=workspace_id
        )

        return create_success_response(
            data={"deleted": True},
            meta={"message": "Interaction deleted successfully"},
            correlation_id=correlation_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("User interaction deletion failed: %s", type(e).__name__)
        return create_error_response(
            code="INTERACTION_DELETE_FAILED",
            message="Failed to delete user interaction",
            correlation_id=correlation_id
        )


# Individual Note Management Endpoints

@router.post("/documents/{document_id}/interactions/{clause_id}/notes", response_model=APIResponse[dict])
@versioned_response
async def add_clause_note(
    document_id: str,
    clause_id: str,
    request: Request,
    note_data: NoteRequest,
    workspace_id: str = Depends(get_workspace_id)
):
    """Add a new note to a specific clause."""
    correlation_id = getattr(request.state, 'correlation_id', None)

    try:
        service = get_document_service()

        await _require_clause(service, document_id, clause_id, workspace_id)

        # Add the note
        new_note = await service.add_note(
            document_id=document_id,
            clause_id=clause_id,
            workspace_id=workspace_id,
            text=note_data.text
        )

        return create_success_response(
            data={"note": without_legacy_owner_fields(new_note)},
            correlation_id=correlation_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Clause note creation failed: %s", type(e).__name__)
        return create_error_response(
            code="NOTE_ADD_FAILED",
            message="Failed to add note",
            correlation_id=correlation_id
        )


@router.put("/documents/{document_id}/interactions/{clause_id}/notes/{note_id}", response_model=APIResponse[dict])
@versioned_response
async def update_clause_note(
    document_id: str,
    clause_id: str,
    note_id: str,
    request: Request,
    note_data: NoteRequest,
    workspace_id: str = Depends(get_workspace_id)
):
    """Update an existing note."""
    correlation_id = getattr(request.state, 'correlation_id', None)

    try:
        service = get_document_service()

        await _require_clause(service, document_id, clause_id, workspace_id)

        # Update the note
        updated_note = await service.update_note(
            document_id=document_id,
            clause_id=clause_id,
            workspace_id=workspace_id,
            note_id=note_id,
            text=note_data.text
        )

        return create_success_response(
            data={"note": without_legacy_owner_fields(updated_note)},
            correlation_id=correlation_id
        )

    except ValueError:
        return create_error_response(
            code="NOTE_NOT_FOUND",
            message="Note not found",
            correlation_id=correlation_id
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Clause note update failed: %s", type(e).__name__)
        return create_error_response(
            code="NOTE_UPDATE_FAILED",
            message="Failed to update note",
            correlation_id=correlation_id
        )


@router.delete("/documents/{document_id}/interactions/{clause_id}/notes/{note_id}", response_model=APIResponse[dict])
@versioned_response
async def delete_clause_note(
    document_id: str,
    clause_id: str,
    note_id: str,
    request: Request,
    workspace_id: str = Depends(get_workspace_id)
):
    """Delete a specific note."""
    correlation_id = getattr(request.state, 'correlation_id', None)

    try:
        service = get_document_service()

        await _require_clause(service, document_id, clause_id, workspace_id)

        success = await service.delete_note(
            document_id=document_id,
            clause_id=clause_id,
            workspace_id=workspace_id,
            note_id=note_id
        )

        if not success:
            return create_error_response(
                code="NOTE_NOT_FOUND",
                message="Note not found",
                correlation_id=correlation_id
            )

        return create_success_response(
            data={"deleted": True},
            correlation_id=correlation_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Clause note deletion failed: %s", type(e).__name__)
        return create_error_response(
            code="NOTE_DELETE_FAILED",
            message="Failed to delete note",
            correlation_id=correlation_id
        )


class ClauseRewriteRequest(BaseModel):
    document_id: str


@router.post("/clauses/{clause_id}/rewrite", response_model=APIResponse[dict])
@versioned_response
async def generate_clause_rewrite_endpoint(
    clause_id: str,
    request: Request,
    rewrite_request: ClauseRewriteRequest,
    workspace_id: str = Depends(get_workspace_id)
):
    """Generate a rewrite suggestion for a specific clause."""
    correlation_id = getattr(request.state, 'correlation_id', None)

    try:
        service = get_document_service()

        # Fetch the document to get full text and contract type
        document = await service.get_document_for_workspace(rewrite_request.document_id, workspace_id)
        if not document:
            return create_error_response(
                code="DOCUMENT_NOT_FOUND",
                message="Document not found",
                correlation_id=correlation_id
            )

        # Find the specific clause
        clause = None
        if document.get("clauses"):
            for c in document["clauses"]:
                if c.get("id") == clause_id:
                    clause = c
                    break

        if not clause:
            return create_error_response(
                code="CLAUSE_NOT_FOUND",
                message="Clause not found in document",
                correlation_id=correlation_id
            )

        # Check if rewrite already exists
        if clause.get("rewrite_suggestion"):
            return create_success_response(
                data={
                    "rewrite_suggestion": clause["rewrite_suggestion"],
                    "rewrite_generated_at": clause["rewrite_generated_at"],
                    "rewrite_generation": clause.get("rewrite_generation"),
                    "cached": True
                },
                correlation_id=correlation_id
            )

        # Generate rewrite using AI with workspace API key
        workspace_api_key = await service.get_workspace_api_key(workspace_id)
        if not workspace_api_key:
            return create_error_response(
                code="API_KEY_REQUIRED",
                message="Please add your OpenAI API key in Settings before generating rewrites.",
                correlation_id=correlation_id
            )
        workspace_model = await service.get_workspace_model(workspace_id)
        rewrite_generation = generation_metadata(workspace_model, "rewrite")

        from clauseiq_types.common import Clause, ContractType
        from services.ai.client_manager import workspace_openai_client

        # Convert dict to Clause object
        clause_obj = Clause(**clause)
        contract_type = ContractType(document.get("contract_type", "OTHER"))

        async with workspace_openai_client(workspace_api_key):
            rewrite_suggestion = await generate_clause_rewrite(
                clause=clause_obj,
                document_text=document["text"],
                contract_type=contract_type,
                model=workspace_model
            )

        # Save rewrite to database
        updated_clause = await service.update_clause_rewrite(
            document_id=rewrite_request.document_id,
            clause_id=clause_id,
            workspace_id=workspace_id,
            rewrite_suggestion=rewrite_suggestion,
            generation=rewrite_generation,
        )

        return create_success_response(
            data={
                "rewrite_suggestion": rewrite_suggestion,
                "rewrite_generated_at": updated_clause["rewrite_generated_at"],
                "rewrite_generation": updated_clause.get("rewrite_generation", rewrite_generation),
                "cached": False
            },
            correlation_id=correlation_id
        )

    except AIRequestError as error:
        raise HTTPException(status_code=error.status_code, detail=error.public_message) from None
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Clause rewrite request failed: %s", type(e).__name__)
        return create_error_response(
            code="REWRITE_GENERATION_FAILED",
            message="Failed to generate clause rewrite",
            correlation_id=correlation_id
        )
