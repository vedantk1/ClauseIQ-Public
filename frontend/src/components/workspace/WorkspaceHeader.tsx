import React from "react";
import type { ReviewBrief, ReviewRun } from "@clauseiq/shared-types";
import { AppHeader } from "@/components/shell/AppHeader";
import { runLabel, runStatus, type WorkspaceSaveState } from "./workspaceState";
import { WorkspaceSaveIndicator } from "./WorkspaceControls";

const perspectiveLabels: Record<ReviewBrief["perspective"], string> = {
  customer: "Customer perspective",
  provider: "Provider perspective",
  neutral: "Neutral perspective",
  other: "Other perspective",
};

export function WorkspaceHeader({ documentId, filename, run, state, onLeave }: {
  documentId: string;
  filename: string;
  run: ReviewRun | null;
  state: WorkspaceSaveState;
  onLeave: (destination: string) => void;
}) {
  return <AppHeader onNavigate={onLeave} guarded navigationLabel="Workspace navigation"
    moreItems={[{ href: `/review?documentId=${encodeURIComponent(documentId)}`, label: "Earlier review" }]}>
      <h1 className="cw-document-title" title={filename}>{filename}</h1>
      <div className="cw-header-meta">
        {run && <span className="cw-perspective" title={`Original review context: ${run.context.role || run.context.perspective}`}>
          {perspectiveLabels[run.context.perspective]}
        </span>}
        <span className="cw-run-badge" data-kind={run?.kind || "none"} data-status={run ? runStatus(run) : "none"}>
          {run ? run.kind === "fixture" && runStatus(run) === "ready" ? "Synthetic example" : runLabel(run) : "Not reviewed"}
        </span>
        <WorkspaceSaveIndicator state={state} />
      </div>
  </AppHeader>;
}
