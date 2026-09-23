import type { DocumentItem } from "@/types/documents";
import { hasCompletedAnalysis } from "@/lib/sourceStatus";

export function canOpenWorkspace(document: DocumentItem): boolean {
  return !!document.source_revision_id && document.source_status === "stored";
}

export function documentDestination(document: DocumentItem, resume = false): string {
  const path = canOpenWorkspace(document) ? "/workspace" : "/review";
  return `${path}?documentId=${encodeURIComponent(document.id)}${resume && canOpenWorkspace(document) ? "&resume=1" : ""}`;
}

export function libraryReviewLabel(document: DocumentItem): string {
  const review = document.review_summary;
  if (review) {
    switch (review.status) {
      case "ready": return review.kind === "fixture" ? "Example review" : "AI review available";
      case "incomplete": return review.kind === "fixture" ? "Incomplete example" : "Incomplete AI review";
      case "processing": return "Review in progress";
      case "failed": return "Review failed";
      case "interrupted": return "Review interrupted";
      case "unavailable": return "Review state unavailable";
    }
  }
  if (document.analysis_status === "processing") return "Earlier analysis in progress";
  if (document.analysis_status === "failed") return "Earlier analysis failed";
  if (hasCompletedAnalysis(document)) return "Earlier analysis available";
  // Older servers have no summary: do not infer review status from extraction.
  return review ? "Review not started" : "Review status unavailable";
}

export function sourceNotice(document: DocumentItem): string | null {
  if (document.source_status === "storage_failed") return "Original not saved";
  if (document.source_status === "storing") return "Saving original";
  switch (document.extraction_status) {
    case "partial": return "Incomplete source text";
    case "failed": return "Text extraction failed";
    case "unavailable": return "No extractable text";
    case "pending":
    case "processing": return "Preparing source text";
    default: return null;
  }
}

export function pageCountLabel(document: DocumentItem): string {
  const count = document.page_count;
  return typeof count === "number" && Number.isInteger(count) && count > 0
    ? `${count} ${count === 1 ? "page" : "pages"}` : "Pages unavailable";
}

export function savedQuestionLabel(document: DocumentItem): string {
  const count = document.review_summary?.saved_question_count || 0;
  return `${count} saved ${count === 1 ? "question" : "questions"}`;
}

function timestamp(value: string | null | undefined): number {
  if (!value) return 0;
  // Existing naive backend ISO timestamps are UTC, not the browser's local zone.
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const result = Date.parse(normalized);
  return Number.isFinite(result) ? result : 0;
}

export function libraryDate(value: string | null | undefined): string {
  const date = timestamp(value);
  return date ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(date) : "Date unavailable";
}

export function libraryDateTime(value: string | null | undefined): string {
  const date = timestamp(value);
  return date ? new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date) : "Date unavailable";
}

export function duplicateIdentity(document: DocumentItem, documents: DocumentItem[]): string | null {
  const siblings = documents.filter(item => item.filename === document.filename);
  if (siblings.length < 2) return null;
  let length = 6;
  while (length < document.id.length && siblings.some(item => item.id !== document.id && item.id.slice(-length) === document.id.slice(-length))) length++;
  return `Imported ${libraryDateTime(document.upload_date)} · ${document.id.slice(-length)}`;
}

export function continuingDocument(documents: DocumentItem[]): DocumentItem | null {
  return documents.filter(document => canOpenWorkspace(document) &&
    document.review_summary?.can_resume &&
    ["ready", "incomplete"].includes(document.review_summary.status))
    .sort((a, b) => timestamp(b.review_summary?.last_activity_at) - timestamp(a.review_summary?.last_activity_at) || a.id.localeCompare(b.id))[0] || null;
}

/** Close details when their record leaves the visible list; never substitute another. */
export function selectedLibraryDocument(documents: DocumentItem[], selectedId: string): DocumentItem | null {
  return documents.find(document => document.id === selectedId) || null;
}
