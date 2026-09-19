"use client";

import React, { useEffect, useRef, useState } from "react";
import { ChevronRight, FileText, Info } from "lucide-react";
import type { DocumentSourceResponse, ReviewEvidence, ReviewFinding } from "@clauseiq/shared-types";
import PDFViewer from "@/components/PDFViewer";
import { presentEvidence, type EvidencePresentation } from "./evidencePresentation";
import { Action, Panel } from "./WorkspaceControls";

function sameEvidenceReference(left: ReviewEvidence, right: ReviewEvidence) {
  return left.source_revision_id === right.source_revision_id && left.span_id === right.span_id &&
    left.end_span_id === right.end_span_id && left.page_number === right.page_number &&
    left.quote === right.quote && left.label === right.label;
}

function evidenceContextKey(evidence: ReviewEvidence) {
  return JSON.stringify([evidence.source_revision_id, evidence.page_number, evidence.span_id,
    evidence.end_span_id, evidence.quote, evidence.label]);
}

function SourceContext({ presentation }: { presentation: EvidencePresentation }) {
  const context = presentation.context;
  if (!context) return null;
  return <details className="cw-evidence-context">
    <summary>Inspect surrounding text · page {context.pageNumber}</summary>
    <p className="cw-evidence-context-note">Extracted source text, with the saved quotation marked. Surrounding text is not added to this citation and may not show a full clause; qualifications may be on other pages.</p>
    {context.clippedBefore && <p className="cw-evidence-context-boundary">Earlier text on this page is outside this window.</p>}
    <p className="cw-evidence-context-text whitespace-pre-wrap break-words">{context.before}<mark className="cw-evidence-context-match">{context.quote}</mark>{context.after}</p>
    {context.clippedAfter && <p className="cw-evidence-context-boundary">Later text on this page is outside this window.</p>}
    {(context.clippedBefore || context.clippedAfter) && <details className="cw-evidence-full-page">
      <summary>View full extracted page {context.pageNumber}</summary>
      <p className="cw-evidence-context-note">Extraction output, not a reproduction of the PDF layout.</p>
      <p className="cw-evidence-context-text whitespace-pre-wrap break-words">{context.fullPage}</p>
    </details>}
  </details>;
}

export function EvidenceSourcePane({ finding, source, onOpen, selectedEvidence, onSelect }: {
  finding: ReviewFinding; source: DocumentSourceResponse | null; onOpen: (evidence: ReviewEvidence) => void;
  selectedEvidence?: ReviewEvidence | null; onSelect?: (evidence: ReviewEvidence) => void;
}) {
  const [localSelection, setLocalSelection] = useState<{ findingId: string; evidence: ReviewEvidence } | null>(null);
  const detailHeading = useRef<HTMLHeadingElement>(null);
  const pendingFocus = useRef<{ findingId: string; evidence: ReviewEvidence } | null>(null);
  const requested = selectedEvidence === undefined
    ? (localSelection?.findingId === finding.id ? localSelection.evidence : null)
    : selectedEvidence;
  // Only display an exact reference from this finding; stale selections never supply their own quote.
  const selected = finding.evidence.find(item => item === requested) ||
    (requested && finding.evidence.find(item => sameEvidenceReference(item, requested))) || finding.evidence[0] || null;
  useEffect(() => {
    const intent = pendingFocus.current;
    if (!intent) return; // Loading, resume and externally selected evidence never move focus.
    if (intent.findingId !== finding.id || !finding.evidence.includes(intent.evidence)) {
      pendingFocus.current = null;
      return;
    }
    if (selected !== intent.evidence) return; // A controlled selection must be displayed first.
    pendingFocus.current = null;
    detailHeading.current?.focus({ preventScroll: true });
    detailHeading.current?.scrollIntoView({ block: "nearest" });
  }, [finding.id, finding.evidence, selected, localSelection]);
  const presentation = selected ? presentEvidence(selected, source) : null;
  return <section className="cw-evidence-pane" aria-label="Related evidence">
    <h2 className="cw-evidence-heading">Related evidence</h2>
    {selected && presentation ? <article className="cw-evidence-detail">
      <h3 ref={detailHeading} tabIndex={-1} className="cw-evidence-detail-heading">{selected.label} · page {selected.page_number}</h3>
      <p className="cw-evidence-scope">{presentation.scope} · may begin or end mid-clause</p>
      <blockquote className="cw-evidence-quote whitespace-pre-wrap break-words">{selected.quote}</blockquote>
      <p className={`cw-evidence-match${presentation.matched ? "" : " cw-evidence-match-warning"}`}>
        {presentation.matchLabel}
      </p>
      <Action className="cw-evidence-open" disabled={!presentation.matched} onClick={() => onOpen(selected)}>
        Open original · page {selected.page_number}
      </Action>
      <SourceContext key={`${finding.id}-${finding.evidence.indexOf(selected)}-${evidenceContextKey(selected)}`} presentation={presentation} />
    </article> : <p className="cw-evidence-empty">No source quotation accompanies this finding. Any not-found claim is limited to its stated reviewed scope, not proof that a term is absent.</p>}
    {!!finding.evidence.length && <h3 className="cw-evidence-references-heading">References ({finding.evidence.length})</h3>}
    {!!finding.evidence.length && <ul className="cw-evidence-list" aria-label="Evidence references">
      {finding.evidence.map((evidence, index) => <li key={`${evidence.span_id}-${index}`}>
        <button type="button" className="cw-evidence-selector" aria-pressed={selected === evidence}
          onClick={() => {
            const intent = { findingId: finding.id, evidence };
            pendingFocus.current = intent;
            setLocalSelection(intent);
            onSelect?.(evidence);
          }}>
          <FileText className="cw-evidence-icon" size={19} aria-hidden="true" />
          <span className="cw-evidence-reference">
            <span className="cw-evidence-label">{evidence.label}</span>
            <span className="cw-evidence-page">Page {evidence.page_number}</span>
            {!presentEvidence(evidence, source).matched && <span className="cw-evidence-unmatched">Source not matched</span>}
          </span>
          <ChevronRight className="cw-evidence-chevron" size={18} aria-hidden="true" />
        </button>
      </li>)}
    </ul>}
    <div className="cw-evidence-disclaimer">
      <Info size={19} aria-hidden="true" />
      <p>Matching confirms wording and location—not the finding&apos;s correctness or completeness. Read the rule and its qualifications together; relationship labels are interpretation, not proof of legal effect.</p>
    </div>
  </section>;
}

