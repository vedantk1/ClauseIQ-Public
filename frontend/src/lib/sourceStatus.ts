import type { SourceMetadata } from "@clauseiq/shared-types";

/** Keep lifecycle metadata separate from generated analysis fields. */
export function pickSourceMetadata(document: SourceMetadata): SourceMetadata {
  return {
    source_revision_id: document.source_revision_id,
    source_sha256: document.source_sha256,
    source_status: document.source_status,
    extraction_status: document.extraction_status,
    extraction_error: document.extraction_error,
    analysis_status: document.analysis_status,
  };
}

export function hasCompletedAnalysis(document: SourceMetadata): boolean {
  if (document.analysis_status != null) {
    return document.analysis_status === "ready";
  }
  // Old records do not have lifecycle metadata. Do not hide their saved work.
  return !document.source_revision_id && !document.source_sha256 &&
    !document.source_status && !document.extraction_status;
}

export function getDocumentSourceStatus(document: SourceMetadata): {
  label: string;
  message: string;
  tone: "success" | "warning" | "error";
} {
  if (hasCompletedAnalysis(document)) {
    return { label: "Complete", message: "Saved analysis is available.", tone: "success" };
  }
  if (document.source_status === "storage_failed") {
    return { label: "Original not saved", message: "The original PDF could not be saved. No completed review is available.", tone: "error" };
  }
  if (document.source_status === "storing") {
    return { label: "Saving original", message: "The original PDF has not finished saving. No completed review is available.", tone: "warning" };
  }
  if (document.extraction_status === "failed") {
    return { label: "Text extraction failed", message: "Text extraction did not finish. The original PDF is separate from the review; this is not a completed analysis.", tone: "error" };
  }
  if (document.extraction_status === "partial") {
    return { label: "Incomplete source text", message: "Text was not extracted from every page. No completed AI review is available; missing text must not be treated as an absence of issues.", tone: "warning" };
  }
  if (document.extraction_status === "unavailable") {
    return { label: "No extractable text", message: "No usable text was extracted from this PDF. It has not been reviewed by AI.", tone: "warning" };
  }
  if (document.extraction_status === "processing" || document.extraction_status === "pending") {
    return { label: "Preparing source text", message: "Text extraction is pending or in progress. This document does not have a completed AI review.", tone: "warning" };
  }
  if (document.analysis_status === "processing") {
    return { label: "Analysis in progress", message: "The analysis has not finished. No completed review is available yet.", tone: "warning" };
  }
  if (document.analysis_status === "failed") {
    return { label: "Analysis failed", message: "The analysis did not finish. No completed review is available; the original document remains separate from the AI result.", tone: "error" };
  }
  return { label: "Not yet reviewed", message: "This document has been imported, but no AI review has been completed. Extracting text does not constitute a review.", tone: "warning" };
}
