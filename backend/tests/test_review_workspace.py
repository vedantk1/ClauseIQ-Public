"""Deterministic personal-state, exact-evidence and lost-write regressions."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from clauseiq_types.review import ReviewEvidence, ReviewRun, ReviewWorkspaceUpdate
from middleware.api_standardization import add_api_standardization
from routers import review_workspace
from services.ai.text_extractor import TextExtractor
from services.review_workspace_service import FIXTURE_PATH, ReviewWorkspaceError, ReviewWorkspaceService


PDF_PATH = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pdfs" / "managed-services-25p.pdf"
WORKSPACE = "local"


class MemoryDocuments:
    def __init__(self, document):
        self.document = deepcopy(document)
        self.writes = []
        self.fail = False
        self.lose_confirmation = False

    async def get_document_for_workspace(self, document_id, workspace_id):
        snapshot = deepcopy(self.document)
        await asyncio.sleep(0)
        return snapshot if snapshot and (document_id, workspace_id) == (snapshot["id"], snapshot["workspace_id"]) else None

    async def update_document_if(self, document_id, workspace_id, expected, values):
        if self.fail:
            raise RuntimeError("PRIVATE STORAGE DETAIL")
        if not self.document or (document_id, workspace_id) != (self.document["id"], self.document["workspace_id"]):
            return False
        for key, value in expected.items():
            actual = self.document
            for part in key.split("."):
                actual = actual.get(part) if isinstance(actual, dict) else None
            if actual != value:
                return False
        self.document.update(deepcopy(values))
        self.writes.append(deepcopy(values))
        if self.lose_confirmation:
            raise RuntimeError("PRIVATE STORAGE DETAIL")
        return True

    async def get_workspace_api_key(self, *_):
        raise AssertionError("Review persistence must not read credentials")


@pytest.fixture(scope="module")
def source_document():
    source = asyncio.run(TextExtractor().extract_source(PDF_PATH.read_bytes(), PDF_PATH.name))
    return {"id": "doc-1", "workspace_id": WORKSPACE, "source_revision_id": "source-1",
            "source_sha256": source.content_sha256, "source_status": "stored", "has_pdf_file": True,
            "extraction_status": "complete", "source_extraction": source.model_dump(),
            "pdf_file_id": "internal-pointer", "text": source.text, "clauses": None,
            "user_interactions": {"old-clause": {"notes": ["Preserve legacy note"]}}}


@pytest.fixture
def storage(source_document):
    return MemoryDocuments(source_document)


@pytest.fixture
def service(storage):
    return ReviewWorkspaceService(storage)


def update_request(revision, operation):
    return ReviewWorkspaceUpdate(expected_revision=revision, operation=operation)


async def change(service, revision, kind, **values):
    return await service.update("doc-1", WORKSPACE, update_request(revision, {"type": kind, **values}))


@pytest.mark.asyncio
async def test_read_is_lazy_key_free_and_omits_internal_document_fields(service, storage):
    state = await service.read("doc-1", WORKSPACE)
    assert state.revision == 0 and state.runs == [] and state.personal == {}
    assert state.brief.model_dump() == {"perspective": "neutral", "role": "", "priorities": ""}
    assert state.fixture_available is True
    assert storage.writes == []
    assert "review_workspace" not in storage.document
    assert not {"pdf_file_id", "text", "source_extraction", "user_interactions", "workspace_id"}.intersection(state.model_dump())


@pytest.mark.asyncio
async def test_fixture_is_exactly_grounded_idempotent_and_keeps_brief(service, storage):
    state = await change(service, 0, "set_brief", brief={"perspective": "provider", "role": "", "priorities": "Payment"})
    state = await service.create_fixture("doc-1", WORKSPACE, state.revision)
    assert state.revision == 2 and len(state.runs) == 1
    run = state.runs[0]
    assert run.kind == "fixture" and run.context.perspective == "customer"
    assert state.brief.perspective == "provider" and state.brief.priorities == "Payment"
    assert len(run.findings) == 7
    spans = {span["id"]: (page["page_number"], span["text"])
             for page in storage.document["source_extraction"]["pages"] for span in page["spans"]}
    assert sum(len(f.evidence) for f in run.findings) == 30
    for finding in run.findings:
        for evidence in finding.evidence:
            assert evidence.source_revision_id == "source-1"
            assert spans[evidence.span_id] == (evidence.page_number, evidence.quote)
    repeated = await service.create_fixture("doc-1", WORKSPACE, 0)
    assert repeated == state
    assert len(storage.writes) == 2


@pytest.mark.asyncio
async def test_drafts_saved_questions_markers_and_position_persist_independently(service, storage):
    state = await service.create_fixture("doc-1", WORKSPACE, 0)
    run = state.runs[0]
    finding = run.findings[1]
    scope = {"run_id": run.id, "finding_id": finding.id}
    state = await change(service, state.revision, "set_draft", **scope, text="My unfinished question")
    assert state.personal[run.id].saved_questions == {}
    state = await change(service, state.revision, "save_question", **scope, text="A deliberate saved question")
    question = state.personal[run.id].saved_questions[finding.id]
    state = await change(service, state.revision, "save_question", **scope, text="Updated saved wording")
    assert state.personal[run.id].saved_questions[finding.id].id == question.id
    assert state.personal[run.id].drafts[finding.id] == "My unfinished question"
    assert state.personal[run.id].markers == {} and state.personal[run.id].opened_finding_ids == []
    state = await change(service, state.revision, "set_position", run_id=run.id, position={
        "view": "findings", "finding_id": finding.id, "evidence_span_id": finding.evidence[0].span_id,
    })
    assert state.personal[run.id].opened_finding_ids == [finding.id]
    assert state.personal[run.id].markers == {}
    state = await change(service, state.revision, "set_marker", **scope, marker="revisit")
    state = await change(service, state.revision, "set_marker", **scope, marker="reviewed_by_me")
    assert state.personal[run.id].markers[finding.id] == "reviewed_by_me"
    assert len(state.personal[run.id].saved_questions) == 1
    reloaded = await ReviewWorkspaceService(storage).read("doc-1", WORKSPACE)
    assert reloaded == state
    assert state.runs[0] == run
    assert storage.document["user_interactions"] == {"old-clause": {"notes": ["Preserve legacy note"]}}
    state = await change(service, state.revision, "set_marker", **scope, marker="not_marked")
    assert state.personal[run.id].markers[finding.id] == "not_marked"


@pytest.mark.asyncio
async def test_saved_passage_ranges_restore_alongside_legacy_evidence_without_read_time_rewrite(service, storage):
    state = await service.create_fixture("doc-1", WORKSPACE, 0)
    fixture = state.runs[0]
    page = next(page for page in storage.document["source_extraction"]["pages"] if len(page["spans"]) >= 3)
    first, last = page["spans"][0], page["spans"][2]
    evidence = ReviewEvidence(
        source_revision_id=state.source_revision_id, span_id=first["id"], end_span_id=last["id"],
        page_number=page["page_number"], quote=page["text"][first["start"]:last["end"]],
        label="Synthetic complete passage",
    )
    assert "\n" in evidence.quote and evidence.span_id != evidence.end_span_id
    finding = fixture.findings[0].model_copy(update={"evidence": [evidence]}, deep=True)
    run = ReviewRun(
        id="range-run", kind="ai", status="ready", source_revision_id=state.source_revision_id,
        created_at="synthetic-time", completed_at="synthetic-time", context=state.brief,
        overview_items=[{"text": "Synthetic sourced overview", "evidence": [evidence]}], findings=[finding],
        coverage={"page_count": 25, "extracted_pages": list(range(1, 26)), "omitted_pages": []},
        generation={"model_id": "gpt-5.6-terra", "reasoning_effort": "medium", "max_completion_tokens": 16000,
                    "catalog_verified_on": "synthetic-date", "prompt_version": "synthetic-v1",
                    "schema_version": "synthetic-v1", "extraction_version": "synthetic-v1", "estimated_input_tokens": 100},
    )
    state.runs.append(run)
    # Older persisted evidence has no end key at all. Reading must not migrate it.
    storage.document["review_workspace"] = state.model_dump(exclude_none=True)
    before = deepcopy(storage.document)
    writes_before = len(storage.writes)
    restored = await ReviewWorkspaceService(storage).read("doc-1", WORKSPACE)
    assert storage.document == before and len(storage.writes) == writes_before
    assert restored.runs[0] == fixture
    assert all(item.end_span_id is None for old in restored.runs[0].findings for item in old.evidence)
    assert restored.runs[1] == run
    assert restored.runs[1].overview_items[0].evidence[0] == evidence

    saved = await change(service, restored.revision, "set_position", run_id=run.id, position={
        "view": "document", "finding_id": finding.id, "evidence_span_id": evidence.span_id,
    })
    saved = await change(service, saved.revision, "set_draft", run_id=run.id,
                         finding_id=finding.id, text="Synthetic range-specific draft")
    reloaded = await ReviewWorkspaceService(storage).read("doc-1", WORKSPACE)
    assert reloaded == saved
    assert reloaded.runs[0] == fixture and reloaded.runs[1] == run
    assert reloaded.personal[run.id].position.evidence_span_id == evidence.span_id
    assert reloaded.personal[run.id].drafts[finding.id] == "Synthetic range-specific draft"
    assert storage.document["review_workspace"]["runs"][1]["findings"][0]["evidence"][0]["end_span_id"] == last["id"]


@pytest.mark.asyncio
async def test_noop_does_not_invent_revision_or_change_timestamp(service, storage):
    state = await service.create_fixture("doc-1", WORKSPACE, 0)
    run, finding = state.runs[0], state.runs[0].findings[0]
    state = await change(service, 1, "save_question", run_id=run.id, finding_id=finding.id, text="Keep this")
    before = deepcopy(storage.document)
    repeated = await change(service, 2, "save_question", run_id=run.id, finding_id=finding.id, text="Keep this")
    assert repeated == state and storage.document == before
    assert (await change(service, 2, "set_marker", run_id=run.id, finding_id=finding.id, marker="not_marked")).revision == 2


@pytest.mark.asyncio
async def test_late_draft_and_other_tab_conflict_cannot_replace_newer_work(service, storage):
    state = await service.create_fixture("doc-1", WORKSPACE, 0)
    scope = {"run_id": state.runs[0].id, "finding_id": state.runs[0].findings[0].id}
    newer = await change(service, 1, "set_draft", **scope, text="Newer words")
    with pytest.raises(ReviewWorkspaceError) as caught:
        await change(service, 1, "set_draft", **scope, text="Older words")
    assert caught.value.code == "REVISION_CONFLICT" and caught.value.current_revision == 2
    assert await service.read("doc-1", WORKSPACE) == newer


@pytest.mark.asyncio
async def test_parallel_initial_claims_have_one_winner(service, storage):
    results = await asyncio.gather(*[
        change(service, 0, "set_brief", brief={"perspective": "neutral", "role": "", "priorities": priority})
        for priority in ("Payment", "Exit")
    ], return_exceptions=True)
    assert sum(not isinstance(result, Exception) for result in results) == 1
    failure = next(result for result in results if isinstance(result, Exception))
    assert isinstance(failure, ReviewWorkspaceError) and failure.code == "REVISION_CONFLICT"
    assert len(storage.writes) == 1


@pytest.mark.asyncio
async def test_failed_write_retains_previous_question_and_newer_draft(service, storage, caplog):
    state = await service.create_fixture("doc-1", WORKSPACE, 0)
    scope = {"run_id": state.runs[0].id, "finding_id": state.runs[0].findings[0].id}
    state = await change(service, 1, "save_question", **scope, text="Saved words")
    state = await change(service, 2, "set_draft", **scope, text="Newer unfinished words")
    before = deepcopy(storage.document)
    storage.fail = True
    with pytest.raises(ReviewWorkspaceError) as caught:
        await change(service, 3, "save_question", **scope, text="Replacement words")
    assert caught.value.code == "REVIEW_SAVE_UNCONFIRMED"
    assert storage.document == before
    assert "PRIVATE STORAGE DETAIL" not in caplog.text


@pytest.mark.asyncio
async def test_lost_fixture_response_cannot_duplicate_run(service, storage):
    storage.lose_confirmation = True
    with pytest.raises(ReviewWorkspaceError, match="write could not be confirmed"):
        await service.create_fixture("doc-1", WORKSPACE, 0)
    storage.lose_confirmation = False
    state = await service.create_fixture("doc-1", WORKSPACE, 0)
    assert len(state.runs) == 1 and state.revision == 1 and len(storage.writes) == 1


@pytest.mark.asyncio
async def test_lost_question_response_retains_one_stable_question(service, storage):
    state = await service.create_fixture("doc-1", WORKSPACE, 0)
    scope = {"run_id": state.runs[0].id, "finding_id": state.runs[0].findings[0].id}
    storage.lose_confirmation = True
    with pytest.raises(ReviewWorkspaceError):
        await change(service, 1, "save_question", **scope, text="Question")
    storage.lose_confirmation = False
    with pytest.raises(ReviewWorkspaceError) as caught:
        await change(service, 1, "save_question", **scope, text="Question")
    assert caught.value.code == "REVISION_CONFLICT"
    reloaded = await service.read("doc-1", WORKSPACE)
    retry = await change(service, reloaded.revision, "save_question", **scope, text="Question")
    assert retry == reloaded
    assert len(retry.personal[scope["run_id"]].saved_questions) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("document_id,workspace_id", [("other", "local"), ("doc-1", "other")])
async def test_wrong_scope_never_reads_or_writes(service, storage, document_id, workspace_id):
    for operation in (
        service.read(document_id, workspace_id),
        service.create_fixture(document_id, workspace_id, 0),
        service.update(document_id, workspace_id, update_request(0, {"type": "set_brief", "brief": {}})),
    ):
        with pytest.raises(ReviewWorkspaceError) as caught:
            await operation
        assert caught.value.status_code == 404
    assert storage.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", [
    {"type": "set_draft", "run_id": "wrong", "finding_id": "archive-exit", "text": "Must not save"},
    {"type": "set_marker", "run_id": "actual", "finding_id": "wrong", "marker": "revisit"},
    {"type": "set_position", "run_id": "actual", "position": {"view": "findings", "finding_id": None, "evidence_span_id": None}},
    {"type": "set_position", "run_id": "actual", "position": {"view": "document", "finding_id": "archive-exit", "evidence_span_id": "wrong"}},
    {"type": "save_question", "run_id": "actual", "finding_id": "archive-exit", "text": "   "},
])
async def test_invalid_run_finding_position_or_question_does_not_mutate(service, storage, operation):
    state = await service.create_fixture("doc-1", WORKSPACE, 0)
    operation = deepcopy(operation)
    if operation["run_id"] == "actual":
        operation["run_id"] = state.runs[0].id
    before = deepcopy(storage.document)
    with pytest.raises(ReviewWorkspaceError):
        await service.update("doc-1", WORKSPACE, update_request(1, operation))
    assert storage.document == before


@pytest.mark.asyncio
async def test_legacy_record_is_not_migrated_or_synthetic_user_assigned(storage):
    storage.document.pop("source_revision_id")
    before = deepcopy(storage.document)
    with pytest.raises(ReviewWorkspaceError) as caught:
        await ReviewWorkspaceService(storage).read("doc-1", WORKSPACE)
    assert caught.value.code == "SOURCE_REVISION_REQUIRED"
    assert storage.document == before and storage.writes == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["hash", "partial", "ambiguous", "missing", "source_revision"])
async def test_fixture_and_saved_state_fail_closed_on_source_mismatch(service, storage, mutation):
    if mutation == "source_revision":
        await service.create_fixture("doc-1", WORKSPACE, 0)
        storage.document["source_revision_id"] = "replacement-source"
    elif mutation == "hash":
        storage.document["source_sha256"] = "a" * 64
    elif mutation == "partial":
        storage.document["extraction_status"] = "partial"
    else:
        page = storage.document["source_extraction"]["pages"][14]
        match = json.loads(FIXTURE_PATH.read_text())["findings"][0]["evidence"][0]["match"]
        span = next(span for span in page["spans"] if match in span["text"])
        if mutation == "ambiguous":
            page["spans"].append(deepcopy(span))
        else:
            page["spans"].remove(span)
    before = deepcopy(storage.document)
    with pytest.raises(ReviewWorkspaceError):
        await service.create_fixture("doc-1", WORKSPACE, 0)
    assert storage.document == before


@pytest.mark.parametrize("payload", [
    {"expected_revision": -1, "operation": {"type": "set_brief", "brief": {}}},
    {"expected_revision": True, "operation": {"type": "set_brief", "brief": {}}},
    {"expected_revision": 0, "operation": {"type": "set_brief", "brief": {}, "workspace_id": "other"}},
    {"expected_revision": 0, "operation": {"type": "set_draft", "run_id": "r", "finding_id": "f", "text": "x" * 5001}},
    {"expected_revision": 0, "operation": {"type": "set_brief", "brief": {"perspective": "admin"}}},
    {"expected_revision": 0, "operation": {"type": "set_brief", "brief": {"role": "x" * 201}}},
    {"expected_revision": 0, "operation": {"type": "set_brief", "brief": {"priorities": "x" * 2001}}},
])
def test_request_contract_forbids_identity_overrides_invalid_types_and_excess_text(payload):
    with pytest.raises(ValidationError):
        ReviewWorkspaceUpdate.model_validate(payload)


def test_http_contract_errors_are_safe_and_revision_aware(monkeypatch, storage):
    monkeypatch.setattr(review_workspace, "get_document_service", lambda: storage)
    app = add_api_standardization(FastAPI())
    app.include_router(review_workspace.router, prefix="/api/v1")
    client = TestClient(app)
    path = "/api/v1/documents/doc-1/review-workspace"
    response = client.get(path)
    assert response.status_code == 200 and response.json()["data"]["revision"] == 0
    created = client.post(path + "/fixture", json={"expected_revision": 0})
    assert created.status_code == 200
    run = created.json()["data"]["runs"][0]
    draft = {"expected_revision": 1, "operation": {"type": "set_draft", "run_id": run["id"], "finding_id": "archive-exit", "text": "PRIVATE DRAFT"}}
    assert client.put(path, json=draft).status_code == 200
    conflict = client.put(path, json=draft)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "REVISION_CONFLICT"
    assert conflict.json()["error"]["details"]["current_revision"] == 2
    assert "PRIVATE DRAFT" not in conflict.text
    draft["operation"]["text"] = "PRIVATE DRAFT" * 500
    invalid = client.put(path, json=draft)
    assert invalid.status_code == 422 and "PRIVATE DRAFT" not in invalid.text
    assert "pdf_file_id" not in client.get(path).text
    assert client.get(path + "?workspace_id=other").json()["data"]["document_id"] == "doc-1"


@pytest.mark.asyncio
async def test_document_deletion_also_removes_review_without_side_collection(service, storage):
    await service.create_fixture("doc-1", WORKSPACE, 0)
    assert "review_workspace" in storage.document
    storage.document = None
    with pytest.raises(ReviewWorkspaceError) as caught:
        await service.read("doc-1", WORKSPACE)
    assert caught.value.status_code == 404
