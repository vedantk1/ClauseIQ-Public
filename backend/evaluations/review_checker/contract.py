"""Strict diagnostic shapes and exact reference checks, not semantic validation."""

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import Field

from clauseiq_types.review import (
    ReviewBrief, ReviewCoverage, ReviewFailure, ReviewFinding, ReviewGeneration,
    ReviewId, ReviewModel, ReviewOverviewItem,
)

MAX_CHECK_TARGETS = 100
MAX_DIAGNOSTIC_BYTES = 1_000_000
ShortText = Annotated[str, Field(min_length=1, max_length=1000)]
LocalId = Annotated[str, Field(min_length=1, max_length=160)]
PassageIds = Annotated[list[LocalId], Field(min_length=1, max_length=12)]


class CheckCandidate(ReviewModel):
    """Only the immutable material being assessed, never personal workspace state."""
    source_revision_id: ReviewId
    context: ReviewBrief
    overview_items: list[ReviewOverviewItem] = Field(min_length=1, max_length=30)
    findings: list[ReviewFinding] = Field(max_length=100)
    coverage: ReviewCoverage


class CheckBinding(ReviewModel):
    source_revision_id: ReviewId
    source_sha256: str
    extraction_sha256: str
    extraction_version: str
    passage_version: str
    candidate_sha256: str
    brief_sha256: str


class TargetCheck(ReviewModel):
    target_id: LocalId
    status: Literal["assessed", "not_assessable", "no_factual_assertion"]
    reason: str = Field(min_length=1, max_length=300)


class ClaimIssue(ReviewModel):
    target_id: LocalId
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=10000)
    category: Literal["own_evidence_missing", "source_conflict", "qualification_missing", "absence_overstated"]
    explanation: ShortText
    passage_ids: PassageIds


class PriorityGap(ReviewModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str = Field(min_length=1, max_length=2000)
    explanation: ShortText
    passage_ids: PassageIds
    related_item_ids: list[LocalId] = Field(max_length=30)


class PriorityAssessment(ReviewModel):
    status: Literal["addressed", "partial", "not_addressed", "not_assessable", "not_stated"]
    explanation: ShortText
    gaps: list[PriorityGap] = Field(max_length=12)


class DiagnosticReport(ReviewModel):
    target_checks: list[TargetCheck] = Field(min_length=1, max_length=MAX_CHECK_TARGETS)
    claim_issues: list[ClaimIssue] = Field(max_length=50)
    priority_assessment: PriorityAssessment
    limitations: list[ShortText] = Field(max_length=20)


class CheckResult(ReviewModel):
    # Completed means the diagnostic contract was satisfied, NOT that the review is correct.
    status: Literal["completed", "incomplete", "failed"]
    diagnostics: DiagnosticReport | None
    binding: CheckBinding
    generation: ReviewGeneration
    failure: ReviewFailure | None


@dataclass(frozen=True)
class PreparedCheck:
    generation: ReviewGeneration
    messages: list[dict[str, str]]
    response_format: dict
    timeout_seconds: int
    binding: CheckBinding
    targets: dict[str, str]
    item_ids: frozenset[str]
    passage_ids: frozenset[str]
    priorities: str
    source_complete: bool


def _unique_known(values, known):
    if len(values) != len(set(values)) or not set(values) <= known:
        raise ValueError("Diagnostic references must be unique and supplied.")


def _exact_excerpt(text, start, end, quote):
    # Python offsets count Unicode code points; no whitespace repair or first-match search.
    if not quote.strip() or not 0 <= start < end <= len(text) or text[start:end] != quote:
        raise ValueError("Diagnostic excerpt does not match its exact target.")


def validate_diagnostics(prepared: PreparedCheck, report: DiagnosticReport) -> None:
    """Check complete inventory and exact IDs/offsets; never declare a claim true."""
    checked = [entry.target_id for entry in report.target_checks]
    _unique_known(checked, set(prepared.targets))
    if set(checked) != set(prepared.targets):
        raise ValueError("Every supplied target requires exactly one diagnostic check.")
    states = {entry.target_id: entry.status for entry in report.target_checks}
    if any(not entry.reason.strip() for entry in report.target_checks):
        raise ValueError("Diagnostic reasons must not be blank.")
    if any(not item.strip() for item in report.limitations):
        raise ValueError("Diagnostic limitations must not be blank.")
    seen_issues = set()
    for issue in report.claim_issues:
        if issue.target_id not in prepared.targets or states[issue.target_id] != "assessed":
            raise ValueError("A claim issue requires an assessed supplied target.")
        _exact_excerpt(prepared.targets[issue.target_id], issue.start, issue.end, issue.quote)
        _unique_known(issue.passage_ids, prepared.passage_ids)
        identity = (issue.target_id, issue.start, issue.end, issue.category)
        if not issue.explanation.strip() or identity in seen_issues:
            raise ValueError("Diagnostic issues must be explained and unique.")
        seen_issues.add(identity)

    priorities = report.priority_assessment
    if not priorities.explanation.strip():
        raise ValueError("Priority assessment must be explained.")
    if not prepared.priorities.strip():
        if priorities.status != "not_stated" or priorities.gaps:
            raise ValueError("Unstated priorities must not be invented.")
    elif priorities.status == "not_stated":
        raise ValueError("Supplied priorities cannot be marked unstated.")
    if priorities.status in ("addressed", "not_stated") and priorities.gaps:
        raise ValueError("An addressed priority report cannot also contain gaps.")
    if priorities.status in ("partial", "not_addressed") and not priorities.gaps:
        raise ValueError("A priority gap assessment requires concrete diagnostics.")
    seen_gaps = set()
    for gap in priorities.gaps:
        _exact_excerpt(prepared.priorities, gap.start, gap.end, gap.quote)
        _unique_known(gap.passage_ids, prepared.passage_ids)
        _unique_known(gap.related_item_ids, prepared.item_ids)
        identity = (gap.start, gap.end, tuple(sorted(gap.passage_ids)))
        if not gap.explanation.strip() or identity in seen_gaps:
            raise ValueError("Priority gaps must be explained and unique.")
        seen_gaps.add(identity)
