/** Local personal work is independent of source-scoped review runs. */
export interface ReviewBrief {
  perspective: "neutral" | "customer" | "provider" | "other";
  role: string;
  priorities: string;
}

export interface ReviewEvidence {
  source_revision_id: string;
  span_id: string;
  /** Inclusive same-page end anchor; absent/null means the original single span. */
  end_span_id?: string | null;
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
  basis?: "source_text" | "not_found";
  coverage_basis?: string;
}

export interface ReviewOverviewItem { text: string; evidence: ReviewEvidence[] }
export interface ReviewCoverage {
  page_count: number;
  extracted_pages: number[];
  omitted_pages: number[];
  input_scope: "all_extracted_text";
  limitations: string[];
}
export interface ReviewGeneration {
  model_id: string;
  endpoint: "chat.completions";
  reasoning_effort: string;
  max_completion_tokens: number;
  catalog_verified_on: string;
  prompt_version: string;
  schema_version: string;
  extraction_version: string;
  estimated_input_tokens: number;
  usage: { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null;
  duration_ms: number | null;
}

export interface ReviewAskAnswerItem {
  text: string;
  evidence: ReviewEvidence[];
}

export interface ReviewAskTurn {
  id: string;
  run_id: string;
  finding_id: string;
  source_revision_id: string;
  question: string;
  created_at: string;
  status: "processing" | "ready" | "incomplete" | "failed" | "interrupted";
  completed_at: string | null;
  answer: ReviewAskAnswerItem[];
  limitations: string[];
  generation: ReviewGeneration;
  coverage: ReviewCoverage;
  failure: { code: string; message: string } | null;
  history_turn_ids: string[];
  include_history: boolean;
  history_truncated: boolean;
}

export interface ReviewRun {
  id: string;
  kind: "fixture" | "ai";
  source_revision_id: string;
  created_at: string;
  context: ReviewBrief;
  fixture_version?: string | null;
  overview: string;
  findings: ReviewFinding[];
  status?: "processing" | "ready" | "incomplete" | "failed" | "interrupted";
  completed_at?: string | null;
  overview_items?: ReviewOverviewItem[];
  coverage?: ReviewCoverage | null;
  generation?: ReviewGeneration | null;
  failure?: { code: string; message: string } | null;
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
  /** Optional for existing snapshots; independent of saved-question drafts. */
  ask_drafts?: Record<string, string>;
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
  /** Old snapshots have no Ask attempts. Reading never starts a request. */
  ask_turns?: ReviewAskTurn[];
  fixture_available: boolean;
}

export type ReviewWorkspaceOperation =
  | { type: "set_brief"; brief: ReviewBrief }
  | { type: "set_draft" | "set_ask_draft" | "save_question"; run_id: string; finding_id: string; text: string }
  | { type: "remove_question"; run_id: string; finding_id: string }
  | { type: "set_marker"; run_id: string; finding_id: string; marker: ReviewMarker }
  | { type: "set_position"; run_id: string; position: ReviewPosition };

export interface ReviewWorkspaceUpdate {
  expected_revision: number;
  operation: ReviewWorkspaceOperation;
}

export interface FixtureReviewRequest {
  expected_revision: number;
}

export interface StartReviewRequest {
  expected_revision: number;
  request_id: string;
  model_id: string;
  reasoning_effort?: string;
}

export interface StartAskRequest {
  expected_revision: number;
  request_id: string;
  model_id: string;
  reasoning_effort?: string;
  question: string;
  include_history: boolean;
}
