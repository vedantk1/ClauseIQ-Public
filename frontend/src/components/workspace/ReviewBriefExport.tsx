"use client";

import React, { useRef, useState } from "react";
import type { DocumentSourceResponse, ReviewPersonalState, ReviewRun } from "@clauseiq/shared-types";
import { Action } from "./WorkspaceControls";
import { buildReviewBrief } from "./reviewBrief";
import { copyReviewBrief, downloadReviewBrief } from "./reviewBriefDelivery";

export interface ReviewBriefExportProps {
  filename: string;
  run: ReviewRun | null;
  personal: ReviewPersonalState;
  source: DocumentSourceResponse | null;
  unavailable?: string;
  compact?: boolean;
}

export function ReviewBriefExport({ unavailable, compact = false, ...input }: ReviewBriefExportProps) {
  const brief = buildReviewBrief(input);
  const [feedback, setFeedback] = useState<{ markdown: string; message: string; manualCopy?: boolean; error?: boolean } | null>(null);
  const [copying, setCopying] = useState<string | null>(null);
  const inFlight = useRef<string | null>(null);
  const disabled = !!unavailable || !brief;
  const activeCopy = !!brief && copying === brief.markdown;
  const currentFeedback = !disabled && feedback?.markdown === brief?.markdown ? feedback : null;

  async function copy() {
    if (disabled || !brief || inFlight.current === brief.markdown) return;
    const { markdown } = brief;
    inFlight.current = markdown;
    setCopying(markdown);
    setFeedback(null);
    try {
      await copyReviewBrief(markdown);
      setFeedback({ markdown, message: "Review brief copied." });
    } catch {
      setFeedback({ markdown, error: true, manualCopy: true,
        message: "Clipboard access was unavailable. Select and copy the brief below, or download Markdown." });
    } finally {
      if (inFlight.current === markdown) {
        inFlight.current = null;
        setCopying(null);
      }
    }
  }

  function download() {
    if (disabled || !brief) return;
    try {
      downloadReviewBrief(brief.filename, brief.markdown);
      setFeedback({ markdown: brief.markdown, message: "Markdown download requested. Check your browser’s downloads." });
    } catch {
      setFeedback({ markdown: brief.markdown, error: true, manualCopy: true,
        message: "The download could not be started. Select and copy the brief below." });
    }
  }

  return <section className="co-export" aria-label={compact ? "Export confirmed review brief" : undefined} aria-labelledby={compact ? undefined : "review-brief-heading"}>
    {!compact && <div><h3 id="review-brief-heading">Take your review with you</h3>
      <p className="co-note">Confirmed questions, personal markers and finding context from this run. Drafts and Ask answers stay out. No AI call.</p>
    </div>}
    <div className="co-export-actions">
      <Action disabled={disabled || activeCopy} onClick={() => void copy()}>{activeCopy ? "Copying…" : "Copy brief"}</Action>
      <Action disabled={disabled} onClick={download}>Download Markdown</Action>
    </div>
    {unavailable ? <p className="co-note">{unavailable}</p> : !brief ? <p className="co-note">Save a question or add a personal marker to create a brief.</p> : null}
    {currentFeedback && <p className="co-note" role={currentFeedback.error ? "alert" : "status"}>{currentFeedback.message}</p>}
    {currentFeedback?.manualCopy && brief && <label className="co-export-fallback">Review brief (Markdown)
      <textarea readOnly value={brief.markdown} rows={8} onFocus={event => event.currentTarget.select()} />
    </label>}
  </section>;
}
