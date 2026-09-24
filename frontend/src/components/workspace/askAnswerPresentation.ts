export type AskAnswerPart =
  | { kind: "text"; text: string }
  | { kind: "unlinked-reference"; text: string; number: number };

/**
 * Display-only handling of request-local passage IDs occasionally echoed into prose.
 * Stored evidence keeps exact source anchors, but not these provider-facing IDs.
 * Never guess their association from page numbers, evidence order, or nearby text.
 * Ordinary brackets and unrecognized reference formats remain literal prose.
 */
export function presentAskAnswer(text: string): AskAnswerPart[] {
  const pattern = /\[\s*p[1-9]\d*_b[1-9]\d*_v[1-9]\d*(?:\s*[,;]\s*p[1-9]\d*_b[1-9]\d*_v[1-9]\d*)*\s*\]/g;
  const parts: AskAnswerPart[] = [];
  let end = 0;
  let number = 0;
  for (const match of text.matchAll(pattern)) {
    const start = match.index!;
    if (start > end) parts.push({ kind: "text", text: text.slice(end, start) });
    parts.push({ kind: "unlinked-reference", text: match[0], number: ++number });
    end = start + match[0].length;
  }
  if (end < text.length || !parts.length) parts.push({ kind: "text", text: text.slice(end) });
  return parts;
}