export function EvidenceList({ evidence, source, onOpen }: {
  evidence: ReviewEvidence[]; source: DocumentSourceResponse | null; onOpen: (evidence: ReviewEvidence) => void;
}) {
  return <div className="mt-4 space-y-4">
      {evidence.map((evidence, index) => {
        const presentation = presentEvidence(evidence, source);
        return <article className="rounded-lg border border-border-muted p-4" key={`${evidence.span_id}-${index}`}>
          <h3 className="font-medium">{evidence.label}</h3>
          <p className="mt-1 text-xs text-text-secondary">Page {evidence.page_number} · {presentation.matchLabel}</p>
          <p className="cw-evidence-scope">{presentation.scope} · may begin or end mid-clause</p>
          <blockquote className="my-3 whitespace-pre-wrap break-words border-l-2 border-accent-purple pl-3 text-sm leading-relaxed">{evidence.quote}</blockquote>
          <Action disabled={!presentation.matched} onClick={() => onOpen(evidence)}>Read page {evidence.page_number} in the original</Action>
          <SourceContext key={evidenceContextKey(evidence)} presentation={presentation} />
        </article>;
      })}
    </div>;
}

export function DocumentSourceView({ documentId, filename, source, finding, evidence, navigationRequest, onReturn, overviewText, answerText, returnLabel }: {
  documentId: string; filename: string; source: DocumentSourceResponse | null;
  finding: ReviewFinding | null; evidence: ReviewEvidence | null;
  navigationRequest: { requestId: number; pageNumber: number } | undefined;
  onReturn: () => void;
  overviewText?: string;
  answerText?: string;
  returnLabel?: string;
}) {
  const [pageNumber, setPageNumber] = useState(navigationRequest?.pageNumber || 1);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const page = source?.source_extraction?.pages.find(item => item.page_number === pageNumber);
  const presentation = evidence ? presentEvidence(evidence, source) : null;
  return <div className="space-y-4">
    {answerText && <Panel><h2 className="font-semibold">Source context for Ask answer</h2><p className="mt-2 whitespace-pre-wrap text-sm">{answerText}</p><p className="mt-2 text-xs text-text-secondary">This AI answer may cite a passage beyond the original finding&apos;s evidence. Matching is not legal verification.</p></Panel>}
    {overviewText && <Panel><h2 className="font-semibold">Source context for agreement overview</h2><p className="my-2 text-sm">{overviewText}</p><Action onClick={onReturn}>Return to overview</Action></Panel>}
    {finding && <Panel>
      <p className="text-sm text-text-secondary">Source context for</p>
      <h2 className="mt-1 text-lg font-semibold">{finding.title}</h2>
      <p className="my-2 text-sm">{finding.facts}</p>
      <Action onClick={onReturn}>{returnLabel || "Return to this finding"}</Action>
    </Panel>}
    {evidence && presentation?.matched && <Panel>
      <h3 className="font-semibold">{evidence.label} · page {evidence.page_number}</h3>
      <p className="cw-evidence-scope">{presentation.scope} · may begin or end mid-clause</p>
      <blockquote className="mt-2 whitespace-pre-wrap text-sm">{evidence.quote}</blockquote>
      <p className="mt-2 text-xs text-text-secondary">{evidence.end_span_id ? "Passage" : "Quote"} matched to extracted source. The PDF opens at the physical page; no guessed highlight is applied.</p>
      <SourceContext key={evidenceContextKey(evidence)} presentation={presentation} />
    </Panel>}
    {navigationError && <p role="alert" className="text-sm">{navigationError}</p>}
    {/* A definite height lets the PDF viewer scroll internally instead of growing with every page. */}
    <div className="h-[75vh] min-h-[360px] max-h-[900px] overflow-hidden">
      <PDFViewer documentId={documentId} fileName={filename} sourceRevisionId={source?.source_revision_id || undefined}
        navigationRequest={navigationRequest} onPageChange={setPageNumber} onNavigationError={setNavigationError} />
    </div>
    <details className="rounded-lg border border-border-muted bg-bg-surface p-4">
      <summary className="cursor-pointer font-medium">Extracted text on page {pageNumber}</summary>
      <p className="mt-2 text-xs text-text-secondary">This is extraction output, not a reproduction of the PDF layout.</p>
      <p className="mt-3 whitespace-pre-wrap break-words text-sm">{page?.text || "No extracted text is available on this page."}</p>
    </details>
  </div>;
}
