"use client";

import React, { useState } from "react";
import type { DocumentSourceResponse, ReviewAskTurn, ReviewEvidence, ReviewFinding, ReviewRun } from "@clauseiq/shared-types";
import Modal from "@/components/ui/Modal";
import { useWorkspace } from "@/context/WorkspaceContext";
import { Action, fieldClass, Panel } from "./WorkspaceControls";
import { EvidenceList } from "./EvidenceSourcePane";
import { askHistorySummary, draftKey, paidActionBusy, runStatus, type ReviewWorkspaceController, type WorkspaceSaveState } from "./workspaceState";

export function FindingAsk({ run, finding, state, controller, source, sourceReady, onEvidence, onSettings, reviewQuestion = "" }: {
  run: ReviewRun; finding: ReviewFinding; state: WorkspaceSaveState; controller: ReviewWorkspaceController;
  source: DocumentSourceResponse | null; sourceReady: boolean;
  onEvidence: (text: string, evidence: ReviewEvidence) => void; onSettings: () => void;
  reviewQuestion?: string;
}) {
  const { settings, isLoading, error, refresh } = useWorkspace();
  const [includeHistory, setIncludeHistory] = useState(true);
  const [interruptId, setInterruptId] = useState<string | null>(null);
  const [replacement, setReplacement] = useState<string | null>(null);
  const turns = (state.workspace?.ask_turns || []).filter(turn => turn.run_id === run.id && turn.finding_id === finding.id);
  const savedDraft = state.workspace?.personal[run.id]?.ask_drafts?.[finding.id];
  const draft = state.localAskDrafts?.[draftKey(run.id, finding.id)] ?? savedDraft ?? "";
  const action = state.askAction || { status: "idle", error: null, canRetryRequest: false };
  const ownAction = action.runId === run.id && action.findingId === finding.id;
  const working = ["preparing", "generating", "interrupting"].includes(action.status);
  const blocked = ["loading", "failed", "conflict", "review"].includes(state.status);
  const processing = (state.workspace?.ask_turns || []).some(turn => turn.status === "processing") ||
    !!state.workspace?.runs.some(item => runStatus(item) === "processing");
  const history = askHistorySummary(turns, run.id, finding.id);

  return <Panel className="cw-conversation">
    <div className="cw-conversation-history">
    <h2 className="text-lg font-semibold">Ask about this finding</h2>
    <p className="mt-1 text-sm text-text-secondary">{finding.title}</p>
    <details className="mt-3 text-sm"><summary className="cursor-pointer">Context used for this conversation</summary>
      <p className="mt-2">Sends this finding, its original review perspective and extracted document text to OpenAI using your key.</p>
      {run.kind === "fixture" && <p className="mt-2">This finding is a synthetic example. Ask produces a real paid AI answer, not a prewritten response.</p>}
      <p className="mt-2">Finding: {finding.title}</p><p>Reviewing for: {run.context.role || run.context.perspective}</p>
      <p className="whitespace-pre-wrap">Priorities: {run.context.priorities || "No extra priorities supplied."}</p>
      <p className="mt-2 text-text-secondary">This conversation keeps the selected run&apos;s context. Editing the review brief does not change it. Saved questions, markers and unsent drafts are not included.</p>
    </details>
    <div className="mt-4 space-y-4" aria-label="Saved answers for this finding">
      {turns.length ? turns.map(turn => <AskTurn key={turn.id} turn={turn} source={source} onEvidence={onEvidence}
        onRefresh={() => void controller.reloadSaved()} onInterrupt={() => setInterruptId(turn.id)}
        controlsDisabled={paidActionBusy(state) || blocked || state.pending > 0} />)
        : <p className="cw-ask-empty">Ask about a qualification, exception or uncertainty in this finding. Your answer history will appear here.</p>}
    </div>
    </div>
    <div className="cw-ask-composer">
    <div className="cw-composer-heading"><label htmlFor="ask-draft" className="text-sm font-medium">Question to ask AI</label>
      {reviewQuestion.trim() && <Action disabled={blocked || paidActionBusy(state)} onClick={() => {
        if (blocked || paidActionBusy(state)) return;
        if (draft.trim() && draft !== reviewQuestion) setReplacement(reviewQuestion);
        else controller.setAskDraft(run.id, finding.id, reviewQuestion);
      }}>Use review question</Action>}
    </div>
    <textarea id="ask-draft" className={`${fieldClass} mt-2`} rows={3} maxLength={5000} value={draft}
      onChange={event => controller.setAskDraft(run.id, finding.id, event.target.value)}
      onBlur={() => controller.flushDrafts()} placeholder="For example, does another clause qualify this finding?" />
    <p className="mt-1 text-xs text-text-secondary">Separate Ask draft · nothing is sent until you choose Send.</p>
    {state.status === "review" && savedDraft !== undefined && savedDraft !== draft && <div className="mt-3 rounded border border-border-muted p-3 text-sm">
      <h3 className="font-semibold">Latest saved Ask draft</h3><p className="mt-2 whitespace-pre-wrap">{savedDraft || "Empty draft"}</p>
      <p className="mt-2">Your local wording remains above. Compare both before applying pending changes.</p>
    </div>}
    <details className="cw-ask-options"><summary>Conversation options · {includeHistory ? `${history.count} recent answers` : "fresh question"}</summary>
    <label className="mt-3 flex items-start gap-2 text-sm"><input type="checkbox" checked={includeHistory} disabled={paidActionBusy(state)}
      onChange={event => setIncludeHistory(event.target.checked)} />Include recent answers for this finding</label>
    <p className="mt-1 text-xs text-text-secondary">{includeHistory
      ? `Up to the last 6 usable question-and-answer turns from this finding since the latest successful fresh question are included (${history.count} currently available). Earlier AI answers can be wrong and are not source evidence.`
      : "Fresh question: no earlier Ask turns are included. The finding, original perspective and extracted source are still included."}</p>
    {history.truncated && includeHistory && <p className="mt-1 text-xs text-text-secondary">Older turns stay visible but are omitted from this request. Restate older details when needed.</p>}
    <p className="mt-2 text-xs text-text-secondary">Drafts save locally and stay separate from confirmed questions in My review. Sent wording remains until you edit it.</p>
    <div className="mt-2 flex gap-2"><Action disabled={working} onClick={onSettings}>Open Settings</Action>
      <Action disabled={working || isLoading} onClick={() => void refresh()}>Refresh model and key status</Action></div>
    </details>
    <div className="cw-send-meta"><span>{settings?.model_id || "Model unavailable"}</span><span>Send uses your key · API charges apply{run.kind === "fixture" ? " · live AI, not an example answer" : ""}.</span></div>
    {(isLoading || !settings?.has_api_key || settings.api_key_needs_reentry) && <p className="mt-1 text-xs text-text-secondary">{isLoading ? "Loading model and key status…" : <>Add or re-enter your API key in <button type="button" className="underline" onClick={onSettings}>Settings</button>. Saved answers remain available.</>}</p>}
    {error && <p role="alert" className="mt-2 text-sm">Settings could not be confirmed. {error}</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      <Action disabled={paidActionBusy(state) || blocked || processing || !draft.trim() || !sourceReady ||
          isLoading || !!error || !settings?.has_api_key || settings.api_key_needs_reentry || !["ready", "incomplete"].includes(runStatus(run))}
        onClick={() => settings && void controller.startAsk(run.id, finding.id, draft, settings.model_id, crypto.randomUUID(), includeHistory)}>
        {ownAction && action.status === "preparing" ? "Confirming saved question…" : ownAction && action.status === "generating" ? "Answer request in progress…" : "Send question to AI"}
      </Action>
    </div>
    {!sourceReady && <p className="mt-2 text-sm">The matching extracted source must be loaded before sending.</p>}
    {blocked && <p className="mt-2 text-sm">Resolve pending save errors or compare local changes before sending.</p>}
    {ownAction && working && <p className="mt-3 text-sm" role="status">{action.status === "preparing" ? "Waiting for pending local changes to be confirmed. No AI request has been sent yet." : action.status === "interrupting" ? "Marking the saved answer interrupted…" : "One bounded request is running. No automatic retry or model switch will occur. Your draft is retained."}</p>}
    {ownAction && action.error && <p role="alert" className="mt-3 text-sm">{action.error}</p>}
    {ownAction && action.status === "uncertain" && <div className="mt-3 space-y-3 text-sm">
      <p>{action.requestRejected ? "This request was rejected before provider dispatch." : "The provider may have received the question and charges may apply."} Refreshing only reads saved state; it never sends another question.</p>
      <Action disabled={state.status === "loading"} onClick={() => void controller.reloadSaved()}>Check saved Ask state</Action>
      {action.canRetryRequest && <div><p className="mb-2">No turn with this request ID was found. Resending is an explicit paid action using the original question, model, history choice and revision. If already accepted, the server returns that turn without another provider call.</p><Action disabled={state.status === "loading"} onClick={() => void controller.retryAskRequest()}>Resend same Ask request (API charges may apply)</Action></div>}
    </div>}
    </div>
    <Modal isOpen={replacement !== null} onClose={() => setReplacement(null)} title="Replace the Ask draft?" footer={<>
      <Action onClick={() => setReplacement(null)}>Keep Ask draft</Action>
      <Action disabled={blocked || paidActionBusy(state)} onClick={() => {
        if (replacement !== null && !blocked && !paidActionBusy(state)) { controller.setAskDraft(run.id, finding.id, replacement); setReplacement(null); }
      }}>Replace Ask draft</Action>
    </>}><p>Your different unsent Ask draft will be replaced with the review question. The saved review question and earlier answers stay unchanged. Nothing is sent to AI.</p></Modal>
    <Modal isOpen={!!interruptId} onClose={() => setInterruptId(null)} title="Mark this answer interrupted?" footer={<>
      <Action onClick={() => setInterruptId(null)}>Keep waiting</Action>
      <Action onClick={() => { if (interruptId) void controller.interruptAsk(interruptId); setInterruptId(null); }}>Mark interrupted</Action>
    </>}><p>This abandons the saved answer and discards any late result. It does not cancel the provider request or guarantee a refund. Sending another question is a separate paid action. Your draft and earlier answers remain.</p></Modal>
  </Panel>;
}

export function AskTurn({ turn, source, onEvidence, onRefresh, onInterrupt, controlsDisabled }: {
  turn: ReviewAskTurn; source: DocumentSourceResponse | null;
  onEvidence: (text: string, evidence: ReviewEvidence) => void;
  onRefresh: () => void; onInterrupt: () => void; controlsDisabled: boolean;
}) {
  return <article className="rounded-lg border border-border-muted p-4">
    <h3 className="font-semibold">You asked</h3><p className="mt-2 whitespace-pre-wrap text-sm">{turn.question}</p>
    <p className="mt-3 text-xs font-semibold uppercase tracking-wide">AI answer — {turn.status}</p>
    {turn.answer.map((item, index) => <div className="mt-3 text-sm" key={index}>
      <p className="whitespace-pre-wrap leading-relaxed">{item.text}</p>
      <EvidenceList preview evidence={item.evidence} source={source} onOpen={evidence => onEvidence(item.text, evidence)} />
    </div>)}
    {turn.status === "processing" && <div className="mt-3 space-y-2 text-sm"><p>No final answer is recorded yet. Reopening does not retry it.</p><div className="flex flex-wrap gap-2"><Action disabled={controlsDisabled} onClick={onRefresh}>Refresh saved answer status</Action><Action disabled={controlsDisabled} onClick={onInterrupt}>Mark this answer interrupted</Action></div></div>}
    {turn.status === "incomplete" && <p className="mt-3 text-sm font-medium">This answer is incomplete. Consider the source and output limitations below; missing material has not been checked.</p>}
    {turn.status === "failed" && <p className="mt-3 text-sm">No usable answer was completed. Your question and earlier answers remain saved.</p>}
    {turn.status === "interrupted" && <p className="mt-3 text-sm">This answer was abandoned. Late output will not be attached; provider charges may still apply.</p>}
    {turn.failure && <p className="mt-2 text-sm">{turn.failure.message}</p>}
    {!!turn.limitations.length && <ul className="mt-3 list-disc space-y-1 pl-5 text-sm">{turn.limitations.map((text, index) => <li key={index}>{text}</li>)}</ul>}
    <p className="mt-3 text-xs text-text-secondary">AI interpretation can be wrong. A source match confirms wording and location, not correctness, completeness or legal verification.</p>
    <details className="mt-3 text-xs text-text-secondary"><summary className="cursor-pointer">Answer context, coverage and provenance</summary>
      <div className="mt-2 space-y-2 break-words">
        <p>Recorded: {turn.created_at}{turn.completed_at ? ` · Completed: ${turn.completed_at}` : ""}</p>
        <p>{turn.include_history ? `${turn.history_turn_ids.length} earlier usable turns included from this finding.` : "Fresh question: earlier turns were not included."} {turn.history_truncated ? "Older turns were omitted by the history limit." : ""}</p>
        <p>Input: extracted pages {turn.coverage.extracted_pages.join(", ") || "none"} of {turn.coverage.page_count}. Text supplied is not proof that all provisions were understood.</p>
        {!!turn.coverage.omitted_pages.length && <p>Omitted pages: {turn.coverage.omitted_pages.join(", ")}.</p>}
        {turn.coverage.limitations.map((text, index) => <p key={index}>{text}</p>)}
        <p>Model: {turn.generation.model_id} · reasoning: {turn.generation.reasoning_effort} · endpoint: {turn.generation.endpoint}</p>
        <p>Prompt: {turn.generation.prompt_version} · schema: {turn.generation.schema_version}</p>
        <p>Estimated input tokens: {turn.generation.estimated_input_tokens} · maximum completion tokens: {turn.generation.max_completion_tokens}</p>
        <p>{turn.generation.usage ? `Provider usage: ${turn.generation.usage.prompt_tokens} input + ${turn.generation.usage.completion_tokens} output = ${turn.generation.usage.total_tokens} tokens` : "Provider usage unavailable; this does not mean no charge."}</p>
        {turn.generation.duration_ms != null && <p>Duration: {(turn.generation.duration_ms / 1000).toFixed(1)} seconds</p>}
      </div>
    </details>
  </article>;
}
