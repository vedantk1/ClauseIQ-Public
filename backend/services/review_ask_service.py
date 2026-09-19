"""Durable finding-scoped Ask attempts. Only a confirmed explicit claim pays.

Reads, draft writes, retries of an existing ID and interruption never dispatch
provider work. Results are fenced by the immutable source and review snapshot.
"""
import logging
from datetime import datetime, timezone

from bson import BSON

from clauseiq_types.review import ReviewAskTurn, ReviewFailure, ReviewRun, StartAskRequest
from services.ai.client_manager import workspace_openai_client
from services.ai.generation import AIRequestError
from services.ai.review_ask import generate_ask, prepare_ask
from services.ai.token_utils import _positive_env_integer
from services.review_generation_service import ReviewGenerationService
from services.review_workspace_service import ReviewWorkspaceError, ReviewWorkspaceService


logger = logging.getLogger(__name__)
MAX_ASK_TURNS = 100
MAX_ASK_HISTORY = 6
DEFAULT_ASK_STORAGE_BYTES = 2 * 1024 * 1024
MAX_ASK_STORAGE_BYTES = 8 * 1024 * 1024
MAX_ASK_RESULT_BYTES = 256 * 1024
ASK_METADATA_RESERVE_BYTES = 16 * 1024
MAX_DOCUMENT_STORAGE_BYTES = 12 * 1024 * 1024
FINAL_SAVE_ATTEMPTS = 4


def _now():
    return datetime.now(timezone.utc).isoformat()


