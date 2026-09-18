"""Bounded source-scoped review data, distinct from legacy clauses and notes."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


ReviewId = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")]
ReviewMarker = Literal["not_marked", "revisit", "reviewed_by_me"]


class ReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReviewBrief(ReviewModel):
    perspective: Literal["neutral", "customer", "provider", "other"] = "neutral"
    role: str = Field(default="", max_length=200)
    priorities: str = Field(default="", max_length=2000)


class ReviewEvidence(ReviewModel):
    source_revision_id: ReviewId
    span_id: ReviewId
    page_number: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=20000)
    label: str = Field(min_length=1, max_length=200)


class ReviewFinding(ReviewModel):
    id: ReviewId
    title: str = Field(min_length=1, max_length=300)
    facts: str = Field(max_length=10000)
    interpretation: str = Field(max_length=10000)
    uncertainty: str = Field(max_length=10000)
    next_step: str = Field(max_length=5000)
    suggested_question: str = Field(max_length=5000)
    evidence: list[ReviewEvidence] = Field(min_length=1, max_length=30)


class ReviewRun(ReviewModel):
    id: ReviewId
    kind: Literal["fixture"]
    source_revision_id: ReviewId
    created_at: str
    context: ReviewBrief
    fixture_version: str = Field(min_length=1, max_length=100)
    overview: str = Field(max_length=20000)
    findings: list[ReviewFinding] = Field(min_length=1, max_length=100)


class ReviewPosition(ReviewModel):
    view: Literal["overview", "findings", "document", "my_review"] = "overview"
    finding_id: ReviewId | None = None
    evidence_span_id: ReviewId | None = None


class SavedReviewQuestion(ReviewModel):
    id: ReviewId
    text: str = Field(min_length=1, max_length=5000)
    saved_at: str


class ReviewPersonalState(ReviewModel):
    drafts: dict[ReviewId, Annotated[str, Field(max_length=5000)]] = Field(default_factory=dict, max_length=100)
    saved_questions: dict[ReviewId, SavedReviewQuestion] = Field(default_factory=dict, max_length=100)
    markers: dict[ReviewId, ReviewMarker] = Field(default_factory=dict, max_length=100)
    opened_finding_ids: list[ReviewId] = Field(default_factory=list, max_length=100)
    position: ReviewPosition = Field(default_factory=ReviewPosition)


class ReviewWorkspaceResponse(ReviewModel):
    document_id: ReviewId
    source_revision_id: ReviewId
    revision: int = Field(ge=0)
    brief: ReviewBrief = Field(default_factory=ReviewBrief)
    runs: list[ReviewRun] = Field(default_factory=list, max_length=100)
    personal: dict[ReviewId, ReviewPersonalState] = Field(default_factory=dict, max_length=100)
    fixture_available: bool = False


class SetBrief(ReviewModel):
    type: Literal["set_brief"]
    brief: ReviewBrief


class SetDraft(ReviewModel):
    type: Literal["set_draft"]
    run_id: ReviewId
    finding_id: ReviewId
    text: str = Field(max_length=5000)


class SaveQuestion(ReviewModel):
    type: Literal["save_question"]
    run_id: ReviewId
    finding_id: ReviewId
    text: str = Field(min_length=1, max_length=5000)


class SetMarker(ReviewModel):
    type: Literal["set_marker"]
    run_id: ReviewId
    finding_id: ReviewId
    marker: ReviewMarker


class SetPosition(ReviewModel):
    type: Literal["set_position"]
    run_id: ReviewId
    position: ReviewPosition


ReviewWorkspaceOperation = Annotated[
    Union[SetBrief, SetDraft, SaveQuestion, SetMarker, SetPosition], Field(discriminator="type"),
]


class ReviewWorkspaceUpdate(ReviewModel):
    expected_revision: int = Field(ge=0)
    operation: ReviewWorkspaceOperation


class FixtureReviewRequest(ReviewModel):
    expected_revision: int = Field(ge=0)
