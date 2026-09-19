"use client";

import React, { useEffect, useRef } from "react";
import { ChevronRight, FileText, CircleHelp, ArrowLeft } from "lucide-react";
import type { DocumentSourceResponse, ReviewEvidence, ReviewFinding, ReviewMarker, ReviewPersonalState, ReviewRun, SavedReviewQuestion } from "@clauseiq/shared-types";
import { Action, fieldClass, markerLabels } from "./WorkspaceControls";
import { EvidenceSourcePane } from "./EvidenceSourcePane";
import { FindingAsk } from "./FindingAsk";
import { draftKey, type ReviewWorkspaceController, type WorkspaceSaveState } from "./workspaceState";

interface FindingReviewProps {
  run: ReviewRun;
  finding: ReviewFinding;
  personal: ReviewPersonalState;
  state: WorkspaceSaveState;
  controller: ReviewWorkspaceController;
  source: DocumentSourceResponse | null;
  sourceReady: boolean;
  draft: string;
  savedQuestion?: SavedReviewQuestion;
  blocked: boolean;
  selectedEvidence: ReviewEvidence | null;
  showAsk: boolean;
  onFinding: (id: string) => void;
  onSelectEvidence: (evidence: ReviewEvidence) => void;
  onOpenEvidence: (evidence: ReviewEvidence) => void;
  onAskEvidence: (text: string, evidence: ReviewEvidence) => void;
  onShowAsk: () => void;
  onShowEvidence: () => void;
  onSettings: () => void;
}

