import type { ReviewAskInlineCitation, ReviewEvidence } from "@clauseiq/shared-types";

export type AskAnswerPart =
  | { kind: "text"; text: string }
  | { kind: "linked-reference"; text: string; number: number; evidence: ReviewEvidence }
  | { kind: "unlinked-reference"; text: string; number: number };

/**
 * Display-only handling of request-local IDs with a server-validated association.
 * Historical or malformed mappings remain unlinked. Never guess an association
 * from page numbers, evidence order, another paragraph, or nearby text.
 * Ordinary brackets and unrecognized reference formats remain literal prose.
 */
export function presentAskAnswer(text: string, evidence: ReviewEvidence[] = [], citations: ReviewAskInlineCitation[] = []): AskAnswerPart[] {
  const pattern = /\[\s*p[1-9]\d*_b[1-9]\d*_v[1-9]\d*(?:\s*[,;]\s*p[1-9]\d*_b[1-9]\d*_v[1-9]\d*)*\s*\]/g;
  const valid = Array.isArray(citations) && citations.length <= 10 && citations.every(citation =>
    citation && typeof citation.passage_id === "string" && citation.passage_id.length <= 128 &&
    /^p[1-9]\d*_b[1-9]\d*_v[1-9]\d*$/.test(citation.passage_id) && Number.isInteger(citation.evidence_index) &&
    citation.evidence_index >= 0 && citation.evidence_index < 10 && citation.evidence_index < evidence.length &&
    !!evidence[citation.evidence_index]) &&
    new Set(citations.map(citation => citation.passage_id)).size === citations.length &&
    new Set(citations.map(citation => citation.evidence_index)).size === citations.length;
  const links = new Map(valid ? citations.map(citation => [citation.passage_id, citation.evidence_index]) : []);
  const parts: AskAnswerPart[] = [];
  let end = 0;
  let number = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index!;
    if (start > end) parts.push({ kind: "text", text: text.slice(end, start) });
    const ids = [...match[0].matchAll(/p[1-9]\d*_b[1-9]\d*_v[1-9]\d*/g)];
    if (!ids.some(id => links.has(id[0]))) {
      parts.push({ kind: "unlinked-reference", text: match[0], number: ++number });
    } else {
      let groupEnd = 0;
      for (const id of ids) {
        const offset = id.index!;
        if (offset > groupEnd) parts.push({ kind: "text", text: match[0].slice(groupEnd, offset) });
        const index = links.get(id[0]);
        parts.push(index === undefined
          ? { kind: "unlinked-reference", text: id[0], number: ++number }
          : { kind: "linked-reference", text: id[0], number: index + 1, evidence: evidence[index] });
        groupEnd = offset + id[0].length;
      }
      if (groupEnd < match[0].length) parts.push({ kind: "text", text: match[0].slice(groupEnd) });
    }
    end = start + match[0].length;
  }
  if (end < text.length || !parts.length) parts.push({ kind: "text", text: text.slice(end) });
  return parts;
}
