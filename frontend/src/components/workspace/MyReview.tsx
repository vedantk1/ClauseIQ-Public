import React from "react";
import { ArrowRight, FileText } from "lucide-react";
import type { DocumentSourceResponse, ReviewEvidence, ReviewPersonalState, ReviewRun } from "@clauseiq/shared-types";
import { Action, markerLabels } from "./WorkspaceControls";
import { evidenceMatches } from "./workspaceState";
import styles from "./WorkspaceSummaries.module.css";

export interface MyReviewProps {
  run: ReviewRun | null;
  personal: ReviewPersonalState;
  source: DocumentSourceResponse | null;
  onFinding: (findingId: string) => void;
  onSource: (findingId: string, evidence: ReviewEvidence) => void;
  onExplore: () => void;
}

/** Confirmed questions only. Drafts and provider answers are not personal saves. */
export function MyReview({ run, personal, source, onFinding, onSource, onExplore }: MyReviewProps) {
  const findings = run?.findings || [];
  const saved = findings.filter(finding => personal.saved_questions[finding.id]);
  const revisits = findings.filter(finding => personal.markers[finding.id] === "revisit");
  const reviewed = findings.filter(finding => personal.markers[finding.id] === "reviewed_by_me");
  const matchingSource = source?.source_revision_id === run?.source_revision_id ? source : null;
  return <div className={styles.summaries}>
    <header className="co-heading"><div><p className="co-eyebrow">Your saved work · selected run only</p><h2>My review</h2>
      <p>Questions you deliberately saved, alongside your personal markers. Saving does not send a message, accept a term or resolve a finding.</p>
    </div><Action className="co-secondary-action" onClick={onExplore}>{run ? "Explore findings" : "Open review setup"}<ArrowRight size={17} aria-hidden="true" /></Action></header>
    <div className="co-personal-grid">
      <section aria-labelledby="saved-questions-heading" className="co-saved-questions">
        <div className="co-section-heading"><h3 id="saved-questions-heading">Saved questions</h3><span className="co-note">{saved.length} confirmed {saved.length === 1 ? "question" : "questions"}</span></div>
        {saved.length ? <div className="co-question-list">{saved.map(finding => {
          const question = personal.saved_questions[finding.id];
          return <article key={`${run?.id}:${finding.id}`} className="co-question-card">
            <div className="co-question-context"><h4>{finding.title}</h4><span className="co-marker-label">{markerLabels[personal.markers[finding.id] || "not_marked"]}</span></div>
            <p className="co-question-wording">{question.text}</p>
            <Action onClick={() => onFinding(finding.id)}>Return to finding and edit<ArrowRight size={16} aria-hidden="true" /></Action>
            {finding.evidence.length > 0 ? <details className="co-question-sources"><summary>Finding source · {finding.evidence.length} {finding.evidence.length === 1 ? "reference" : "references"}</summary>
              <p className="co-note">These references accompany the finding; they do not verify your question or its interpretation.</p>
              <ul>{finding.evidence.map((evidence, index) => {
                const matched = evidence.source_revision_id === run?.source_revision_id && evidenceMatches(evidence, matchingSource);
                return <li key={`${evidence.span_id}:${index}`}><button type="button" disabled={!matched} onClick={() => { if (matched) onSource(finding.id, evidence); }}>
                  <FileText size={17} aria-hidden="true" /><span>{evidence.label}<span className="co-reference-page">Page {evidence.page_number}{matched ? " · Open source" : " · Source not matched"}</span></span><ArrowRight size={16} aria-hidden="true" />
                </button></li>;
              })}</ul>
            </details> : <p className="co-note">No source reference accompanies this finding. A not-found claim is limited to the recorded review scope.</p>}
          </article>;
        })}</div> : <div className="co-empty"><h4>{run ? "No saved questions in this run" : "No review run yet"}</h4><p>{run ? "Open a finding, write a question you want to keep, and save it. Recoverable drafts stay separate until you deliberately save." : "Start from review setup. Once a run is available, you can keep questions and mark findings for later."}</p></div>}
      </section>
      <aside className="co-personal-markers" aria-labelledby="personal-markers-heading"><h3 id="personal-markers-heading">Personal markers</h3><p className="co-note">Markers describe your activity, not legal safety or review completeness.</p>
        {([['Revisit', revisits], ['Reviewed by me', reviewed]] as const).map(([title, items]) => <section className="co-marker-group" key={title}><h4>{title}<span>{items.length}</span></h4>
          {items.length ? <ul>{items.map(finding => <li key={finding.id}><button type="button" onClick={() => onFinding(finding.id)}>{finding.title}<ArrowRight size={15} aria-hidden="true" /></button></li>)}</ul> : <p className="co-note">Nothing marked here in this run.</p>}
        </section>)}
      </aside>
    </div>
  </div>;
}
