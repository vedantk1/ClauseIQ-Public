"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Card from "./Card";
import Button from "./Button";
import DropdownMenu from "./DropdownMenu";
import PdfJsRenderer, { type PdfJsController, type PdfSearchState } from "./pdf/PdfJsRenderer";
import config from "@/config/config";
import { LOCAL_API_HEADERS } from "@/lib/api";
import { getRiskHighlightColor, getRiskBorderColor, type HighlightResult } from "@/utils/pdfHighlightUtils";
import type { Clause } from "@clauseiq/shared-types";
import { PdfPageNavigationSession, pdfSourceKey, type PdfNavigationRequest, type PdfNavigationResult } from "@/lib/pdfPageNavigation";

interface PDFViewerProps {
  documentId: string;
  fileName?: string;
  className?: string;
  sourceRevisionId?: string;
  navigationRequest?: PdfNavigationRequest;
  onPageChange?: (pageNumber: number) => void;
  onNavigationError?: (message: string) => void;
  highlightText?: string;
  highlightClause?: Clause | null;
  onHighlightComplete?: (result: HighlightResult) => void;
  dropdownMenuItems?: Array<{
    label: string;
    icon?: React.ReactNode;
    onClick: () => void;
    disabled?: boolean;
    variant?: "default" | "danger";
  }>;
}

