"use client";

import { useEffect, useState } from "react";
import type { DocumentSourceResponse } from "@clauseiq/shared-types";
import { reviewWorkspaceApi } from "@/lib/reviewWorkspaceApi";
import { ReviewWorkspaceController, type WorkspaceSaveState } from "@/components/workspace/workspaceState";

export function useReviewWorkspace(documentId: string) {
  const [controller, setController] = useState<ReviewWorkspaceController | null>(null);
  const [state, setState] = useState<WorkspaceSaveState | null>(null);
  const [source, setSource] = useState<DocumentSourceResponse | null>(null);
  const [filename, setFilename] = useState("Agreement");
  const [sourceError, setSourceError] = useState<string | null>(null);

  useEffect(() => {
    const current = new ReviewWorkspaceController(documentId, reviewWorkspaceApi);
    let active = true;
    setController(current);
    setState(current.getSnapshot());
    setSource(null);
    setSourceError(null);
    const unsubscribe = current.subscribe(() => setState(current.getSnapshot()));
    void current.load();
    void Promise.all([reviewWorkspaceApi.source(documentId), reviewWorkspaceApi.document(documentId)])
      .then(([snapshot, document]) => {
        if (active) { setSource(snapshot); setFilename(document.filename); }
      }).catch(() => {
        if (active) setSourceError("Source details could not be loaded. Reload the workspace before checking evidence.");
      });
    return () => { active = false; unsubscribe(); current.dispose(); };
  }, [documentId]);

  return { controller, state, source, filename, sourceError };
}
