"""Local review persistence. No credentials, generation, indexing or external calls."""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from pydantic import Field, ValidationError

from clauseiq_types.review import (
    ReviewBrief, ReviewEvidence, ReviewFinding, ReviewModel, ReviewPersonalState,
    ReviewRun, ReviewWorkspaceResponse, ReviewWorkspaceUpdate, SavedReviewQuestion,
)
from clauseiq_types.source import SourceExtraction
from database.service import get_document_service


logger = logging.getLogger(__name__)
FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "reviews" / "managed-services-25p.json"


class ReviewWorkspaceError(RuntimeError):
    def __init__(self, code, message, status_code=409, current_revision=None):
        super().__init__(message)
        self.code, self.public_message, self.status_code = code, message, status_code
        self.current_revision = current_revision


class FixtureEvidence(ReviewModel):
    page_number: int = Field(ge=1)
    label: str = Field(min_length=1, max_length=200)
    match: str = Field(min_length=1, max_length=20000)


class FixtureFinding(ReviewModel):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=300)
    facts: str = Field(max_length=10000)
    interpretation: str = Field(max_length=10000)
    uncertainty: str = Field(max_length=10000)
    next_step: str = Field(max_length=5000)
    suggested_question: str = Field(max_length=5000)
    evidence: list[FixtureEvidence] = Field(min_length=1, max_length=30)


class FixtureReview(ReviewModel):
    version: str = Field(min_length=1, max_length=100)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    context: ReviewBrief
    overview: str = Field(max_length=20000)
    findings: list[FixtureFinding] = Field(min_length=1, max_length=100)


