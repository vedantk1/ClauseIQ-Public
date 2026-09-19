"use client";

import { useCallback, useEffect, useState } from "react";
import { reviewWorkspaceApi } from "@/lib/reviewWorkspaceApi";
import { initialWorkspaceReads, WorkspaceReads } from "@/lib/workspaceReads";
import { ReviewWorkspaceController, type WorkspaceSaveState } from "@/components/workspace/workspaceState";

export function useReviewWorkspace(documentId: string) {
  const [session, setSession] = useState<{
    documentId: string; controller: ReviewWorkspaceController; reads: WorkspaceReads;
  } | null>(null);
  const [state, setState] = useState<WorkspaceSaveState | null>(null);
  const [readState, setReadState] = useState(initialWorkspaceReads);

  useEffect(() => {
    const current = new ReviewWorkspaceController(documentId, reviewWorkspaceApi);
    const reads = new WorkspaceReads(documentId, reviewWorkspaceApi);
    setSession({ documentId, controller: current, reads });
    setState(current.getSnapshot());
    setReadState(reads.getSnapshot());
    const unsubscribe = current.subscribe(() => setState(current.getSnapshot()));
    const unsubscribeReads = reads.subscribe(() => setReadState(reads.getSnapshot()));
    void current.load();
    reads.load();
    return () => { unsubscribeReads(); reads.dispose(); unsubscribe(); current.dispose(); };
  }, [documentId]);

  const isCurrent = session?.documentId === documentId;
  const retrySource = useCallback(() => {
    if (session?.documentId === documentId) void session.reads.retrySource();
  }, [session, documentId]);
  const retryMetadata = useCallback(() => {
    if (session?.documentId === documentId) void session.reads.retryMetadata();
  }, [session, documentId]);

  // A route change must not expose the previous document while its effect cleans up.
  return {
    controller: isCurrent ? session.controller : null,
    state: isCurrent ? state : null,
    ...(isCurrent ? readState : initialWorkspaceReads()),
    retrySource, retryMetadata,
  };
}
