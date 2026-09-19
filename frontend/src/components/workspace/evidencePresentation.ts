import type { DocumentSourceResponse, ReviewEvidence } from "@clauseiq/shared-types";
import { evidenceMatches } from "./workspaceState";

const CONTEXT_CHARACTERS = 360;

export type EvidencePresentation = {
  matched: boolean;
  scope: "Saved excerpt" | "Selected passage";
  matchLabel: string;
  context: {
    pageNumber: number;
    before: string;
    quote: string;
    after: string;
    clippedBefore: boolean;
    clippedAfter: boolean;
    fullPage: string;
  } | null;
};

/** A display-only window around exact anchors; never repairs or changes saved evidence. */
export function presentEvidence(evidence: ReviewEvidence, source: DocumentSourceResponse | null): EvidencePresentation {
  const ranged = evidence.end_span_id != null;
  const unmatched: EvidencePresentation = {
    matched: false,
    scope: ranged ? "Selected passage" : "Saved excerpt",
    matchLabel: "Quote could not be matched to this source",
    context: null,
  };
  if (!evidenceMatches(evidence, source)) return unmatched;
  const pages = source!.source_extraction!.pages;
  const matchingPages = pages.filter(page => page.page_number === evidence.page_number);
  if (matchingPages.length !== 1) return unmatched;
  const page = matchingPages[0];
  const first = page.spans.find(span => span.id === evidence.span_id)!;
  const last = ranged ? page.spans.find(span => span.id === evidence.end_span_id)! : first;
  const allSpans = pages.flatMap(item => item.spans);
  // Legacy single-span matches also need unambiguous anchors before we expose nearby text.
  if (allSpans.filter(span => span.id === first.id).length !== 1 ||
      allSpans.filter(span => span.id === last.id).length !== 1 ||
      (!ranged && page.spans.some(span => span !== first && span.start < first.end && span.end > first.start))) {
    return unmatched;
  }
  const characters = Array.from(page.text); // Backend offsets are Unicode code points, not UTF-16 units.
  const start = Math.max(0, first.start - CONTEXT_CHARACTERS);
  const end = Math.min(characters.length, last.end + CONTEXT_CHARACTERS);
  return {
    matched: true,
    scope: unmatched.scope,
    matchLabel: ranged ? "Passage matched to source" : "Quote matched to source",
    context: {
      pageNumber: page.page_number,
      before: characters.slice(start, first.start).join(""),
      quote: evidence.quote,
      after: characters.slice(last.end, end).join(""),
      clippedBefore: start > 0,
      clippedAfter: end < characters.length,
      fullPage: page.text,
    },
  };
}
