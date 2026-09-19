import React from "react";
import { Action } from "./WorkspaceControls";

type ReadStatus = "loading" | "ready" | "error";

/** Read recovery is separate from the review/save controller and paid operations. */
export function SourceReadNotice({ sourceStatus, metadataStatus, sourceError, metadataError,
  onRetrySource, onRetryMetadata }: {
  sourceStatus: ReadStatus; metadataStatus: ReadStatus;
  sourceError: string | null; metadataError: string | null;
  onRetrySource: () => void; onRetryMetadata: () => void;
}) {
  if (!sourceError && !metadataError && sourceStatus !== "loading" && metadataStatus !== "loading") return null;
  return <div className="space-y-2" aria-label="Document loading status">
    {sourceStatus === "loading" ? <p role="status" className="text-sm text-text-secondary">Loading source text… Saved review work stays available.</p>
      : sourceError && <div role="alert" className="rounded-lg border border-border-muted p-3 text-sm">
        <p>{sourceError}</p>
        <p className="mt-1 text-text-secondary">Retry only reads the saved source. It does not discard drafts, extract the PDF again or run AI.</p>
        <Action className="mt-2" onClick={onRetrySource}>Retry source loading</Action>
      </div>}
    {metadataStatus === "loading" ? <p role="status" className="text-sm text-text-secondary">Loading agreement details…</p>
      : metadataError && <div role="alert" className="rounded-lg border border-border-muted p-3 text-sm">
        <p>{metadataError}</p>
        <Action className="mt-2" onClick={onRetryMetadata}>Retry agreement details</Action>
      </div>}
  </div>;
}
