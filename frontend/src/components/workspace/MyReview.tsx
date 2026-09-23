"use client";

import React, { useState } from "react";
import { ArrowRight, FileText } from "lucide-react";
import type { DocumentSourceResponse, ReviewEvidence, ReviewMarker, ReviewPersonalState, ReviewRun } from "@clauseiq/shared-types";
import Modal from "@/components/ui/Modal";
import { Action, markerLabels } from "./WorkspaceControls";
import { draftKey, evidenceMatches, paidActionBusy, type ReviewWorkspaceController, type WorkspaceSaveState } from "./workspaceState";
import { ReviewBriefExport } from "./ReviewBriefExport";
import styles from "./MyReview.module.css";

export interface MyReviewProps {
  filename?: string; exportUnavailable?: string;
  run: ReviewRun | null; personal: ReviewPersonalState; source: DocumentSourceResponse | null;
  state?: WorkspaceSaveState; controller?: ReviewWorkspaceController;
  onFinding: (findingId: string) => void;
  onSource: (findingId: string, evidence: ReviewEvidence) => void;
  onExplore: () => void;
}

/** Filters change presentation only; exports still receive the complete confirmed run. */
export function MyReview({ filename = "Agreement", exportUnavailable, run, personal, source, state, controller, onFinding, onSource, onExplore }: MyReviewProps) {
  const [filter, setFilter] = useState<"work" | "all" | "revisit" | "saved">("work");
  const [editing, setEditing] = useState<string | null>(null);
  const [removing, setRemoving] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const findings = run?.findings || [];
  const saved = findings.filter(finding => personal.saved_questions[finding.id]);
  const revisits = findings.filter(finding => personal.markers[finding.id] === "revisit");
  const work = findings.filter(finding => personal.saved_questions[finding.id] || personal.markers[finding.id] && personal.markers[finding.id] !== "not_marked");
  const visible = filter === "work" ? work : filter === "saved" ? saved : filter === "revisit" ? revisits : findings;
  const matchingSource = source?.source_revision_id === run?.source_revision_id ? source : null;
  const processing = state?.workspace?.runs.some(item => item.status === "processing") || state?.workspace?.ask_turns?.some(item => item.status === "processing");
  const blocked = !state || !controller || state.status !== "saved" || state.pending > 0 || paidActionBusy(state) || !!processing;
  const editBlocked = !state || !controller || ["loading", "failed", "conflict", "review"].includes(state.status) || paidActionBusy(state) || !!processing;
  const removal = findings.find(finding => finding.id === removing && personal.saved_questions[finding.id]);

  return <div className={styles.review}>
    <header className="mr-heading"><div><h2>My review</h2>
      <p>Questions and personal markers · selected run only.</p>
    </div><Action onClick={onExplore}>{run ? "Explore findings" : "Open review setup"}<ArrowRight size={16} aria-hidden="true" /></Action></header>
    <div className="mr-toolbar">
      <div className="mr-filters" role="group" aria-label="Filter review checklist">
        {([['work', 'Saved work', work.length], ['all', 'All findings', findings.length], ['revisit', 'Revisit', revisits.length], ['saved', 'Saved questions', saved.length]] as const).map(([value, label, count]) =>
          <button key={value} type="button" aria-pressed={filter === value} onClick={() => { setFilter(value); setEditing(null); setFeedback(""); }}>{label}<span>{count}</span></button>)}
      </div>
      <ReviewBriefExport key={run?.id || "no-run"} compact filename={filename} run={run} personal={personal} source={source} unavailable={exportUnavailable} />
    </div>
    <details className="mr-summary"><summary>About saved work and export</summary><p>{saved.length} confirmed {saved.length === 1 ? "question" : "questions"}; {revisits.length} to revisit. Markers are personal activity, not legal safety or completeness. Saving never sends a message, accepts a term or resolves a finding. Export ignores filters.</p></details>
    {feedback && <p className="mr-feedback" role="status">{feedback}</p>}
    {state && blocked && <p className="mr-feedback" role="status">Finish saving or resolve pending changes above before changing saved questions or markers. Your draft stays available.</p>}
    {run && !saved.length && <p className="mr-empty-note">No saved questions in this run. Recoverable drafts stay separate until you deliberately save.</p>}
    {visible.length ? <ol className="mr-list" aria-label="Review checklist">{visible.map(finding => {
      const question = personal.saved_questions[finding.id];
      const isEditing = editing === finding.id;
      const draft = state?.localDrafts[draftKey(run!.id, finding.id)] ?? personal.drafts[finding.id] ?? question?.text ?? "";
      return <li key={finding.id} className={`mr-item${!question && !isEditing ? " mr-item-compact" : ""}`}>
        <div className="mr-item-heading"><h3><button type="button" onClick={() => onFinding(finding.id)}>{finding.title}<ArrowRight size={15} aria-hidden="true" /></button></h3>
          <label className="mr-marker"><span className="sr-only">Marker for {finding.title}</span><select value={personal.markers[finding.id] || "not_marked"} disabled={blocked}
            onChange={event => { if (!blocked && run && Object.hasOwn(markerLabels, event.target.value)) controller!.enqueue({ type: "set_marker", run_id: run.id, finding_id: finding.id, marker: event.target.value as ReviewMarker }); }}>
            {Object.entries(markerLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
        </div>
        {question && <p className="mr-question">{question.text}</p>}
        {isEditing && <div className="mr-editor">
          <label>Question draft for {finding.title}<textarea autoFocus rows={3} maxLength={5000} value={draft} readOnly={editBlocked}
            onChange={event => { if (!editBlocked && run) controller!.setDraft(run.id, finding.id, event.target.value); }} onBlur={() => controller?.flushDrafts()} /></label>
          <p className="mr-muted">Drafts are kept for recovery. Only Save question changes your confirmed question and exported brief.</p>
          {state?.status === "review" && personal.drafts[finding.id] !== undefined && personal.drafts[finding.id] !== draft && <div className="mr-recovery"><strong>Latest saved draft</strong><p>{personal.drafts[finding.id] || "Empty draft"}</p><p>Compare with your local wording before applying pending changes above.</p></div>}
          <div className="mr-actions"><Action disabled={blocked || !draft.trim() || draft === question?.text} onClick={() => {
            if (!blocked && run && draft.trim() && draft !== question?.text) { controller!.saveQuestion(run.id, finding.id, draft); setEditing(null); setFeedback("Question update requested. Wait for saved confirmation."); }
          }}>Save question</Action><Action onClick={() => { controller?.flushDrafts(); setEditing(null); setFeedback("Editing closed. Your saved question is unchanged; the draft remains available."); }}>Cancel editing</Action></div>
        </div>}
        <div className="mr-actions">
          {!isEditing && <Action disabled={editBlocked} onClick={() => { if (!editBlocked) { setEditing(finding.id); setFeedback(""); } }}>{question ? "Edit question" : "Add question"}</Action>}
          {question && <details className="mr-row-menu"><summary aria-label={`More actions for ${finding.title}`}>More</summary><Action disabled={blocked} onClick={() => { if (!blocked) setRemoving(finding.id); }}>Remove saved question</Action></details>}
        </div>
        {finding.evidence.length > 0 ? <details className="mr-sources"><summary>Finding source · {finding.evidence.length} {finding.evidence.length === 1 ? "reference" : "references"}</summary>
          <p className="mr-muted">These references accompany the finding; they do not verify your question or its interpretation.</p>
          <ul>{finding.evidence.map((evidence, index) => {
            const matched = evidence.source_revision_id === run?.source_revision_id && evidenceMatches(evidence, matchingSource);
            return <li key={`${evidence.span_id}:${index}`}><button type="button" disabled={!matched} onClick={() => { if (matched) onSource(finding.id, evidence); }}>
              <FileText size={16} aria-hidden="true" /><span>{evidence.label}<span className="mr-reference-page">Page {evidence.page_number}{matched ? " · Open source" : " · Source not matched"}</span></span><ArrowRight size={15} aria-hidden="true" />
            </button></li>;
          })}</ul>
        </details> : <p className="mr-source-note">No source reference accompanies this finding. A not-found claim is limited to the recorded review scope.</p>}
      </li>;
    })}</ol> : <div className="mr-empty"><h3>{!run ? "No review run yet" : filter === "work" ? "Nothing saved or marked yet" : filter === "revisit" ? "Nothing marked for revisit" : filter === "saved" ? "No saved questions in this run" : "No findings in this run"}</h3><p>{!run ? "Start from review setup to keep questions and mark findings for later." : "Keep a question or set a personal status while reviewing. Recoverable drafts stay separate until saved."}</p>{run && <Action onClick={() => setFilter("all")}>Show all findings</Action>}</div>}
    <Modal isOpen={!!removal} onClose={() => setRemoving(null)} title="Remove saved question?" size="sm" footer={<>
      <Action onClick={() => setRemoving(null)}>Keep saved question</Action>
      <Action disabled={blocked} onClick={() => { if (!blocked && run && removal) { controller!.removeQuestion(run.id, removal.id); setRemoving(null); setEditing(null); setFeedback("Removal requested. Your draft and marker are retained; wait for saved confirmation."); } }}>Remove question</Action>
    </>}>
      <p>This removes the confirmed question from My review and future briefs. The finding, source, marker and Ask history stay unchanged.</p>
      <p className="mt-3">Your existing draft stays available, including an empty draft. If no draft exists, the saved wording is kept as a recoverable draft. You can open the editor and save it again.</p>
      {removal && <p className="mt-3 max-h-40 overflow-y-auto whitespace-pre-wrap break-words text-text-secondary">{personal.saved_questions[removal.id].text}</p>}
    </Modal>
  </div>;
}
