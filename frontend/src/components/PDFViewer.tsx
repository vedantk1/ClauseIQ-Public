"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Button from "./Button";
import DropdownMenu from "./DropdownMenu";
import PdfJsRenderer, { type PdfJsController, type PdfSearchState } from "./pdf/PdfJsRenderer";
import config from "@/config/config";
import { LOCAL_API_HEADERS } from "@/lib/api";
import { getRiskHighlightColor, getRiskBorderColor, type HighlightResult } from "@/utils/pdfHighlightUtils";
import type { Clause } from "@clauseiq/shared-types";
import { PdfPageNavigationSession, pdfPageIndex, pdfSourceKey, type PdfNavigationRequest, type PdfNavigationResult } from "@/lib/pdfPageNavigation";
import styles from "./pdf/PDFReader.module.css";
import { readReaderView, rememberReaderView, type ReaderViewState, type PdfZoom } from "@/lib/readerViewState";

interface PDFViewerProps {
  documentId: string;
  fileName?: string;
  className?: string;
  toolbarLeading?: React.ReactNode;
  toolbarActions?: React.ReactNode;
  rememberView?: boolean;
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
  highlightClause, onHighlightComplete, dropdownMenuItems, toolbarLeading, toolbarActions, rememberView = false,
}: PDFViewerProps) {
  const sourceKey = pdfSourceKey(documentId, sourceRevisionId);
  const bookmark = useMemo(() => rememberView && sourceRevisionId ? readReaderView(sourceKey) : null, [rememberView, sourceRevisionId, sourceKey]);
  const effectiveRequest = navigationRequest?.restore && bookmark ? undefined : navigationRequest;
  const [scale, setScale] = useState<PdfZoom>(bookmark?.zoom ?? 1);
  const [actualScale, setActualScale] = useState(1);
  const zoomLevel = typeof scale === "number" ? scale : actualScale;
  const [viewMode, setViewMode] = useState<"single" | "continuous">(bookmark?.mode ?? "continuous");
  const remembered = useRef<ReaderViewState | null>(bookmark);
  const persistTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [numPages, setNumPages] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [pageError, setPageError] = useState<string | null>(null);
  const [pdfUrl, setPdfUrl] = useState("");
  const [loadedSourceKey, setLoadedSourceKey] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [readyVersion, setReadyVersion] = useState(0);
  const [search, setSearch] = useState<PdfSearchState>({ current: 0, total: 0, pending: false });
  const sessionRef = useRef<PdfPageNavigationSession | null>(null);
  const attemptRef = useRef(retry);
  if (sessionRef.current?.sourceKey !== sourceKey || sessionRef.current?.viewMode !== viewMode || attemptRef.current !== retry) {
    const sameSource = sessionRef.current?.sourceKey === sourceKey;
    sessionRef.current = new PdfPageNavigationSession(sourceKey, viewMode, sessionRef.current);
    if (!sameSource && bookmark) sessionRef.current.pageNumber = bookmark.pageNumber;
    attemptRef.current = retry;
  }
  const session = sessionRef.current;
  const controllerRef = useRef<{ session: PdfPageNavigationSession; controller: PdfJsController } | null>(null);
  const callbacks = useRef({ onPageChange, onNavigationError, onHighlightComplete, navigationRequest: effectiveRequest });
  callbacks.current = { onPageChange, onNavigationError, onHighlightComplete, navigationRequest: effectiveRequest };
  const sourceNavigation = sourceRevisionId != null || navigationRequest != null;
  // Evidence references are physical pages, not heuristic text-search targets.
  const searchQuery = sourceNavigation ? "" : (highlightClause?.text || highlightText || "").trim();

  const remember = useCallback((next: ReaderViewState) => {
    remembered.current = next;
    if (!rememberView || !sourceRevisionId) return;
    rememberReaderView(sourceKey, next, false);
    if (persistTimer.current) clearTimeout(persistTimer.current);
    persistTimer.current = setTimeout(() => rememberReaderView(sourceKey, next), 200);
  }, [rememberView, sourceKey, sourceRevisionId]);

  useEffect(() => {
    if (loadedSourceKey !== sourceKey || currentPage < 1 || currentPage > numPages) return;
    const location = remembered.current?.location;
    remember({ version: 1, pageNumber: currentPage, zoom: scale, mode: viewMode,
      ...(location?.pageNumber === currentPage ? { location } : {}) });
  }, [currentPage, numPages, loadedSourceKey, sourceKey, scale, viewMode, remember]);

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
    if (effectiveRequest) applyNavigation(session.request(effectiveRequest));
    else session.clearRequest();
  }, [effectiveRequest, session, applyNavigation]);

  useEffect(() => {
    const flush = () => {
      if (persistTimer.current) clearTimeout(persistTimer.current);
      if (rememberView && sourceRevisionId && remembered.current) rememberReaderView(sourceKey, remembered.current);
    };
    window.addEventListener("pagehide", flush);
    return () => { window.removeEventListener("pagehide", flush); flush(); };
  }, [rememberView, sourceKey, sourceRevisionId]);

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
    setPageInput("1");
    setPageError(null);
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
    setPageInput(String(session.pageNumber));
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
      setPageInput(String(page));
      setPageError(null);
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

  const goToEnteredPage = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isLoading || controllerRef.current?.session !== session) return;
    const value = pageInput.trim();
    const pageIndex = /^\d+$/.test(value) ? pdfPageIndex(Number(value), numPages) : null;
    if (pageIndex == null) {
      setPageError(`Enter a page number from 1 to ${numPages}.`);
      return;
    }
    setPageError(null);
    session.navigationFailed();
    try {
      controllerRef.current.controller.jumpToPage(pageIndex);
    } catch {
      setPageError("That page could not be opened. Try again or read the extracted text.");
    }
  };

  if (error) return (
    <section className={`${styles.reader} ${className}`} aria-label={`PDF reader: ${fileName}`}>
      {(toolbarLeading || toolbarActions) && <div className={styles.toolbar} aria-label="PDF reading controls">
        {toolbarLeading && <div className={styles.leading}>{toolbarLeading}</div>}
        {toolbarActions}
      </div>}
      <div role="alert" className={styles.error}>
        <h3 className="text-lg font-semibold text-text-primary">Failed to load PDF</h3>
        <p className="my-3 text-text-secondary">{error}</p>
        <Button variant="secondary" onClick={() => setRetry(value => value + 1)}>Retry PDF</Button>
      </div>
    </section>
  );

  return (
    <section className={`${styles.reader} ${className}`} aria-label={`PDF reader: ${fileName}`}>
      <div className={styles.toolbar} aria-label="PDF reading controls">
        {toolbarLeading ? <div className={styles.leading}>{toolbarLeading}</div>
          : <span className={styles.identity} title={fileName}>Original PDF</span>}
        {toolbarActions}
        <div className={styles.controlGroup} role="group" aria-label="Page navigation">
          <Button type="button" size="sm" variant="tertiary" className={styles.iconButton} title="Previous page" aria-label="Previous page"
            disabled={isLoading || currentPage <= 1} onClick={() => movePage(-1)}>←</Button>
          <form onSubmit={goToEnteredPage} className={styles.pageForm}>
            <label>Page <input aria-label="PDF page number" inputMode="numeric" value={pageInput}
              disabled={isLoading || !numPages} aria-invalid={!!pageError}
              title="Enter a physical page number and press Enter"
              onChange={event => { setPageInput(event.target.value); setPageError(null); }}
              onFocus={event => event.currentTarget.select()} /></label>
            <span className={styles.pageCount}>/ {numPages || "—"}</span>
            <button type="submit" className={styles.goButton} disabled={isLoading || !numPages} title="Go to page" aria-label="Go to page">Go</button>
          </form>
          <Button type="button" size="sm" variant="tertiary" className={styles.iconButton} title="Next page" aria-label="Next page"
            disabled={isLoading || currentPage >= numPages} onClick={() => movePage(1)}>→</Button>
          <span className="sr-only" aria-live="polite">{numPages ? `Page ${currentPage} of ${numPages}` : "PDF loading"}</span>
        </div>
        <div className={styles.controlGroup} role="group" aria-label="PDF zoom">
          <Button type="button" size="sm" variant="tertiary" className={styles.iconButton} title="Zoom out" aria-label="Zoom out"
            disabled={zoomLevel <= 0.5} onClick={() => setScale(Math.max(0.5, Math.min(3, Math.round((zoomLevel - 0.2) * 10) / 10)))}>−</Button>
          <label className={styles.zoomValue}><span className="sr-only">PDF zoom</span><select aria-label="PDF zoom" value={typeof scale === "number" ? String(scale) : scale}
            onChange={event => setScale(event.target.value === "page-width" || event.target.value === "page-fit" ? event.target.value : Number(event.target.value))}>
            <option value="page-width">Fit width</option><option value="page-fit">Fit page</option><option value="1">100%</option>
            {typeof scale === "number" && scale !== 1 && <option value={String(scale)}>{Math.round(scale * 100)}%</option>}
          </select></label>
          <Button type="button" size="sm" variant="tertiary" className={styles.iconButton} title="Zoom in" aria-label="Zoom in"
            disabled={zoomLevel >= 3} onClick={() => setScale(Math.min(3, Math.max(.5, Math.round((zoomLevel + 0.2) * 10) / 10)))}>+</Button>
        </div>
        <div className={styles.viewControls}>
          <label className={styles.modeControl}><span>View</span><select aria-label="PDF reading mode" value={viewMode}
            onChange={event => setViewMode(event.target.value as "single" | "continuous")}>
            <option value="continuous">Continuous</option><option value="single">Single page</option>
          </select></label>
          {dropdownMenuItems?.length ? <DropdownMenu align="right" triggerVariant="default" trigger={<span aria-label="Document actions">⋯</span>} items={dropdownMenuItems} /> : null}
        </div>
      </div>
      {pageError && <p className={styles.pageError} role="alert">{pageError}</p>}
      {!sourceNavigation && searchQuery && (
        <div className={styles.searchStatus} role="status">
          {search.pending ? "Searching PDF text…" : search.total ? `Text match ${search.current} of ${search.total}` : "No text match found"}
          {search.total > 1 && <>
            <Button size="sm" variant="secondary" title="Previous match" onClick={() => controllerRef.current?.controller.previousMatch()}>↑</Button>
            <Button size="sm" variant="secondary" title="Next match" onClick={() => controllerRef.current?.controller.nextMatch()}>↓</Button>
          </>}
        </div>
      )}
      <div className={styles.canvas} style={{
        "--pdf-highlight-color": getRiskHighlightColor(highlightClause?.risk_level),
        "--pdf-highlight-border": getRiskBorderColor(highlightClause?.risk_level),
      } as React.CSSProperties}>
        {isLoading && <div className={styles.loading} role="status">Loading PDF…</div>}
        {pdfUrl && loadedSourceKey === sourceKey && <PdfJsRenderer key={`${sourceKey}-${viewMode}-${retry}`}
          fileUrl={pdfUrl} scale={scale} viewMode={viewMode} initialPage={session.pageNumber - 1}
          initialLocation={remembered.current?.location}
          onViewChange={(location, zoom) => {
            if (sessionRef.current !== session || controllerRef.current?.session !== session || location.pageNumber !== session.pageNumber) return;
            setActualScale(zoom);
            remember({ version: 1, pageNumber: location.pageNumber, location, zoom: scale, mode: viewMode });
          }}
          onReady={handleReady} onPageChange={handlePageChange} onSearchChange={handleSearchChange}
          onError={message => {
            if (sessionRef.current !== session) return;
            setError(message);
            setIsLoading(false);
          }} />}
      </div>
    </section>
  );
}
