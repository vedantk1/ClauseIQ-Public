/** Page-aware source text. Offsets are page-relative, end-exclusive Unicode code points, not UTF-16 indices. */
export type SourceWarning = "no_extractable_text" | "page_extraction_failed";

export interface SourceSpan {
  id: string;
  start: number;
  end: number;
  text: string;
}

export interface SourcePage {
  page_number: number;
  text: string;
  status: "extracted" | "empty" | "failed";
  spans: SourceSpan[];
  warnings: SourceWarning[];
}

export interface SourceExtraction {
  content_sha256: string;
  extraction_version: string;
  status: "complete" | "partial" | "unavailable";
  page_count: number;
  pages: SourcePage[];
  warnings: SourceWarning[];
  text: string;
}

/** Missing lifecycle metadata identifies a legacy analyzed document. */
export interface SourceMetadata {
  source_revision_id?: string | null;
  source_sha256?: string | null;
  source_status?: "storing" | "stored" | "storage_failed" | null;
  extraction_status?: "pending" | "processing" | "complete" | "partial" | "unavailable" | "failed" | null;
  extraction_error?: string | null;
  analysis_status?: "not_started" | "processing" | "ready" | "failed" | null;
}

export interface DocumentSourceResponse extends SourceMetadata {
  id: string;
  source_extraction?: SourceExtraction | null;
}