class ReviewAskService(ReviewWorkspaceService):
    @staticmethod
    def _turn(state, turn_id):
        turn = next((item for item in state.ask_turns if item.id == turn_id), None)
        if turn is None:
            raise ReviewWorkspaceError("ASK_NOT_FOUND", "Ask attempt not found in this document.", 404)
        return turn

    @staticmethod
    def _same_request(turn, run_id, finding_id, request):
        if (turn.run_id != run_id or turn.finding_id != finding_id
                or turn.question != request.question or turn.generation.model_id != request.model_id
                or turn.include_history != request.include_history):
            raise ReviewWorkspaceError("REQUEST_ID_CONFLICT", "This Ask request ID already belongs to a different question or context. Keep your draft and start a new request.")

    @staticmethod
    def _history(state, run_id, finding_id, include_history):
        if not include_history:
            return [], False
        eligible = [turn for turn in state.ask_turns if turn.run_id == run_id and turn.finding_id == finding_id
                    and turn.status in ("ready", "incomplete") and turn.answer]
        # A successful fresh question establishes a new conversation boundary.
        # Failed fresh attempts cannot accidentally discard usable prior context.
        for index in range(len(eligible) - 1, -1, -1):
            if not eligible[index].include_history:
                eligible = eligible[index:]
                break
        return eligible[-MAX_ASK_HISTORY:], len(eligible) > MAX_ASK_HISTORY

    @staticmethod
    def _size_guard(document, state, reserve=0):
        limit = min(_positive_env_integer("REVIEW_ASK_MAX_STORAGE_BYTES", DEFAULT_ASK_STORAGE_BYTES), MAX_ASK_STORAGE_BYTES)
        data = state.model_dump(exclude={"fixture_available"})
        ask_bytes = len(BSON.encode({"ask_turns": data["ask_turns"]}))
        projected = {**document, "review_workspace": data}
        if ask_bytes + reserve > limit or len(BSON.encode(projected)) + reserve > MAX_DOCUMENT_STORAGE_BYTES:
            raise ReviewWorkspaceError(
                "ASK_STORAGE_LIMIT", "This document has insufficient space for another saved answer. Existing review work and drafts have not been removed.",
            )

    @staticmethod
    def _same_binding(original, document, expected_run):
        ReviewGenerationService._same_source(original, document)
        # Run objects are immutable snapshots, including the perspective/brief.
        current = next((item for item in document.get("review_workspace", {}).get("runs", [])
                        if item.get("id") == expected_run.id), None)
        if current is None:
            raise ReviewWorkspaceError("ASK_REVIEW_CHANGED", "The review changed during this Ask. Its late result was not saved.")
        if ReviewRun.model_validate(current) != expected_run:
            raise ReviewWorkspaceError("ASK_REVIEW_CHANGED", "The review changed during this Ask. Its late result was not saved.")

    async def start(self, document_id, workspace_id, run_id, finding_id, request: StartAskRequest):
        document = await self._document(document_id, workspace_id)
        current = self._state(document)
        existing = next((item for item in current.ask_turns if item.id == request.request_id), None)
        if existing is not None:
            self._same_request(existing, run_id, finding_id, request)
            return current
        self._revision(current, request.expected_revision)
        run = self._run(current, run_id)
        finding = self._finding(run, finding_id)
        if run.status not in ("ready", "incomplete"):
            raise ReviewWorkspaceError("ASK_REVIEW_UNAVAILABLE", "Open an available finding from a completed review before asking.")
        if not request.question.strip():
            raise ReviewWorkspaceError("INVALID_QUESTION", "Enter a question before asking.", 422)
        if len(current.ask_turns) >= MAX_ASK_TURNS:
            raise ReviewWorkspaceError("ASK_TURN_LIMIT", "This document has reached the saved Ask limit. Existing answers and drafts have not been changed.")
        if any(turn.status == "processing" for turn in current.ask_turns):
            raise ReviewWorkspaceError("ASK_ALREADY_PROCESSING", "An Ask is already processing for this document. Reload or explicitly mark its outcome unknown before starting another.")
        self._size_guard(document, current, MAX_ASK_RESULT_BYTES + ASK_METADATA_RESERVE_BYTES)
        selected_model = await self.documents.get_workspace_model(workspace_id)
        if selected_model != request.model_id:
            raise ReviewWorkspaceError("REVIEW_MODEL_CHANGED", "The selected model changed in Settings. Reload and confirm it before asking.")
        history, history_truncated = self._history(current, run.id, finding.id, request.include_history)
        try:
            prepared = prepare_ask(document, run, finding, request.question, selected_model, history)
        except AIRequestError as error:
            raise ReviewWorkspaceError("ASK_INPUT_REJECTED", error.public_message, error.status_code) from None
        api_key = await self.documents.get_workspace_api_key(workspace_id)
        if not api_key:
            raise ReviewWorkspaceError("API_KEY_REQUIRED", "Add your OpenAI API key in Settings before asking.", 400)
        turn = ReviewAskTurn(
            id=request.request_id, run_id=run.id, finding_id=finding.id, source_revision_id=current.source_revision_id,
            question=request.question, created_at=_now(), status="processing", generation=prepared.generation,
            coverage=prepared.coverage, history_turn_ids=[item.id for item in history],
            include_history=request.include_history, history_truncated=history_truncated,
        )
        updated = current.model_copy(deep=True)
        updated.ask_turns.append(turn)
        self._size_guard(document, updated, MAX_ASK_RESULT_BYTES + ASK_METADATA_RESERVE_BYTES)
        try:
            await self._save(document, workspace_id, current, updated, ReviewGenerationService._source_fence(document))
        except ReviewWorkspaceError as error:
            if error.code == "REVISION_CONFLICT":
                latest = await self.read(document_id, workspace_id)
                raced = next((item for item in latest.ask_turns if item.id == turn.id), None)
                if raced is not None:
                    self._same_request(raced, run.id, finding.id, request)
                    return latest
            raise

        latest_document = await self._document(document_id, workspace_id)
        self._same_binding(document, latest_document, run)
        latest = self._state(latest_document)
        if self._turn(latest, turn.id).status != "processing":
            return latest
        result = None
        try:
            async with workspace_openai_client(api_key) as client:
                result = await generate_ask(prepared, client)
        except Exception as error:
            logger.warning("Ask request failed: %s", type(error).__name__)
            if result is None:
                turn.status = "failed"
                turn.failure = ReviewFailure(code="ASK_GENERATION_FAILED", message=(
                    "The answer could not be completed. The provider may have received the request; no automatic retry was made."
                ))
        if result is not None:
            turn.status, turn.answer, turn.limitations = result.status, result.answer, result.limitations
            turn.generation, turn.coverage, turn.failure = result.generation, result.coverage, result.failure
        turn.completed_at = _now()
        turn = ReviewAskTurn.model_validate(turn.model_dump())
        return await self._finalize(document, workspace_id, run, turn)

    async def _finalize(self, original, workspace_id, run, turn):
        for _ in range(FINAL_SAVE_ATTEMPTS):
            document = await self._document(original["id"], workspace_id)
            self._same_binding(original, document, run)
            current = self._state(document)
            existing = self._turn(current, turn.id)
            if existing.status != "processing":
                return current
            mutable = {"status", "completed_at", "answer", "limitations", "failure", "generation", "coverage"}
            if (existing.model_dump(exclude=mutable) != turn.model_dump(exclude=mutable)
                    or existing.generation.model_dump(exclude={"usage", "duration_ms"})
                    != turn.generation.model_dump(exclude={"usage", "duration_ms"})):
                raise ReviewWorkspaceError("ASK_CONTEXT_CHANGED", "The Ask context changed. Its late result was not saved.")
            updated = current.model_copy(deep=True)
            updated.ask_turns = [turn if item.id == turn.id else item for item in updated.ask_turns]
            try:
                if len(BSON.encode({"answer": [item.model_dump() for item in turn.answer], "limitations": turn.limitations})) > MAX_ASK_RESULT_BYTES:
                    raise ReviewWorkspaceError("ASK_STORAGE_LIMIT", "The answer exceeds the saved result limit.")
                self._size_guard(document, updated)
            except ReviewWorkspaceError as error:
                if error.code != "ASK_STORAGE_LIMIT":
                    raise
                # Never publish a partially truncated answer. Retain usage even
                # if a concurrent edit consumed the preflight headroom.
                compact = turn.model_copy(deep=True)
                compact.status, compact.answer, compact.limitations = "incomplete", [], []
                compact.failure = ReviewFailure(code="ASK_RESULT_TOO_LARGE", message=(
                    "The answer could not fit within saved review limits. No partial answer was saved; recorded usage is retained."
                ))
                updated.ask_turns = [compact if item.id == turn.id else item for item in updated.ask_turns]
                try:
                    self._size_guard(document, updated)
                except ReviewWorkspaceError:
                    # This is after dispatch: do not reuse the preflight code,
                    # which tells clients that no provider request was sent.
                    raise ReviewWorkspaceError(
                        "REVIEW_SAVE_UNCONFIRMED",
                        "The answer could not be saved within current storage limits. Provider charges may apply. Reload its saved status; no automatic retry was made.",
                        503,
                    ) from None
            try:
                return await self._save(document, workspace_id, current, updated, ReviewGenerationService._source_fence(original))
            except ReviewWorkspaceError as error:
                if error.code != "REVISION_CONFLICT":
                    raise
        raise ReviewWorkspaceError("REVIEW_SAVE_UNCONFIRMED", "The answer could not be saved while review work changed. Reload its status; a new Ask may incur another charge.", 503)

    async def interrupt(self, document_id, workspace_id, turn_id, expected_revision):
        document = await self._document(document_id, workspace_id)
        current = self._state(document)
        turn = self._turn(current, turn_id)
        if turn.status == "interrupted":
            return current
        self._revision(current, expected_revision)
        if turn.status != "processing":
            raise ReviewWorkspaceError("ASK_NOT_PROCESSING", "This Ask has already finished and cannot be changed.")
        updated = current.model_copy(deep=True)
        interrupted = self._turn(updated, turn_id)
        interrupted.status, interrupted.completed_at = "interrupted", _now()
        interrupted.failure = ReviewFailure(code="ASK_INTERRUPTED", message=(
            "Marked interrupted locally. This does not cancel provider work or prove that no charge occurred. A new Ask sends a separate paid request."
        ))
        return await self._save(document, workspace_id, current, updated)
