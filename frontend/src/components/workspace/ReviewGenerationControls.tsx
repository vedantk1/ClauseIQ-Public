import React, { useState } from "react";
import type { ReviewRun } from "@clauseiq/shared-types";
import Modal from "@/components/ui/Modal";
import { useWorkspace } from "@/context/WorkspaceContext";
import { type ReviewWorkspaceController, type WorkspaceSaveState, runLabel, runStatus } from "./workspaceState";
import { Action, Panel } from "./WorkspaceControls";

export function ReviewGenerationControls({ state, controller, sourceReady, onSettings, variant = "default" }: {
  state: WorkspaceSaveState; controller: ReviewWorkspaceController; sourceReady: boolean; onSettings: () => void;
  variant?: "default" | "setup";
}) {
  const { settings, isLoading, error, refresh } = useWorkspace();
  const [interruptId, setInterruptId] = useState<string | null>(null);
  const action = state.reviewAction || { status: "idle", error: null, canRetryRequest: false };
  const working = ["preparing", "generating", "interrupting"].includes(action.status);
  const processing = state.workspace?.runs.filter(run => runStatus(run) === "processing") || [];
  const blocked = ["loading", "failed", "conflict", "review"].includes(state.status);
  const askBusy = (state.askAction?.status || "idle") !== "idle" || !!state.workspace?.ask_turns?.some(turn => turn.status === "processing");
  return <Panel className={variant === "setup" ? "cw-setup-generation" : ""}>
    <h2 className="text-lg font-semibold">Start an AI review</h2>
    <p className="mt-2 text-sm">The saved document text and your brief are sent to OpenAI using your key. API charges apply. Earlier runs and personal work are kept separately.</p>
    <p className="mt-3 text-sm">Selected model: <strong>{settings?.model_id || "Unavailable"}</strong></p>
    <p className="mt-1 text-sm text-text-secondary">{isLoading ? "Loading key status…" : settings?.has_api_key && !settings.api_key_needs_reentry ? "Your API key is saved." : "Add or re-enter your API key in Settings before starting. Reading and saving existing work remain available."}</p>
    {error && <p role="alert" className="mt-2 text-sm">Settings could not be confirmed. {error}</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      <Action className={variant === "setup" ? "cw-start-review" : undefined} disabled={working || action.status === "uncertain" || askBusy || blocked || !!processing.length || !sourceReady || isLoading || !!error || !settings?.has_api_key || settings.api_key_needs_reentry}
        onClick={() => settings && void controller.startReview(settings.model_id, crypto.randomUUID())}>
        {action.status === "preparing" ? "Confirming saved work…" : action.status === "generating" ? "Review request in progress…" : state.briefDraft ? "Save brief and start review" : "Start review"}
      </Action>
      <Action disabled={working} onClick={onSettings}>Open Settings</Action>
      <Action disabled={working || isLoading} onClick={() => void refresh()}>Refresh model and key status</Action>
    </div>
    {!sourceReady && <p className="mt-2 text-sm">Load an extracted source before starting a review.</p>}
    {blocked && <p className="mt-2 text-sm">Resolve pending save errors or compare local changes before starting.</p>}
    {askBusy && <p className="mt-2 text-sm">Resolve the current Ask request before starting another paid operation.</p>}
    {working && <p className="mt-3 text-sm" role="status">{action.status === "preparing" ? "Waiting for your brief and pending edits to be confirmed. No review request has been sent yet." : action.status === "interrupting" ? "Marking the saved run interrupted…" : "One bounded request is running. No automatic retry or model switch will occur. Changes you make now stay separate until you confirm applying them."}</p>}
    {action.error && <p role="alert" className="mt-3 text-sm">{action.error}</p>}
    {action.status === "uncertain" && <div className="mt-3 space-y-3 text-sm">
      <p>{action.requestRejected ? "This request was rejected before provider dispatch." : "The provider may have received this request and charges may apply."} Refreshing only reads local saved state; it never starts another review.</p>
      <Action disabled={state.status === "loading"} onClick={() => void controller.reloadSaved()}>Check saved review state</Action>
      {action.canRetryRequest && <div><p className="mb-2">No run for this request was found in the latest saved state. You can explicitly resend the same request ID, original model and saved brief revision. If it was already accepted, the server returns that run without another provider call.</p><Action disabled={state.status === "loading"} onClick={() => void controller.retryReviewRequest()}>Retry this request with the same ID</Action></div>}
    </div>}
    {!!processing.length && <div className="mt-4 space-y-3 border-t border-border-muted pt-4 text-sm">
      <p>A saved review is processing, or its final outcome has not been recorded. Reopening this workspace does not retry it.</p>
      <Action disabled={working || state.status === "loading"} onClick={() => void controller.reloadSaved()}>Refresh saved run status</Action>
      {processing.map(run => <div key={run.id}><p>{runLabel(run)} · {run.generation?.model_id || "Model unavailable"}</p><Action className="mt-2" disabled={working || action.status === "uncertain"} onClick={() => setInterruptId(run.id)}>Mark this run interrupted</Action></div>)}
    </div>}
    <Modal isOpen={!!interruptId} onClose={() => setInterruptId(null)} title="Mark this review interrupted?" footer={<>
      <Action onClick={() => setInterruptId(null)}>Keep waiting</Action>
      <Action onClick={() => { if (interruptId) void controller.interruptRun(interruptId); setInterruptId(null); }}>Mark interrupted</Action>
    </>}>
      <p>This abandons the saved run and discards any late result. It does not cancel a provider request or guarantee a refund; charges may still apply. Starting another review is a separate paid action. Existing runs and personal work are preserved.</p>
    </Modal>
  </Panel>;
}

export function ReviewRunSummary({ run, contextChanged, compact = false }: {
  run: ReviewRun; contextChanged: boolean; compact?: boolean;
}) {
  const introduction = <>
    <p className="font-semibold">{run.kind === "fixture" ? "Synthetic example — not an AI-generated review" : runLabel(run)}</p>
    <p className="mt-1">{run.kind === "fixture" ? "Selected example findings for the exact synthetic managed-services PDF, written from Example Customer's perspective. They are not exhaustive and do not establish legal safety." : "AI interpretation can be wrong. A matched quotation confirms its wording and location, not the finding's correctness or a complete legal review."}</p>
  </>;
  const warnings = <>
    {runStatus(run) === "incomplete" && <p className="mt-2 font-medium">This review is incomplete. Omitted source pages, output or evidence-validation limitations must be considered alongside any displayed findings.</p>}
    {runStatus(run) === "failed" && <p className="mt-2 font-medium">No usable review was completed. The saved original and earlier reviews remain available.</p>}
    {runStatus(run) === "interrupted" && <p className="mt-2 font-medium">This run was abandoned. Late output will not be attached; provider charges may still apply.</p>}
    {runStatus(run) === "processing" && <p className="mt-2 font-medium">No final result is recorded yet. This is not a completed review.</p>}
    {run.failure && <p className="mt-2">{run.failure.message}</p>}
    {contextChanged && <p className="mt-2 font-medium">{compact ? "The saved brief differs; these findings keep their original perspective and have not been rerun." : "The saved brief differs from this review's context. These findings keep their original perspective; changing the brief has not rerun them."}</p>}
  </>;
  const hasWarning = contextChanged || runStatus(run) !== "ready" || !!run.failure;
  return <div className={compact ? "cw-run-summary" : "rounded-lg border border-accent-amber/50 bg-accent-amber/10 p-4 text-sm"} data-warning={hasWarning || undefined}>
    {!compact && introduction}
    {hasWarning && <div className={compact ? "cw-run-warnings" : undefined}>{warnings}</div>}
    <details className={compact ? "cw-provenance" : "mt-2"}><summary className="cursor-pointer">Review context and provenance</summary>
      {compact && introduction}
      <p className="mt-2">{run.context.role || run.context.perspective}</p><p>{run.context.priorities || "No extra priorities supplied."}</p>
      <p className="mt-2">Recorded: {run.created_at}</p>
      {run.generation && <div className="mt-2 space-y-1 break-words text-xs">
        <p>Model: {run.generation.model_id} · endpoint: {run.generation.endpoint} · reasoning: {run.generation.reasoning_effort}</p>
        <p>Prompt: {run.generation.prompt_version} · schema: {run.generation.schema_version} · extractor: {run.generation.extraction_version}</p>
        <p>Estimated input tokens: {run.generation.estimated_input_tokens} · maximum completion tokens: {run.generation.max_completion_tokens}</p>
        <p>{run.generation.usage ? `Provider usage: ${run.generation.usage.prompt_tokens} input + ${run.generation.usage.completion_tokens} output = ${run.generation.usage.total_tokens} tokens` : "Provider usage unavailable; this does not mean no charge."}</p>
        {run.generation.duration_ms !== null && <p>Duration: {(run.generation.duration_ms / 1000).toFixed(1)} seconds</p>}
      </div>}
    </details>
  </div>;
}
