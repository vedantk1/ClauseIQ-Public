/** Local personal review state; generated fixture runs remain immutable. */
export interface ReviewBrief {
  perspective: "neutral" | "customer" | "provider" | "other";
  role: string;
  priorities: string;
}

export interface ReviewEvidence {
  source_revision_id: string;
  span_id: string;
  page_number: number;
  quote: string;
  label: string;
}

export interface ReviewFinding {
  id: string;
  title: string;
  facts: string;
  interpretation: string;
  uncertainty: string;
  next_step: string;
  suggested_question: string;
  evidence: ReviewEvidence[];
}

export interface ReviewRun {
  id: string;
  kind: "fixture";
  source_revision_id: string;
  created_at: string;
  context: ReviewBrief;
  fixture_version: string;
  overview: string;
  findings: ReviewFinding[];
}

export type ReviewMarker = "not_marked" | "revisit" | "reviewed_by_me";
export interface ReviewPosition {
  view: "overview" | "findings" | "document" | "my_review";
  finding_id: string | null;
  evidence_span_id: string | null;
}

export interface SavedReviewQuestion {
  id: string;
  text: string;
  saved_at: string;
}

export interface ReviewPersonalState {
  drafts: Record<string, string>;
  saved_questions: Record<string, SavedReviewQuestion>;
  markers: Record<string, ReviewMarker>;
  opened_finding_ids: string[];
  position: ReviewPosition;
}

export interface ReviewWorkspaceResponse {
  document_id: string;
  source_revision_id: string;
  revision: number;
  brief: ReviewBrief;
  runs: ReviewRun[];
  personal: Record<string, ReviewPersonalState>;
  fixture_available: boolean;
}

export type ReviewWorkspaceOperation =
  | { type: "set_brief"; brief: ReviewBrief }
  | { type: "set_draft" | "save_question"; run_id: string; finding_id: string; text: string }
  | { type: "set_marker"; run_id: string; finding_id: string; marker: ReviewMarker }
  | { type: "set_position"; run_id: string; position: ReviewPosition };

export interface ReviewWorkspaceUpdate {
  expected_revision: number;
  operation: ReviewWorkspaceOperation;
}

export interface FixtureReviewRequest {
  expected_revision: number;
}
