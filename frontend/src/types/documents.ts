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
}

export type ViewMode = "grid" | "list";

export type SortOption = "newest" | "oldest" | "name";

// Contract type color mapping type
export type ContractTypeColorMap = Record<string, string>;