class ReviewWorkspaceService:
    def __init__(self, document_service=None, fixture_path=None):
        self.documents = document_service or get_document_service()
        self.fixture_path = Path(fixture_path) if fixture_path is not None else FIXTURE_PATH

    def _fixture(self):
        try:
            fixture = FixtureReview.model_validate(json.loads(self.fixture_path.read_text()))
            if fixture.context.perspective != "customer" or len({f.id for f in fixture.findings}) != len(fixture.findings):
                raise ValueError("Invalid reviewed fixture")
            return fixture
        except Exception as error:
            logger.warning("Review fixture is unavailable: %s", type(error).__name__)
            return None

    async def _document(self, document_id, workspace_id):
        document = await self.documents.get_document_for_workspace(document_id, workspace_id)
        if not document:
            raise ReviewWorkspaceError("DOCUMENT_NOT_FOUND", "Document not found.", 404)
        if not document.get("source_revision_id"):
            raise ReviewWorkspaceError("SOURCE_REVISION_REQUIRED", "This legacy analysis has no verified source revision. Import its PDF to start a separate review workspace.")
        if document.get("source_status") != "stored" or document.get("has_pdf_file") is not True:
            raise ReviewWorkspaceError("SOURCE_NOT_AVAILABLE", "The original PDF has not been confirmed as stored.")
        return document

    def _state(self, document):
        try:
            stored = document.get("review_workspace")
            state = ReviewWorkspaceResponse.model_validate(stored) if stored is not None else ReviewWorkspaceResponse(
                document_id=document["id"], source_revision_id=document["source_revision_id"], revision=0,
            )
            if state.document_id != document["id"] or state.source_revision_id != document["source_revision_id"]:
                raise ValueError("Workspace source mismatch")
            run_ids = {run.id for run in state.runs}
            if len(run_ids) != len(state.runs) or not set(state.personal).issubset(run_ids):
                raise ValueError("Workspace run mismatch")
            for run in state.runs:
                if run.source_revision_id != state.source_revision_id:
                    raise ValueError("Run source mismatch")
                finding_ids = {finding.id for finding in run.findings}
                if len(finding_ids) != len(run.findings):
                    raise ValueError("Duplicate finding")
                if any(evidence.source_revision_id != state.source_revision_id for finding in run.findings for evidence in finding.evidence):
                    raise ValueError("Evidence source mismatch")
                personal = state.personal.get(run.id)
                if personal:
                    if not (set(personal.drafts) | set(personal.saved_questions) | set(personal.markers) | set(personal.opened_finding_ids)).issubset(finding_ids):
                        raise ValueError("Personal state finding mismatch")
                    self._position(run, personal.position)
            fixture = self._fixture()
            state.fixture_available = bool(
                fixture and document.get("source_sha256") == fixture.source_sha256
                and document.get("extraction_status") == "complete"
            )
            return state
        except (ValueError, ValidationError, ReviewWorkspaceError):
            raise ReviewWorkspaceError("REVIEW_STATE_INVALID", "Saved review state does not match this source. It has not been changed.") from None

    async def read(self, document_id, workspace_id):
        return self._state(await self._document(document_id, workspace_id))

    @staticmethod
    def _revision(state, expected_revision):
        if state.revision != expected_revision:
            raise ReviewWorkspaceError("REVISION_CONFLICT", "Review work changed. Reload it before choosing whether to apply your edit.", current_revision=state.revision)

    @staticmethod
    def _run(state, run_id):
        run = next((run for run in state.runs if run.id == run_id), None)
        if run is None:
            raise ReviewWorkspaceError("RUN_NOT_FOUND", "Review run not found in this document.", 404)
        return run

    @staticmethod
    def _finding(run, finding_id):
        finding = next((finding for finding in run.findings if finding.id == finding_id), None)
        if finding is None:
            raise ReviewWorkspaceError("FINDING_NOT_FOUND", "Finding not found in this review run.", 404)
        return finding

    def _position(self, run, position):
        finding = self._finding(run, position.finding_id) if position.finding_id is not None else None
        if position.view == "findings" and finding is None:
            raise ReviewWorkspaceError("INVALID_POSITION", "Choose a finding before opening its review view.", 422)
        if position.evidence_span_id is not None and (
            finding is None or position.evidence_span_id not in {e.span_id for e in finding.evidence}
        ):
            raise ReviewWorkspaceError("EVIDENCE_NOT_FOUND", "This evidence does not belong to the selected finding.", 422)

    async def _save(self, document, workspace_id, previous, updated):
        # Derived availability is never authoritative stored state.
        old_data = previous.model_dump(exclude={"fixture_available"})
        new_data = updated.model_dump(exclude={"fixture_available"})
        if old_data == new_data:
            return previous
        updated.revision = previous.revision + 1
        expected = {"source_revision_id": previous.source_revision_id, "source_status": "stored", "has_pdf_file": True}
        if document.get("review_workspace") is None:
            expected["review_workspace"] = None
        else:
            expected["review_workspace.revision"] = previous.revision
        try:
            saved = await self.documents.update_document_if(
                document["id"], workspace_id, expected,
                {"review_workspace": updated.model_dump(exclude={"fixture_available"})},
            )
        except Exception as error:
            logger.warning("Review workspace write was not confirmed: %s", type(error).__name__)
            raise ReviewWorkspaceError("REVIEW_SAVE_UNCONFIRMED", "The write could not be confirmed. Keep your draft and reload before retrying.", 503) from None
        if not saved:
            current = await self.read(document["id"], workspace_id)
            raise ReviewWorkspaceError("REVISION_CONFLICT", "Review work changed. Reload it before choosing whether to apply your edit.", current_revision=current.revision)
        return updated

    async def update(self, document_id, workspace_id, request: ReviewWorkspaceUpdate):
        document = await self._document(document_id, workspace_id)
        current = self._state(document)
        self._revision(current, request.expected_revision)
        updated = current.model_copy(deep=True)
        operation = request.operation
        if operation.type == "set_brief":
            updated.brief = operation.brief.model_copy(deep=True)
        else:
            run = self._run(updated, operation.run_id)
            personal = updated.personal.setdefault(run.id, ReviewPersonalState())
            if operation.type == "set_position":
                self._position(run, operation.position)
                personal.position = operation.position.model_copy(deep=True)
                if operation.position.view == "findings" and operation.position.finding_id not in personal.opened_finding_ids:
                    personal.opened_finding_ids.append(operation.position.finding_id)
            else:
                finding = self._finding(run, operation.finding_id)
                if operation.type == "set_draft":
                    personal.drafts[finding.id] = operation.text
                elif operation.type == "save_question":
                    if not operation.text.strip():
                        raise ReviewWorkspaceError("INVALID_QUESTION", "Enter a question before saving it.", 422)
                    old_question = personal.saved_questions.get(finding.id)
                    if old_question is None or old_question.text != operation.text:
                        personal.saved_questions[finding.id] = SavedReviewQuestion(
                            id=old_question.id if old_question else str(uuid5(NAMESPACE_URL, f"clauseiq-question:{run.id}:{finding.id}")),
                            text=operation.text, saved_at=datetime.now(timezone.utc).isoformat(),
                        )
                elif operation.type == "set_marker":
                    if personal.markers.get(finding.id, "not_marked") != operation.marker:
                        personal.markers[finding.id] = operation.marker
        return await self._save(document, workspace_id, current, updated)

    def _fixture_run(self, document, fixture):
        try:
            extraction = SourceExtraction.model_validate(document["source_extraction"])
            if extraction.status != "complete" or extraction.content_sha256 != fixture.source_sha256:
                raise ValueError("Source does not match reviewed fixture")
            findings = []
            for finding in fixture.findings:
                evidence = []
                for item in finding.evidence:
                    matches = [span for page in extraction.pages if page.page_number == item.page_number
                               for span in page.spans if item.match in span.text]
                    if len(matches) != 1:
                        raise ValueError("Fixture evidence is missing or ambiguous")
                    span = matches[0]
                    evidence.append(ReviewEvidence(
                        source_revision_id=document["source_revision_id"], span_id=span.id,
                        page_number=item.page_number, quote=span.text, label=item.label,
                    ))
                findings.append(ReviewFinding(**finding.model_dump(exclude={"evidence"}), evidence=evidence))
            return ReviewRun(
                id=str(uuid5(NAMESPACE_URL, f"clauseiq-fixture:{document['id']}:{document['source_revision_id']}")),
                kind="fixture", source_revision_id=document["source_revision_id"],
                created_at=datetime.now(timezone.utc).isoformat(), context=fixture.context,
                fixture_version=fixture.version, overview=fixture.overview, findings=findings,
            )
        except (KeyError, ValueError, ValidationError):
            raise ReviewWorkspaceError("FIXTURE_EVIDENCE_INVALID", "The example could not be matched exactly to this extraction. No findings were saved.") from None

    async def create_fixture(self, document_id, workspace_id, expected_revision):
        document = await self._document(document_id, workspace_id)
        current = self._state(document)
        # Retrying an uncertain POST returns the single immutable existing run.
        if any(run.kind == "fixture" for run in current.runs):
            return current
        self._revision(current, expected_revision)
        fixture = self._fixture()
        if fixture is None:
            raise ReviewWorkspaceError("FIXTURE_UNAVAILABLE", "The reviewed example is unavailable.", 503)
        if not current.fixture_available:
            raise ReviewWorkspaceError("FIXTURE_NOT_SUPPORTED", "This example is available only for the unchanged reviewed 25-page synthetic PDF with complete extraction.")
        run = self._fixture_run(document, fixture)
        updated = current.model_copy(deep=True)
        updated.runs.append(run)
        updated.personal[run.id] = ReviewPersonalState()
        return await self._save(document, workspace_id, current, updated)
