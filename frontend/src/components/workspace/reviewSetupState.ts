import type { DocumentSourceResponse } from "@clauseiq/shared-types";

/** Setup describes source readiness, never whether the agreement is safe. */
export function reviewSetupSource(source: DocumentSourceResponse | null, documentId: string, sourceRevisionId: string, error: string | null) {
  const snapshot = source?.source_extraction;
  const extracted = snapshot?.pages.filter(page => page.status === "extracted").length || 0;
  const missing = snapshot?.pages.filter(page => page.status !== "extracted") || [];
  const base = { canReview: false, pageCount: snapshot?.page_count ?? null, extracted, missing, limited: false };
  if (error) return { ...base, title: "Source details unavailable", message: "The saved source could not be loaded. You can still open the original; reload the workspace before starting a review." };
  if (!source) return { ...base, title: "Loading source details…", message: "Checking the saved original and extracted text." };
  if (source.id !== documentId || source.source_revision_id !== sourceRevisionId) return { ...base, title: "Source identity mismatch", message: "These source details do not match this workspace. No review can start with this snapshot." };
  if (source.source_status !== "stored") return { ...base, title: "Original storage not confirmed", message: "The original must be stored before a review can start. Check its document record in the Library." };
  if (source.extraction_status === "failed") return { ...base, title: "Text extraction failed", message: "The original remains saved, but usable text has not been confirmed. Inspect the saved record and original before attempting recovery; this screen cannot retry extraction." };
  if (["pending", "processing"].includes(source.extraction_status || "")) return { ...base, title: "Preparing source text", message: "Local text extraction has not finished. No AI review is running." };
  if (!snapshot || !extracted || !snapshot.text.trim()) return { ...base, title: "No usable source text", message: "No usable text is available for AI review. You can still inspect the original. Scanned pages are not automatically converted with OCR." };
  const status = source.extraction_status;
  if (!["complete", "partial"].includes(status || "") || !["complete", "partial"].includes(snapshot.status)) return { ...base, title: "Source text not ready", message: "The source state needs attention before a review can start. Inspect the original and source details." };
  const limited = missing.length > 0 || status === "partial" || snapshot.status === "partial";
  return { ...base, canReview: true, limited,
    title: limited ? "Some source text is missing" : "Source text extracted",
    message: limited ? "A review can use only the extracted text. Missing pages may contain important conditions; they are not evidence that no issue exists." : "Text extraction is complete. This is not an AI review or a check of the agreement’s terms.",
  };
}
