import React from "react";
import type { ReviewBrief, ReviewMarker } from "@clauseiq/shared-types";
import { sameBrief, type WorkspaceSaveState } from "./workspaceState";

export const markerLabels: Record<ReviewMarker, string> = {
  not_marked: "Not marked", revisit: "Revisit", reviewed_by_me: "Reviewed by me",
};
export const fieldClass = "w-full rounded-md border border-border-muted bg-bg-primary p-3 text-text-primary focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-purple";
export function Action({ children, className = "", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" {...props} className={`rounded-md border border-border-muted bg-bg-elevated px-3 py-2 text-sm font-medium hover:border-accent-purple focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent-purple disabled:cursor-not-allowed disabled:opacity-50 ${className}`}>{children}</button>;
}
export function Panel({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <section className={`min-w-0 rounded-xl border border-border-muted bg-bg-surface p-5 ${className}`}>{children}</section>;
}

export function SaveFeedback({ state, onReload, onRetry }: {
  state: WorkspaceSaveState; onReload: () => void; onRetry: () => void;
}) {
  const blocked = state.status === "failed" || state.status === "conflict";
  return <div className="rounded-lg border border-border-muted bg-bg-surface p-3 text-sm" aria-live="polite">
    {blocked ? <>
      <p role="alert">{state.status === "conflict" ? "This workspace changed elsewhere. No conflicting edits were applied." : "Saving could not be confirmed."} {state.error}</p>
      <p className="mt-1 text-text-secondary">Your local wording remains on this page. Keep it open; unconfirmed changes may be lost if you leave.</p>
      <div className="mt-2 flex flex-wrap gap-2">
        <Action onClick={onReload}>Reload saved state; keep my drafts</Action>
        {state.status !== "conflict" && state.workspace && <Action onClick={onRetry}>Retry pending changes</Action>}
      </div>
    </> : state.status === "review" ? <>
      <p>Saved state refreshed. Your pending changes have not been applied.</p>
      <p className="mt-1 text-text-secondary">Compare the saved wording with your local draft. Applying pending changes replaces the latest values for those fields.</p>
      <Action className="mt-2" onClick={onRetry}>Apply my pending changes</Action>
    </> : <p>{state.status === "loading" ? "Loading saved workspace…" : state.pending ? "Saving changes… Keep this page open until confirmed." : state.briefDraft && state.workspace && !sameBrief(state.briefDraft, state.workspace.brief) ? "Brief edits have not been saved yet. Other confirmed work is retained." : "Changes saved locally. No AI calls are made here."}</p>}
  </div>;
}

export function BriefForm({ brief, dirty, pending, onChange, onSave }: {
  brief: ReviewBrief; dirty: boolean; pending: boolean; onChange: (brief: ReviewBrief) => void; onSave: () => void;
}) {
  return <Panel>
    <h2 className="text-lg font-semibold">Your review brief</h2>
    <p className="mb-4 mt-1 text-sm text-text-secondary">Changing this brief does not run AI or rewrite an earlier review.</p>
    <div className="space-y-4">
      <label className="block text-sm">Reviewing for
        <select className={`${fieldClass} mt-1`} value={brief.perspective} onChange={event => onChange({ ...brief, perspective: event.target.value as ReviewBrief["perspective"] })}>
          <option value="neutral">Neutral — explain both sides</option>
          <option value="customer">Customer / buyer</option>
          <option value="provider">Service provider</option>
          <option value="other">Another role</option>
        </select>
      </label>
      <label className="block text-sm">Party or role (optional)
        <input className={`${fieldClass} mt-1`} value={brief.role} maxLength={200} onChange={event => onChange({ ...brief, role: event.target.value })} placeholder="For example, the customer" />
      </label>
      <label className="block text-sm">What matters to you? (optional)
        <textarea className={`${fieldClass} mt-1`} rows={3} maxLength={2000} value={brief.priorities} onChange={event => onChange({ ...brief, priorities: event.target.value })} placeholder="Payment, liability, ownership, exit, or relevant practical context" />
      </label>
      <Action disabled={!dirty || pending} onClick={onSave}>Save brief</Action>
      {dirty && <span className="ml-3 text-sm text-text-secondary">Brief changes not yet confirmed.</span>}
    </div>
  </Panel>;
}
