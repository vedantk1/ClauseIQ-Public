"use client";

import React, { useState } from "react";
import type { DocumentSourceResponse, ReviewEvidence, ReviewFinding } from "@clauseiq/shared-types";
import PDFViewer from "@/components/PDFViewer";
import { evidenceMatches } from "./workspaceState";
import { Action, Panel } from "./WorkspaceControls";

export function EvidenceSourcePane({ finding, source, onOpen }: {
  finding: ReviewFinding; source: DocumentSourceResponse | null; onOpen: (evidence: ReviewEvidence) => void;
}) {
  return <Panel>
    <h2 className="text-lg font-semibold">Related evidence</h2>
    <p className="mt-1 text-sm text-text-secondary">Read the rule and its qualifications together. Relationship labels are interpretation, not proof of legal effect.</p>
    <EvidenceList evidence={finding.evidence} source={source} onOpen={onOpen} />
    {!finding.evidence.length && <p className="mt-3 text-sm">No source quotation accompanies this finding. Any not-found claim is limited to its stated reviewed scope, not proof that a term is absent.</p>}
    <p className="mt-3 text-xs text-text-secondary">Matching confirms wording and location—not the finding&apos;s correctness or completeness.</p>
  </Panel>;
}

export function EvidenceList({ evidence, source, onOpen }: {
  evidence: ReviewEvidence[]; source: DocumentSourceResponse | null; onOpen: (evidence: ReviewEvidence) => void;
}) {
  return <div className="mt-4 space-y-4">
      {evidence.map((evidence, index) => {
        const matched = evidenceMatches(evidence, source);
        return <article className="rounded-lg border border-border-muted p-4" key={`${evidence.span_id}-${index}`}>
          <h3 className="font-medium">{evidence.label}</h3>
          <p className="mt-1 text-xs text-text-secondary">Page {evidence.page_number} · {matched ? (evidence.end_span_id ? "Passage matched to source" : "Quote matched to source") : "Quote could not be matched to this source"}</p>
          <blockquote className="my-3 whitespace-pre-wrap break-words border-l-2 border-accent-purple pl-3 text-sm leading-relaxed">{evidence.quote}</blockquote>
          <Action disabled={!matched} onClick={() => onOpen(evidence)}>Read page {evidence.page_number} in the original</Action>
        </article>;
      })}
    </div>;
}

export function DocumentSourceView({ documentId, filename, source, finding, evidence, navigationRequest, onReturn, overviewText }: {
  documentId: string; filename: string; source: DocumentSourceResponse | null;
  finding: ReviewFinding | null; evidence: ReviewEvidence | null;
  navigationRequest: { requestId: number; pageNumber: number } | undefined;
  onReturn: () => void;
  overviewText?: string;
}) {
  const [pageNumber, setPageNumber] = useState(navigationRequest?.pageNumber || 1);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const page = source?.source_extraction?.pages.find(item => item.page_number === pageNumber);
  return <div className="space-y-4">
    {overviewText && <Panel><h2 className="font-semibold">Source context for agreement overview</h2><p className="my-2 text-sm">{overviewText}</p><Action onClick={onReturn}>Return to overview</Action></Panel>}
    {finding && <Panel>
      <p className="text-sm text-text-secondary">Source context for</p>
      <h2 className="mt-1 text-lg font-semibold">{finding.title}</h2>
      <p className="my-2 text-sm">{finding.facts}</p>
      <Action onClick={onReturn}>Return to this finding</Action>
    </Panel>}
    {evidence && evidenceMatches(evidence, source) && <Panel>
      <h3 className="font-semibold">{evidence.label} · page {evidence.page_number}</h3>
      <blockquote className="mt-2 whitespace-pre-wrap text-sm">{evidence.quote}</blockquote>
      <p className="mt-2 text-xs text-text-secondary">{evidence.end_span_id ? "Passage" : "Quote"} matched to extracted source. The PDF opens at the physical page; no guessed highlight is applied.</p>
    </Panel>}
    {navigationError && <p role="alert" className="text-sm">{navigationError}</p>}
    <div className="min-h-[600px]">
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