/** Local fetch and source-page policy stay independent of the rendering library. */
export default function PDFViewer({
  documentId, fileName = "Document", className = "", sourceRevisionId,
  navigationRequest, onPageChange, onNavigationError, highlightText,
  highlightClause, onHighlightComplete, dropdownMenuItems,
}: PDFViewerProps) {
  const [scale, setScale] = useState(1);
  const [viewMode, setViewMode] = useState<"single" | "continuous">("continuous");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [pdfUrl, setPdfUrl] = useState("");
  const [loadedSourceKey, setLoadedSourceKey] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [readyVersion, setReadyVersion] = useState(0);
  const [search, setSearch] = useState<PdfSearchState>({ current: 0, total: 0, pending: false });
  const sourceKey = pdfSourceKey(documentId, sourceRevisionId);
  const sessionRef = useRef<PdfPageNavigationSession | null>(null);
  const attemptRef = useRef(retry);
  if (sessionRef.current?.sourceKey !== sourceKey || sessionRef.current?.viewMode !== viewMode || attemptRef.current !== retry) {
    sessionRef.current = new PdfPageNavigationSession(sourceKey, viewMode, sessionRef.current);
    attemptRef.current = retry;
  }
  const session = sessionRef.current;
  const controllerRef = useRef<{ session: PdfPageNavigationSession; controller: PdfJsController } | null>(null);
  const callbacks = useRef({ onPageChange, onNavigationError, onHighlightComplete, navigationRequest });
  callbacks.current = { onPageChange, onNavigationError, onHighlightComplete, navigationRequest };
  const sourceNavigation = sourceRevisionId != null || navigationRequest != null;
  // Evidence references are physical pages, not heuristic text-search targets.
  const searchQuery = sourceNavigation ? "" : (highlightClause?.text || highlightText || "").trim();

  const applyNavigation = useCallback((result: PdfNavigationResult) => {
    if (sessionRef.current !== session || !result) return;
    if ("error" in result) {
      callbacks.current.onNavigationError?.(result.error);
      return;
    }
    const active = controllerRef.current;
    if (active?.session !== session) return;
    try {
      active.controller.jumpToPage(result.pageIndex);
    } catch {
      session.navigationFailed();
      callbacks.current.onNavigationError?.("The requested PDF page could not be opened. The extracted excerpt is still available.");
    }
  }, [session]);

  useEffect(() => {
    if (navigationRequest) applyNavigation(session.request(navigationRequest));
    else session.clearRequest();
  }, [navigationRequest, session, applyNavigation]);

  useEffect(() => {
    const abort = new AbortController();
    let objectUrl: string | null = null;
    controllerRef.current = null;
    setError(null);
    setIsLoading(true);
    setPdfUrl("");
    setLoadedSourceKey(null);
    setNumPages(0);
    setCurrentPage(1);
    setSearch({ current: 0, total: 0, pending: false });
    if (!documentId) {
      setError("Missing document ID");
      setIsLoading(false);
      return;
    }
    fetch(`${config.apiUrl}/api/v1/documents/${encodeURIComponent(documentId)}/pdf`, {
      headers: LOCAL_API_HEADERS, signal: abort.signal,
    }).then(response => {
      if (!response.ok) throw new Error("PDF request failed");
      return response.blob();
    }).then(blob => {
      if (abort.signal.aborted) return;
      objectUrl = URL.createObjectURL(blob);
      setLoadedSourceKey(sourceKey);
      setPdfUrl(objectUrl);
    }).catch(() => {
      if (abort.signal.aborted) return;
      setError("Failed to load PDF. Your saved review and extracted text are unchanged.");
      setIsLoading(false);
    });
    return () => {
      abort.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [documentId, sourceKey, retry]);

  const handleReady = (controller: PdfJsController, pageCount: number) => {
    if (sessionRef.current !== session || loadedSourceKey !== sourceKey) return;
    controllerRef.current = { session, controller };
    setNumPages(pageCount);
    setCurrentPage(session.pageNumber);
    setIsLoading(false);
    setError(null);
    // A renderer can become ready before the latest request's passive effect.
    if (callbacks.current.navigationRequest) applyNavigation(session.request(callbacks.current.navigationRequest));
    else session.clearRequest();
    applyNavigation(session.loaded(pageCount));
    setReadyVersion(version => version + 1);
  };

  const handlePageChange = (pageIndex: number) => {
    if (sessionRef.current !== session || controllerRef.current?.session !== session) return;
    const page = session.pageChanged(pageIndex);
    if (page != null) {
      setCurrentPage(page);
      callbacks.current.onPageChange?.(page);
    }
  };

  useEffect(() => {
    const active = controllerRef.current;
    if (sourceNavigation || active?.session !== session) return;
    setSearch({ current: 0, total: 0, pending: Boolean(searchQuery) });
    active.controller.search(searchQuery);
  }, [searchQuery, sourceNavigation, session, readyVersion]);

  const handleSearchChange = (next: PdfSearchState) => {
    if (sourceNavigation || sessionRef.current !== session || !searchQuery) return;
    setSearch(next);
    if (!next.pending) callbacks.current.onHighlightComplete?.({
      found: next.total > 0, strategy: "pdf_text_search", searchTerms: searchQuery, matchCount: next.total,
    });
  };

  const movePage = (delta: number) => {
    const target = currentPage + delta;
    if (target < 1 || target > numPages || controllerRef.current?.session !== session) return;
    session.navigationFailed();
    controllerRef.current.controller.jumpToPage(target - 1);
  };

  if (error) return (
    <Card className={`h-full flex flex-col ${className}`}>
      <div role="alert" className="p-6 text-center">
        <h3 className="text-lg font-semibold text-text-primary">Failed to load PDF</h3>
        <p className="my-3 text-text-secondary">{error}</p>
        <Button variant="secondary" onClick={() => setRetry(value => value + 1)}>Retry PDF</Button>
      </div>
    </Card>
  );

  return (
    <Card className={`h-full flex flex-col border border-border-muted !p-0 ${className}`} rounded={false}>
      <div className="flex flex-wrap items-center justify-between gap-3 p-3 border-b border-border-muted bg-bg-surface">
        <h3 className="min-w-0 truncate font-semibold text-text-primary" title={fileName}>{fileName}</h3>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" variant="secondary" onClick={() => setViewMode(mode => mode === "single" ? "continuous" : "single")}
            title={viewMode === "single" ? "Switch to continuous view" : "Switch to single-page view"}>
            {viewMode === "single" ? "Single" : "Scroll"}
          </Button>
          <Button size="sm" variant="secondary" title="Previous page" aria-label="Previous page"
            disabled={isLoading || currentPage <= 1} onClick={() => movePage(-1)}>←</Button>
          <span className="text-sm text-text-secondary tabular-nums" aria-live="polite">{numPages ? `${currentPage} / ${numPages}` : "—"}</span>
          <Button size="sm" variant="secondary" title="Next page" aria-label="Next page"
            disabled={isLoading || currentPage >= numPages} onClick={() => movePage(1)}>→</Button>
          <Button size="sm" variant="secondary" title="Zoom out" aria-label="Zoom out"
            disabled={scale <= 0.5} onClick={() => setScale(value => Math.max(0.5, Math.round((value - 0.2) * 10) / 10))}>−</Button>
          <span className="text-sm text-text-secondary tabular-nums">{Math.round(scale * 100)}%</span>
          <Button size="sm" variant="secondary" title="Zoom in" aria-label="Zoom in"
            disabled={scale >= 3} onClick={() => setScale(value => Math.min(3, Math.round((value + 0.2) * 10) / 10))}>+</Button>
          <Button size="sm" variant="secondary" title="Reset zoom" onClick={() => setScale(1)}>Reset</Button>
          {dropdownMenuItems?.length ? <DropdownMenu align="right" triggerVariant="default" trigger={<span aria-label="Document actions">⋯</span>} items={dropdownMenuItems} /> : null}
        </div>
      </div>
      {!sourceNavigation && searchQuery && (
        <div className="flex items-center gap-2 px-3 py-2 text-sm text-text-secondary" role="status">
          {search.pending ? "Searching PDF text…" : search.total ? `Text match ${search.current} of ${search.total}` : "No text match found"}
          {search.total > 1 && <>
            <Button size="sm" variant="secondary" title="Previous match" onClick={() => controllerRef.current?.controller.previousMatch()}>↑</Button>
            <Button size="sm" variant="secondary" title="Next match" onClick={() => controllerRef.current?.controller.nextMatch()}>↓</Button>
          </>}
        </div>
      )}
      <div className="flex-1 relative min-h-0 overflow-hidden bg-bg-primary" style={{
        "--pdf-highlight-color": getRiskHighlightColor(highlightClause?.risk_level),
        "--pdf-highlight-border": getRiskBorderColor(highlightClause?.risk_level),
      } as React.CSSProperties}>
        {isLoading && <div className="absolute inset-0 grid place-items-center z-10 bg-bg-surface text-text-secondary" role="status">Loading PDF…</div>}
        {pdfUrl && loadedSourceKey === sourceKey && <PdfJsRenderer key={`${sourceKey}-${viewMode}-${retry}`}
          fileUrl={pdfUrl} scale={scale} viewMode={viewMode} initialPage={session.pageNumber - 1}
          onReady={handleReady} onPageChange={handlePageChange} onSearchChange={handleSearchChange}
          onError={message => {
            if (sessionRef.current !== session) return;
            setError(message);
            setIsLoading(false);
          }} />}
      </div>
    </Card>
  );
}