/** Presentation only: saving, identity and paid requests remain controller-owned. */
export function FindingReview({ run, finding, personal, state, controller, source, sourceReady,
  draft, savedQuestion, blocked, selectedEvidence, showAsk, onFinding, onSelectEvidence,
  onOpenEvidence, onAskEvidence, onShowAsk, onShowEvidence, onSettings }: FindingReviewProps) {
  const askHeading = useRef<HTMLHeadingElement>(null);
  const askButton = useRef<HTMLButtonElement>(null);
  const readingPane = useRef<HTMLDivElement>(null);
  const companionPane = useRef<HTMLElement>(null);
  const index = run.findings.findIndex(item => item.id === finding.id);
  const questionUnchanged = !!savedQuestion && draft === savedQuestion.text;
  const questionConfirmed = questionUnchanged && state.status === "saved" && state.pending === 0;
  const questionStatus = state.status === "failed" ? "Save not confirmed. Keep this page open; your local draft remains here." :
    ["conflict", "review"].includes(state.status) ? "Pending changes need review before this question can be saved." :
    state.status === "loading" ? "Loading saved workspace state…" :
    state.status === "saving" || state.pending > 0 ? "Workspace changes are not yet confirmed. Keep this page open." :
    savedQuestion ? "Draft changed. Your last saved question is retained below." : "Local draft — save to add it to My review.";
  const answerCount = state.workspace?.ask_turns?.filter(turn => turn.run_id === run.id && turn.finding_id === finding.id).length || 0;
  useEffect(() => { if (showAsk) askHeading.current?.focus(); }, [showAsk, finding.id]);
  useEffect(() => { if (readingPane.current) readingPane.current.scrollTop = 0; }, [run.id, finding.id]);
  useEffect(() => { if (companionPane.current) companionPane.current.scrollTop = 0; }, [run.id, finding.id, showAsk]);

  return <div className="cw-findings-layout">
    <aside className="cw-findings-rail" aria-label="Finding navigation">
      <h2>Findings</h2>
      <p className="cw-muted cw-small">{run.findings.length} {run.kind === "fixture" ? "example " : ""}findings · not exhaustive</p>
      <ol className="cw-finding-list">
        {run.findings.map((item, itemIndex) => <li key={item.id}>
          <button type="button" onClick={() => onFinding(item.id)} aria-current={finding.id === item.id ? "true" : undefined}>
            <span className="cw-finding-number" aria-hidden="true">{String(itemIndex + 1).padStart(2, "0")}</span>
            <span className="cw-finding-label"><span>{item.title}</span>
              {personal.markers[item.id] && personal.markers[item.id] !== "not_marked" && <span className="cw-finding-meta">{markerLabels[personal.markers[item.id]]}</span>}
              {personal.saved_questions[item.id] && <span className="cw-finding-meta">Question saved</span>}
              <span className="sr-only"> · {personal.opened_finding_ids.includes(item.id) ? "Opened" : "Not opened"}</span>
            </span>
            <ChevronRight size={18} aria-hidden="true" />
          </button>
        </li>)}
      </ol>
    </aside>

    <div ref={readingPane} className="cw-finding-body">
      <article className="cw-finding-reading" aria-labelledby="selected-finding-title">
        <div className="cw-finding-topline">
          <p className="cw-eyebrow">{run.kind === "fixture" ? "Example finding" : "AI finding"} {String(index + 1).padStart(2, "0")}</p>
          <label><span className="sr-only">My review marker</span><select className="cw-marker" disabled={blocked} value={personal.markers[finding.id] || "not_marked"}
            onChange={event => controller.enqueue({ type: "set_marker", run_id: run.id, finding_id: finding.id, marker: event.target.value as ReviewMarker })}>
            {Object.entries(markerLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
        </div>
        <h2 id="selected-finding-title" className="cw-finding-title">{finding.title}</h2>
        <section className="cw-finding-section cw-facts"><h3>What the agreement says</h3><p>{finding.facts}</p></section>
        <section className="cw-finding-section cw-with-icon"><FileText aria-hidden="true" /><div><h3>Why it matters</h3><p>{finding.interpretation}</p></div></section>
        <section className="cw-finding-section cw-with-icon"><CircleHelp aria-hidden="true" /><div><h3>Still unknown</h3><p>{finding.uncertainty}</p></div></section>
        {finding.basis === "not_found" && <section className="cw-finding-section"><h3>Not found within the reviewed scope</h3><p>{finding.coverage_basis || "No reviewed-scope explanation was supplied."}</p><p className="cw-muted">This is not proof of absence from the original, missing schedules or related documents.</p></section>}
        {finding.basis !== "not_found" && finding.coverage_basis && <section className="cw-finding-section"><h3>Reviewed scope</h3><p>{finding.coverage_basis}</p></section>}
        <details className="cw-finding-details"><summary>Possible next step and marker meaning</summary><p>{finding.next_step}</p><p className="cw-muted cw-small">Your marker is not legal acceptance, a resolved issue or an AI judgement. Opening or saving does not set it.</p></details>
      </article>

      <section className="cw-question" aria-labelledby="keep-question-heading">
        <h2 id="keep-question-heading">Question to keep</h2>
        <label className="sr-only" htmlFor="question-draft">Question draft for {finding.title}</label>
        <textarea id="question-draft" className={fieldClass} rows={4} maxLength={5000} value={draft}
          onChange={event => controller.setDraft(run.id, finding.id, event.target.value)} onBlur={() => controller.flushDrafts()} placeholder="Write a question you want to keep…" />
        <div className="cw-question-actions">
          {questionConfirmed ? <span className="cw-question-saved" role="status">Saved in My review</span> :
            <Action className="cw-primary" disabled={blocked || !draft.trim() || questionUnchanged} onClick={() => controller.saveQuestion(run.id, finding.id, draft)}>{savedQuestion ? "Update saved question" : "Save question"}</Action>}
          <button ref={askButton} type="button" className="cw-ask-action" aria-expanded={showAsk} aria-controls="finding-companion"
            title="Open a separate conversation. Nothing is sent until you choose Send." onClick={onShowAsk}>Ask AI{answerCount ? ` (${answerCount})` : ""}</button>
        </div>
        {!questionConfirmed && <p className="cw-muted cw-small" role="status">{questionStatus}</p>}
        {savedQuestion && draft !== savedQuestion.text && <blockquote className="cw-saved-wording">{savedQuestion.text}</blockquote>}
        {state.status === "review" && personal.drafts[finding.id] !== undefined && personal.drafts[finding.id] !== draft && <div className="cw-draft-conflict"><h3>Latest saved draft from the workspace</h3><p>{personal.drafts[finding.id] || "Empty draft"}</p><p>Your local wording remains above. Apply pending changes only after comparing both.</p></div>}
        <details className="cw-suggestion"><summary>{run.kind === "fixture" ? "Authored example suggestion" : "AI-suggested wording"}</summary><p>{finding.suggested_question}</p><Action onClick={() => controller.setDraft(run.id, finding.id, finding.suggested_question)}>{draft && draft !== finding.suggested_question ? "Replace draft with suggested wording" : "Use suggested wording"}</Action></details>
      </section>
    </div>

    <aside ref={companionPane} className="cw-companion" id="finding-companion" aria-label={showAsk ? "Ask about the selected finding" : "Evidence for the selected finding"}>
      <div hidden={showAsk}><EvidenceSourcePane key={draftKey(run.id, finding.id)} finding={finding} source={source} selectedEvidence={selectedEvidence} onSelect={onSelectEvidence} onOpen={onOpenEvidence} /></div>
      {showAsk && <div className="cw-ask-heading"><button type="button" className="cw-back-action" onClick={() => { onShowEvidence(); askButton.current?.focus(); }}><ArrowLeft size={16} aria-hidden="true" />Back to evidence</button><h2 ref={askHeading} tabIndex={-1}>Ask about this finding</h2><p className="cw-muted cw-small">{finding.title}</p></div>}
      {/* Keep local conversation controls mounted while switching back to evidence. */}
      <div hidden={!showAsk} className="cw-ask-content"><FindingAsk key={draftKey(run.id, finding.id)} run={run} finding={finding} state={state} controller={controller} source={source}
        sourceReady={sourceReady} onEvidence={onAskEvidence} onSettings={onSettings} /></div>
    </aside>
  </div>;
}
