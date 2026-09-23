"""Bounded source-scoped review data, distinct from legacy clauses and notes."""
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


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
    # Omitted/null retains the original exact single-span quotation contract.
    # A range includes both anchors and all original text between them on one page.
    end_span_id: ReviewId | None = None
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
    basis: Literal["source_text", "not_found"] = "source_text"
    coverage_basis: str = Field(default="", max_length=2000)


class ReviewOverviewItem(ReviewModel):
    text: str = Field(min_length=1, max_length=2000)
    evidence: list[ReviewEvidence] = Field(min_length=1, max_length=30)


class ReviewCoverage(ReviewModel):
    page_count: int = Field(ge=0)
    extracted_pages: list[int]
    omitted_pages: list[int]
    input_scope: Literal["all_extracted_text"] = "all_extracted_text"
    limitations: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def check_pages(self):
        pages = self.extracted_pages + self.omitted_pages
        if sorted(pages) != list(range(1, self.page_count + 1)):
            raise ValueError("Coverage must account for each physical page exactly once")
        return self


class ReviewUsage(ReviewModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)


class ReviewGeneration(ReviewModel):
    model_id: str
    endpoint: Literal["chat.completions"] = "chat.completions"
    reasoning_effort: str
    max_completion_tokens: int = Field(gt=0)
    catalog_verified_on: str
    prompt_version: str
    schema_version: str
    extraction_version: str
    estimated_input_tokens: int = Field(ge=0)
    usage: ReviewUsage | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class ReviewFailure(ReviewModel):
    code: str = Field(max_length=100)
    message: str = Field(max_length=2000)


class ReviewAskAnswerItem(ReviewModel):
    text: str = Field(min_length=1, max_length=5000)
    evidence: list[ReviewEvidence] = Field(default_factory=list, max_length=10)


class ReviewAskTurn(ReviewModel):
    """One explicit paid attempt, separate from saved questions and review output."""

    id: ReviewId
    run_id: ReviewId
    finding_id: ReviewId
    source_revision_id: ReviewId
    question: str = Field(min_length=1, max_length=5000)
    created_at: str
    status: Literal["processing", "ready", "incomplete", "failed", "interrupted"] = "processing"
    completed_at: str | None = None
    answer: list[ReviewAskAnswerItem] = Field(default_factory=list, max_length=20)
    limitations: list[Annotated[str, Field(max_length=2000)]] = Field(default_factory=list, max_length=20)
    generation: ReviewGeneration
    coverage: ReviewCoverage
    failure: ReviewFailure | None = None
    history_turn_ids: list[ReviewId] = Field(default_factory=list, max_length=6)
    include_history: bool = True
    history_truncated: bool = False

    @model_validator(mode="after")
    def check_answer_state(self):
        if not self.question.strip():
            raise ValueError("Ask requires a nonblank question")
        if len(set(self.history_turn_ids)) != len(self.history_turn_ids) or self.id in self.history_turn_ids:
            raise ValueError("Ask history must contain distinct earlier attempts")
        if not self.include_history and (self.history_turn_ids or self.history_truncated):
            raise ValueError("A fresh question cannot include earlier answers")
        if self.status in ("processing", "failed", "interrupted") and self.answer:
            raise ValueError("Unfinished or failed attempts cannot publish an answer")
        if self.status == "ready" and (not self.answer or self.failure or self.coverage.omitted_pages):
            raise ValueError("Ready answers require output and no known incomplete state")
        if self.status == "processing" and (self.completed_at is not None or self.failure is not None):
            raise ValueError("Processing attempts cannot have terminal metadata")
        if self.status != "processing" and self.completed_at is None:
            raise ValueError("Terminal answers require a completion timestamp")
        return self


class ReviewRun(ReviewModel):
    id: ReviewId
    kind: Literal["fixture", "ai"]
    source_revision_id: ReviewId
    created_at: str
    context: ReviewBrief
    fixture_version: str | None = Field(default=None, min_length=1, max_length=100)
    overview: str = Field(default="", max_length=20000)
    findings: list[ReviewFinding] = Field(default_factory=list, max_length=100)
    status: Literal["processing", "ready", "incomplete", "failed", "interrupted"] = "ready"
    completed_at: str | None = None
    overview_items: list[ReviewOverviewItem] = Field(default_factory=list, max_length=30)
    coverage: ReviewCoverage | None = None
    generation: ReviewGeneration | None = None
    failure: ReviewFailure | None = None

    @model_validator(mode="after")
    def check_generated_state(self):
        # Old fixture snapshots remain readable without invented AI provenance.
        if self.kind == "ai":
            if self.generation is None or self.coverage is None:
                raise ValueError("AI attempts require generation and source coverage metadata")
            if self.status == "ready" and (self.failure or self.coverage.omitted_pages or not self.overview_items):
                raise ValueError("Ready reviews require sourced overview and no known incomplete state")
            if self.status in ("processing", "failed", "interrupted") and (self.findings or self.overview_items or self.overview):
                raise ValueError("Unfinished or failed attempts cannot publish review output")
            if self.status != "processing" and self.completed_at is None:
                raise ValueError("Terminal attempts require a completion timestamp")
        return self


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
    ask_drafts: dict[ReviewId, Annotated[str, Field(max_length=5000)]] = Field(default_factory=dict, max_length=100)
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
    ask_turns: list[ReviewAskTurn] = Field(default_factory=list, max_length=100)
    fixture_available: bool = False


class SetBrief(ReviewModel):
    type: Literal["set_brief"]
    brief: ReviewBrief


class SetDraft(ReviewModel):
    type: Literal["set_draft"]
    run_id: ReviewId
    finding_id: ReviewId
    text: str = Field(max_length=5000)


class SetAskDraft(ReviewModel):
    type: Literal["set_ask_draft"]
    run_id: ReviewId
    finding_id: ReviewId
    text: str = Field(max_length=5000)


class SaveQuestion(ReviewModel):
    type: Literal["save_question"]
    run_id: ReviewId
    finding_id: ReviewId
    text: str = Field(min_length=1, max_length=5000)


class RemoveQuestion(ReviewModel):
    type: Literal["remove_question"]
    run_id: ReviewId
    finding_id: ReviewId


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
    Union[SetBrief, SetDraft, SetAskDraft, SaveQuestion, RemoveQuestion, SetMarker, SetPosition], Field(discriminator="type"),
]


class ReviewWorkspaceUpdate(ReviewModel):
    expected_revision: int = Field(ge=0)
    operation: ReviewWorkspaceOperation


class FixtureReviewRequest(ReviewModel):
    expected_revision: int = Field(ge=0)


class StartReviewRequest(ReviewModel):
    expected_revision: int = Field(ge=0)
    request_id: ReviewId
    model_id: str = Field(min_length=1, max_length=100)


class InterruptReviewRequest(ReviewModel):
    expected_revision: int = Field(ge=0)


class StartAskRequest(ReviewModel):
    expected_revision: int = Field(ge=0)
    request_id: ReviewId
    model_id: str = Field(min_length=1, max_length=100)
    question: str = Field(min_length=1, max_length=5000)
    include_history: bool = True

    @model_validator(mode="after")
    def check_question(self):
        if not self.question.strip():
            raise ValueError("Ask requires a nonblank question")
        return self
