"use client";

import React, { useState } from "react";
import type { DocumentSourceResponse, ReviewEvidence, ReviewFinding } from "@clauseiq/shared-types";
import PDFViewer from "@/components/PDFViewer";
import { presentEvidence } from "./evidencePresentation";
import styles from "./DocumentWorkspace.module.css";

export interface DocumentWorkspaceProps {
  documentId: string;
  filename: string;
  source: DocumentSourceResponse | null;
  finding: ReviewFinding | null;
  evidence: ReviewEvidence | null;
  navigationRequest: { requestId: number; pageNumber: number; restore?: boolean } | undefined;
  onReturn: () => void;
  overviewText?: string;
  answerText?: string;
  returnLabel?: string;
}

/** Reading fills the workspace; review context and extraction are deliberate side trips. */
export function DocumentWorkspace({ documentId, filename, source, finding, evidence,
  navigationRequest, onReturn, overviewText, answerText, returnLabel }: DocumentWorkspaceProps) {
  const [pageNumber, setPageNumber] = useState(navigationRequest?.pageNumber || 1);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const [showText, setShowText] = useState(false);
  const page = source?.source_extraction?.pages.find(item => item.page_number === pageNumber);
  const presentation = evidence ? presentEvidence(evidence, source) : null;
  // A default selected finding is not a source context for a direct Document-tab visit.
  const hasContext = !!(evidence || overviewText || answerText || returnLabel);
  const contextTitle = overviewText ? "Agreement overview" : answerText ? "Ask answer" : finding?.title || evidence?.label || "Review source";
  const backLabel = returnLabel || (overviewText ? "Return to overview" : "Return to this finding");

  return <section className={styles.workspace} aria-label="Document reader">
    {hasContext && <header className={styles.heading}>
      <button type="button" className={styles.returnButton} onClick={onReturn}>← {backLabel}</button>
      <div className={styles.contextHeading}>
        <h2 title={contextTitle}>{contextTitle}</h2>
      </div>
      <details className={styles.context} onKeyDown={event => {
        if (event.key === "Escape" && event.currentTarget.open) {
          event.currentTarget.open = false;
          event.currentTarget.querySelector("summary")?.focus();
        }
      }}>
      <summary>{evidence ? `Source reference · page ${evidence.page_number}` : "Review context"}</summary>
      <div className={styles.contextBody}>
        {answerText && <><p className={styles.contextLabel}>Ask answer</p><p>{answerText}</p>
          <p className={styles.note}>This answer may cite a passage beyond the finding’s references. A wording match is not legal verification.</p></>}
        {overviewText && <><p className={styles.contextLabel}>Agreement overview</p><p>{overviewText}</p></>}
        {finding && !overviewText && !answerText && <p>{finding.facts}</p>}
        {evidence && presentation && <>
          <p className={styles.contextLabel}>{evidence.label} · page {evidence.page_number}</p>
          <blockquote>{evidence.quote}</blockquote>
          <p className={styles.note}>{presentation.matchLabel}. {presentation.scope}; may begin or end mid-clause.</p>
          <p className={styles.note}>The original opens at the physical page. No guessed highlight is applied.</p>
        </>}
      </div>
      </details>
    </header>}
    {navigationError && <p role="alert" className={styles.navigationError}>{navigationError}</p>}
    <div className={`${styles.readingArea}${showText ? ` ${styles.withText}` : ""}`}>
      <div className={styles.pdfPane}>
        <PDFViewer key={`${documentId}:${source?.source_revision_id || "pending"}`} rememberView documentId={documentId} fileName={filename} sourceRevisionId={source?.source_revision_id || undefined}
          toolbarActions={<button type="button" className={styles.textToggle} aria-expanded={showText} aria-controls="document-extracted-text"
            onClick={() => setShowText(value => !value)}>{showText ? "Hide extracted text" : "Extracted text"}</button>}
          navigationRequest={navigationRequest} onPageChange={page => { setPageNumber(page); setNavigationError(null); }}
          onNavigationError={setNavigationError} />
      </div>
      {showText && <aside className={styles.extraction} id="document-extracted-text" aria-label={`Extracted text on page ${pageNumber}`}>
        <div className={styles.extractionHeading}><div><p className={styles.eyebrow}>Extraction</p><h3>Page {pageNumber}</h3></div>
          <button type="button" title="Close extracted text" aria-label="Close extracted text" onClick={() => setShowText(false)}>×</button>
        </div>
        <p className={styles.note}>Saved extraction output, not the PDF layout. Wording and reading order can differ.</p>
        <div className={styles.extractionText}>{page?.text || "No extracted text is available on this page."}</div>
      </aside>}
    </div>
  </section>;
}
