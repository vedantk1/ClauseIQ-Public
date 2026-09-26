"""Ask provenance and personal drafts remain distinct from generated reviews."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from clauseiq_types.review import (
    ReviewAskAnswerItem, ReviewAskTurn, ReviewPersonalState, ReviewWorkspaceResponse,
    ReviewWorkspaceUpdate, StartAskRequest,
)


def attempt():
    return {
        "id": "ask-1", "run_id": "run-1", "finding_id": "finding-1",
        "source_revision_id": "source-1", "question": "What remains uncertain?",
        "created_at": "synthetic-time",
        "coverage": {"page_count": 2, "extracted_pages": [1, 2], "omitted_pages": []},
        "generation": {
            "model_id": "gpt-5.6-terra", "reasoning_effort": "medium",
            "max_completion_tokens": 4000, "catalog_verified_on": "synthetic-date",
            "prompt_version": "ask-test-v1", "schema_version": "ask-test-v1",
            "extraction_version": "test-v1", "estimated_input_tokens": 100,
        },
    }


def answer():
    return [{"text": "Payment is conditional on acceptance.", "evidence": [{
        "source_revision_id": "source-1", "span_id": "span-1", "end_span_id": "span-3",
        "page_number": 1, "quote": "Payment is due.\nOnly after acceptance.", "label": "Condition",
    }]}]


def test_old_workspace_and_personal_state_need_no_migration():
    state = ReviewWorkspaceResponse(document_id="doc-1", source_revision_id="source-1", revision=0)
    assert state.ask_turns == []
    personal = ReviewPersonalState(drafts={"finding-1": "Keep this wording"})
    assert personal.ask_drafts == {}
    assert personal.saved_questions == {}
    assert personal.drafts["finding-1"] == "Keep this wording"


def test_ask_draft_is_a_separate_scoped_operation():
    update = ReviewWorkspaceUpdate(expected_revision=1, operation={
        "type": "set_ask_draft", "run_id": "run-1", "finding_id": "finding-1", "text": "Ask this",
    })
    assert update.operation.type == "set_ask_draft"
    personal = ReviewPersonalState(drafts={"finding-1": "Keep"}, ask_drafts={"finding-1": "Ask"})
    assert personal.drafts != personal.ask_drafts


@pytest.mark.parametrize("mutation", [
    {"expected_revision": True}, {"expected_revision": -1}, {"request_id": "bad.id"},
    {"question": "   "}, {"question": ""}, {"question": "q" * 5001},
    {"include_history": "true"}, {"model_id": ""}, {"workspace_id": "elsewhere"},
    {"api_key": "synthetic-disallowed"}, {"context": {"perspective": "provider"}},
    {"history_turn_ids": ["ask-other"]},
])
def test_start_cannot_override_source_context_history_or_credentials(mutation):
    with pytest.raises(ValidationError):
        StartAskRequest.model_validate({
            "expected_revision": 0, "request_id": "ask-1", "model_id": "gpt-5.6-terra",
            "question": "What does this mean?", **mutation,
        })


@pytest.mark.parametrize("mutation", [
    {"question": "\n\t"}, {"generation": None}, {"coverage": None},
    {"answer": answer()}, {"completed_at": "synthetic-time"},
    {"failure": {"code": "FAILED", "message": "Failed"}},
    {"history_turn_ids": ["ask-1"]}, {"history_turn_ids": ["old", "old"]},
    {"history_turn_ids": [f"old-{i}" for i in range(7)]},
    {"include_history": False, "history_turn_ids": ["old"]},
    {"include_history": False, "history_truncated": True},
    {"status": "ready", "completed_at": "synthetic-time"},
    {"status": "failed"}, {"status": "interrupted"},
    {"status": "failed", "completed_at": "synthetic-time", "answer": answer()},
    {"status": "ready", "completed_at": "synthetic-time", "answer": answer(),
     "coverage": {"page_count": 2, "extracted_pages": [1], "omitted_pages": [2]}},
    {"status": "ready", "completed_at": "synthetic-time", "answer": answer(),
     "failure": {"code": "FAILED", "message": "Failed"}},
])
def test_invalid_or_unfinished_turn_cannot_masquerade_as_ready(mutation):
    with pytest.raises(ValidationError):
        ReviewAskTurn.model_validate({**attempt(), **deepcopy(mutation)})


def test_terminal_answer_preserves_exact_evidence_and_provenance():
    turn = ReviewAskTurn.model_validate({
        **attempt(), "status": "ready", "completed_at": "synthetic-time", "answer": answer(),
        "history_turn_ids": ["old-1"],
    })
    restored = ReviewAskTurn.model_validate_json(turn.model_dump_json())
    assert restored == turn
    assert restored.answer[0].evidence[0].quote == "Payment is due.\nOnly after acceptance."
    assert restored.generation.reasoning_effort == "medium"
    assert restored.history_turn_ids == ["old-1"]
    assert restored.answer[0].inline_citations == []


def test_inline_mapping_round_trip_preserves_original_text_and_exact_index():
    item = answer()[0]
    item.update(text="Payment has a condition [p1_b3_v1].", inline_citations=[
        {"passage_id": "p1_b3_v1", "evidence_index": 0},
    ])
    parsed = ReviewAskAnswerItem.model_validate(item)
    restored = ReviewAskAnswerItem.model_validate_json(parsed.model_dump_json())
    assert restored == parsed and restored.text == item["text"]
    assert restored.inline_citations[0].evidence_index == 0


@pytest.mark.parametrize("mapping", [
    None, [{"passage_id": "p1_b3_v1", "evidence_index": -1}],
    [{"passage_id": "p1_b3_v1", "evidence_index": 1}],
    [{"passage_id": "p1_b3_v1", "evidence_index": True}],
    [{"passage_id": "p1_b3_v1", "evidence_index": 0.5}],
    [{"passage_id": "unknown", "evidence_index": 0}],
    [{"passage_id": "p0_b3_v1", "evidence_index": 0}],
    [{"passage_id": "p1_b3_v1", "evidence_index": 0}] * 2,
    [{"passage_id": "p1_b3_v1", "evidence_index": 0}, {"passage_id": "p1_b4_v1", "evidence_index": 0}],
])
def test_malformed_inline_mapping_cannot_select_an_unrelated_or_missing_reference(mapping):
    with pytest.raises(ValidationError):
        ReviewAskAnswerItem.model_validate({**answer()[0], "inline_citations": mapping})


def test_partial_source_answer_remains_incomplete():
    turn = ReviewAskTurn.model_validate({
        **attempt(), "status": "incomplete", "completed_at": "synthetic-time", "answer": answer(),
        "coverage": {"page_count": 2, "extracted_pages": [1], "omitted_pages": [2]},
        "limitations": ["Page 2 was not extracted."],
    })
    assert turn.status == "incomplete"
