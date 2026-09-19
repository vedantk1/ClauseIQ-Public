/**
 * Document-related TypeScript interfaces and types
 * Extracted from documents page for better type safety and reusability
 */
import type { SourceMetadata } from "@clauseiq/shared-types";

export interface DocumentItem extends SourceMetadata {
  id: string;
  filename: string;
  upload_date: string;
  contract_type?: string | null;
  page_count?: number | null;
  last_viewed?: string | null;
  review_summary?: LibraryReviewSummary | null;
}

/** Read-only list metadata, never a substitute for opening the saved review. */
export interface LibraryReviewSummary {
  kind: "fixture" | "ai" | null;
  status: "not_started" | "ready" | "incomplete" | "processing" | "failed" | "interrupted" | "unavailable";
  saved_question_count: number;
  last_activity_at: string | null;
  can_resume: boolean;
}

export type ViewMode = "grid" | "list";

export type SortOption = "newest" | "oldest" | "name";

// Contract type color mapping type
export type ContractTypeColorMap = Record<string, string>;
