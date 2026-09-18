"""Durable, explicit review attempts; no automatic replay of a paid request."""
import logging
from datetime import datetime, timezone

from clauseiq_types.review import ReviewFailure, ReviewPersonalState, ReviewRun, StartReviewRequest
from services.ai.client_manager import workspace_openai_client
from services.ai.generation import AIRequestError
from services.ai.review_generation import generate_review, prepare_review
from services.review_workspace_service import ReviewWorkspaceError, ReviewWorkspaceService


logger = logging.getLogger(__name__)
FINAL_SAVE_ATTEMPTS = 4
MAX_REVIEW_RUNS = 100


def _now():
    return datetime.now(timezone.utc).isoformat()


class ReviewGenerationService(ReviewWorkspaceService):
    """Persist before calling the provider and fence every later result by source/run.

    A persisted processing attempt may have an unknown provider outcome after a
    lost response or process exit. Reading or replaying its ID never resends it.
    """

    async def start(self, document_id, workspace_id, request: StartReviewRequest):
        document = await self._document(document_id, workspace_id)
        current = self._state(document)
        existing = next((run for run in current.runs if run.id == request.request_id), None)
        if existing:
            # An existing fixture ID is not a generation idempotency token.
            if existing.kind != "ai":
                raise ReviewWorkspaceError("REQUEST_ID_CONFLICT", "Choose a new review request before starting.")
            return current
        self._revision(current, request.expected_revision)
        if len(current.runs) >= MAX_REVIEW_RUNS:
            raise ReviewWorkspaceError("REVIEW_RUN_LIMIT", "This document has reached the saved review-run limit. Existing reviews have not been changed.")
        if any(run.status == "processing" for run in current.runs):
            raise ReviewWorkspaceError("REVIEW_ALREADY_PROCESSING", "A review is already processing. Reload its status or explicitly mark its outcome unknown before starting another.")

        selected_model = await self.documents.get_workspace_model(workspace_id)
        if selected_model != request.model_id:
            raise ReviewWorkspaceError("REVIEW_MODEL_CHANGED", "The selected model changed in Settings. Reload and confirm the model before starting review.")
        try:
            prepared = prepare_review(document, current.brief, selected_model)
        except AIRequestError as error:
            raise ReviewWorkspaceError("REVIEW_INPUT_REJECTED", error.public_message, error.status_code) from None
        api_key = await self.documents.get_workspace_api_key(workspace_id)
        if not api_key:
            raise ReviewWorkspaceError("API_KEY_REQUIRED", "Add your OpenAI API key in Settings before starting review.", 400)

        run = ReviewRun(
            id=request.request_id, kind="ai", status="processing", created_at=_now(),
            source_revision_id=current.source_revision_id, context=current.brief.model_copy(deep=True),
            generation=prepared.generation, coverage=prepared.coverage,
        )
        updated = current.model_copy(deep=True)
        updated.runs.append(run)
        updated.personal[run.id] = ReviewPersonalState()
        try:
            await self._save(document, workspace_id, current, updated, self._source_fence(document))
        except ReviewWorkspaceError as error:
            if error.code == "REVISION_CONFLICT":
                # Two identical explicit submissions can race before the claim.
                # Only the confirmed claimant can reach the provider.
                latest = await self.read(document_id, workspace_id)
                if any(item.id == run.id and item.kind == "ai" for item in latest.runs):
                    return latest
            raise

        # Check again after the claim; interruption/deletion before dispatch must
        # not knowingly start paid work. This is not a provider cancellation API.
        latest_document = await self._document(document_id, workspace_id)
        self._same_source(document, latest_document)
        latest = self._state(latest_document)
        if self._run(latest, run.id).status != "processing":
            return latest
        result = None
        try:
            async with workspace_openai_client(api_key) as client:
                result = await generate_review(prepared, client)
        except Exception as error:
            # Provider exceptions and credential setup/close failures must not
            # leak request content or trigger another generation attempt.
            logger.warning("Review generation request failed: %s", type(error).__name__)
            if result is None:
                run.status = "failed"
                run.failure = ReviewFailure(
                    code="REVIEW_GENERATION_FAILED",
                    message="The review could not be completed. The provider may have received the request; no automatic retry was made.",
                )
        if result is not None:
            run.status = result.status
            run.overview_items = result.overview_items
            run.findings = result.findings
            run.coverage = result.coverage
            run.generation = result.generation
            run.failure = result.failure
        run.completed_at = _now()
        run = ReviewRun.model_validate(run.model_dump())
        return await self._finalize(document, workspace_id, run)

    @staticmethod
    def _source_fence(document):
        return {"source_sha256": document.get("source_sha256"), "source_extraction": document.get("source_extraction")}

    @staticmethod
    def _same_source(original, current):
        if (current.get("source_revision_id") != original.get("source_revision_id")
                or current.get("source_sha256") != original.get("source_sha256")
                or current.get("source_extraction") != original.get("source_extraction")):
            raise ReviewWorkspaceError("REVIEW_SOURCE_CHANGED", "The source changed during this review. Its late result was not saved.")

    async def _finalize(self, original, workspace_id, run):
        for _ in range(FINAL_SAVE_ATTEMPTS):
            document = await self._document(original["id"], workspace_id)
            self._same_source(original, document)
            current = self._state(document)
            existing = self._run(current, run.id)
            if existing.status != "processing":
                # An explicit interruption (or already saved terminal result)
                # takes precedence over a late provider response.
                return current
            updated = current.model_copy(deep=True)
            updated.runs = [run if item.id == run.id else item for item in updated.runs]
            try:
                return await self._save(document, workspace_id, current, updated, self._source_fence(original))
            except ReviewWorkspaceError as error:
                if error.code != "REVISION_CONFLICT":
                    raise
                # Only persistence is retried, never the provider. Re-read state
                # so an intervening brief/draft/marker update is preserved.
        raise ReviewWorkspaceError(
            "REVIEW_SAVE_UNCONFIRMED",
            "The generated result could not be saved while review work changed. Reload its status; do not assume a new review is free of another charge.", 503,
        )

    async def interrupt(self, document_id, workspace_id, run_id, expected_revision):
        document = await self._document(document_id, workspace_id)
        current = self._state(document)
        run = self._run(current, run_id)
        if run.kind != "ai":
            raise ReviewWorkspaceError("REVIEW_NOT_INTERRUPTIBLE", "Only a processing AI review can be marked interrupted.")
        if run.status == "interrupted":
            return current
        self._revision(current, expected_revision)
        if run.status != "processing":
            raise ReviewWorkspaceError("REVIEW_NOT_PROCESSING", "This review has already finished and cannot be changed.")
        updated = current.model_copy(deep=True)
        interrupted = self._run(updated, run_id)
        interrupted.status = "interrupted"
        interrupted.completed_at = _now()
        interrupted.failure = ReviewFailure(
            code="REVIEW_INTERRUPTED",
            message="Marked interrupted locally. This does not cancel provider work or prove that no charge occurred. A new review sends a separate paid request.",
        )
        return await self._save(document, workspace_id, current, updated)
