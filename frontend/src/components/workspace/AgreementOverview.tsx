import React from "react";
import { ArrowRight, BookOpen, FileText } from "lucide-react";
import type { DocumentSourceResponse, ReviewEvidence, ReviewPersonalState, ReviewRun } from "@clauseiq/shared-types";
import { Action } from "./WorkspaceControls";
import { EvidenceList } from "./EvidenceSourcePane";
import { evidenceMatches, runStatus } from "./workspaceState";
import styles from "./WorkspaceSummaries.module.css";

export interface AgreementOverviewProps {
  run: ReviewRun;
  personal: ReviewPersonalState;
  source: DocumentSourceResponse | null;
  sourceLoading?: boolean;
  sourceError?: string | null;
  onFinding: (findingId: string) => void;
  onSource: (text: string, evidence: ReviewEvidence) => void;
  onOriginal: () => void;
  onExplore: () => void;
  onResume: () => void;
  onMyReview?: () => void;
  children?: React.ReactNode;
  controlsOpen?: boolean;
}

const viewNames = { overview: "Overview", findings: "Findings", document: "Document", my_review: "My review" };
const perspectiveNames = { neutral: "Neutral", customer: "Customer", provider: "Provider", other: "Other role" };

/** Saved agreement output leads; preparing another paid run stays secondary. */
export function AgreementOverview({ run, personal, source, sourceLoading = false, sourceError = null,
  onFinding, onSource, onOriginal, onExplore, onResume, onMyReview, children, controlsOpen = false,
}: AgreementOverviewProps) {
  const status = runStatus(run);
  const hasOutput = status === "ready" || status === "incomplete";
  const matchingSource = !sourceLoading && !sourceError && source?.source_revision_id === run.source_revision_id ? source : null;
  const extraction = matchingSource?.source_extraction;
  const pages = extraction?.pages || [];
  const extracted = pages.filter(page => page.status === "extracted").length;
  const missing = pages.filter(page => page.status !== "extracted");
  const findingIds = new Set(run.findings.map(finding => finding.id));
  const saved = Object.keys(personal.saved_questions).filter(id => findingIds.has(id));
  const opened = new Set(personal.opened_finding_ids.filter(id => findingIds.has(id))).size;
  const revisits = run.findings.filter(finding => personal.markers[finding.id] === "revisit");
  const resumeFinding = run.findings.find(finding => finding.id === personal.position.finding_id);
  const emptyMessage = status === "processing" ? "This review is still processing. No final agreement summary is available yet."
    : status === "failed" ? "No usable agreement summary was completed for this run. Your original and earlier saved runs remain available."
    : status === "interrupted" ? "This run was interrupted. No final agreement summary is available; it will not restart automatically."
    : "No usable overview is available in this run. Check its status and source limitations before using any findings.";

  return <div className={styles.summaries}>
    <header className="co-heading">
      <div><p className="co-eyebrow">{run.kind === "fixture" ? "Authored synthetic example" : "Saved AI review"}</p>
        <h2>Agreement overview</h2><p>{perspectiveNames[run.context.perspective]} perspective{run.context.role ? ` · ${run.context.role}` : ""} — the context saved with this run.</p>
      </div>
      <Action className="co-secondary-action" onClick={onOriginal}><FileText size={17} aria-hidden="true" />Open original</Action>
    </header>

    <div className="co-overview-grid">
      <section className="co-agreement-summary" aria-label="Agreement summary">
        {hasOutput && run.overview_items?.length ? <div className="co-summary-items">{run.overview_items.map((item, index) => <article key={index}>
          <p className="co-reading">{item.text}</p>
          <details className="co-overview-evidence"><summary>Supporting source · {item.evidence.length} {item.evidence.length === 1 ? "reference" : "references"}</summary>
            <EvidenceList evidence={item.evidence} source={matchingSource} onOpen={evidence => {
              if (evidence.source_revision_id === run.source_revision_id && evidenceMatches(evidence, matchingSource)) onSource(item.text, evidence);
            }} />
          </details>
        </article>)}</div> : <p className="co-reading">{hasOutput && run.overview ? run.overview : emptyMessage}</p>}
        <div className="co-findings-next">
          <div><h3>{hasOutput ? "Look closer at the findings" : "Check this run’s status"}</h3>
            <p>{hasOutput ? `${run.findings.length} ${run.kind === "fixture" ? "example " : ""}findings in this run. This is not a complete inventory of the agreement’s risks.` : "A missing result is not a finding that the agreement has no issues."}</p>
          </div>
          {hasOutput && <Action className="co-primary-action" onClick={onExplore}>Explore findings<ArrowRight size={17} aria-hidden="true" /></Action>}
        </div>
      </section>

      <aside className="co-activity" aria-labelledby="review-activity-heading">
        <h3 id="review-activity-heading">Your review activity</h3>
        <p className="co-activity-counts">{opened} opened · {revisits.length} to revisit · {saved.length} saved questions</p>
        <p className="co-note">Personal activity, not review completeness.</p>
        {hasOutput && <div className="co-resume"><p>Saved position: {viewNames[personal.position.view]}{resumeFinding ? ` — ${resumeFinding.title}` : ""}</p>
          <Action onClick={onResume}>Continue from saved position<ArrowRight size={16} aria-hidden="true" /></Action>
        </div>}
        {revisits.length > 0 && <div className="co-revisit"><h4>Left for later</h4><ul>{revisits.map(finding => <li key={finding.id}><button type="button" onClick={() => onFinding(finding.id)}>{finding.title}<ArrowRight size={15} aria-hidden="true" /></button></li>)}</ul></div>}
        {onMyReview && <button type="button" className="co-text-action" onClick={onMyReview}><BookOpen size={16} aria-hidden="true" />Open My review</button>}
      </aside>
    </div>

    <section className="co-source-coverage" aria-labelledby="overview-source-heading">
      <div className="co-section-heading"><h3 id="overview-source-heading">Source and coverage</h3><span className="co-note">Text supplied is not proof that every provision was understood.</span></div>
      {sourceLoading ? <p role="status">Loading source details…</p>
        : sourceError ? <p role="alert">Source details could not be loaded. Use the source recovery controls above to retry; saved review work remains unchanged.</p>
        : !matchingSource ? <p role="alert">Source details are unavailable or do not match this run. Evidence cannot be checked against them.</p>
        : !extraction ? <p>No page-aware source snapshot is available. The original PDF and extraction status are separate from the review.</p>
        : <p>{extracted} of {extraction.page_count} source pages have extracted text.</p>}
      {missing.length > 0 && <p className="co-limitation">Extraction limitations on pages {missing.map(page => `${page.page_number} (${page.status === "empty" ? "no extractable text" : "extraction failed"})`).join(", ")}. No OCR is performed.</p>}
      {run.coverage && <>
        <p>Saved run input: {run.coverage.extracted_pages.length} of {run.coverage.page_count} pages.</p>
        {run.coverage.omitted_pages.length > 0 && <p className="co-limitation">Pages omitted from this review: {run.coverage.omitted_pages.join(", ")}.</p>}
        {run.coverage.limitations.length > 0 && <ul className="co-limitations">{run.coverage.limitations.map((limitation, index) => <li key={index}>{limitation}</li>)}</ul>}
        <details className="co-source-details"><summary>Pages supplied to this run</summary><p>{run.coverage.extracted_pages.join(", ") || "None"}</p></details>
      </>}
      <details className="co-source-details"><summary>Source identity</summary><dl><dt>Run source revision</dt><dd>{run.source_revision_id}</dd><dt>SHA-256</dt><dd>{matchingSource?.source_sha256 || "Unavailable"}</dd><dt>Extractor</dt><dd>{extraction?.extraction_version || "Unavailable"}</dd></dl></details>
    </section>

    {children && <details className="co-review-controls" open={controlsOpen}>
      <summary><span>Review brief and another run</span><span>Changing the brief does not update these saved findings.</span></summary>
      <div className="co-review-controls-content">{children}</div>
    </details>}
  </div>;
}
