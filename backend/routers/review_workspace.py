"""Local review state and explicit, persisted AI-generation attempts."""
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from clauseiq_types.review import (
    FixtureReviewRequest, InterruptReviewRequest, ReviewWorkspaceResponse,
    ReviewWorkspaceUpdate, StartReviewRequest,
)
from database.service import get_document_service
from middleware.api_standardization import APIResponse, create_error_response
from services.review_workspace_service import ReviewWorkspaceError, ReviewWorkspaceService
from services.review_generation_service import ReviewGenerationService
from workspace import get_workspace_id


logger = logging.getLogger(__name__)
router = APIRouter(tags=["review-workspace"])


async def _response(operation, document_id):
    try:
        return APIResponse(success=True, data=await operation)
    except ReviewWorkspaceError as error:
        details = {"document_id": document_id}
        if error.current_revision is not None:
            details["current_revision"] = error.current_revision
        return JSONResponse(status_code=error.status_code, content=create_error_response(
            error.code, error.public_message, details=details,
        ).model_dump())
    except Exception as error:
        logger.error("Review workspace request failed: %s", type(error).__name__)
        return JSONResponse(status_code=503, content=create_error_response(
            "REVIEW_WORKSPACE_UNAVAILABLE", "Review work could not be loaded or saved. Keep your draft and reload before retrying.",
            details={"document_id": document_id},
        ).model_dump())


@router.get("/documents/{document_id}/review-workspace", response_model=APIResponse[ReviewWorkspaceResponse])
async def get_review_workspace(document_id: str, workspace_id: str = Depends(get_workspace_id)):
    return await _response(ReviewWorkspaceService(get_document_service()).read(document_id, workspace_id), document_id)


@router.put("/documents/{document_id}/review-workspace", response_model=APIResponse[ReviewWorkspaceResponse])
async def update_review_workspace(document_id: str, body: ReviewWorkspaceUpdate, workspace_id: str = Depends(get_workspace_id)):
    return await _response(ReviewWorkspaceService(get_document_service()).update(document_id, workspace_id, body), document_id)


@router.post("/documents/{document_id}/review-workspace/fixture", response_model=APIResponse[ReviewWorkspaceResponse])
async def create_fixture_review(document_id: str, body: FixtureReviewRequest, workspace_id: str = Depends(get_workspace_id)):
    return await _response(ReviewWorkspaceService(get_document_service()).create_fixture(document_id, workspace_id, body.expected_revision), document_id)


@router.post("/documents/{document_id}/review-workspace/generate", response_model=APIResponse[ReviewWorkspaceResponse])
async def generate_review(document_id: str, body: StartReviewRequest, workspace_id: str = Depends(get_workspace_id)):
    return await _response(ReviewGenerationService(get_document_service()).start(document_id, workspace_id, body), document_id)


@router.post("/documents/{document_id}/review-workspace/runs/{run_id}/interrupt", response_model=APIResponse[ReviewWorkspaceResponse])
async def interrupt_review(document_id: str, run_id: str, body: InterruptReviewRequest, workspace_id: str = Depends(get_workspace_id)):
    return await _response(ReviewGenerationService(get_document_service()).interrupt(
        document_id, workspace_id, run_id, body.expected_revision,
    ), document_id)
