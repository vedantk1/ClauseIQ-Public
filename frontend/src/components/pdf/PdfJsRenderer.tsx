"use client";

import React, { useEffect, useRef } from "react";
import type { PDFDocumentLoadingTask } from "pdfjs-dist";
import type { PDFViewer } from "pdfjs-dist/web/pdf_viewer.mjs";
import { securePdfDocumentOptions } from "@/lib/pdfPageNavigation";
import "pdfjs-dist/web/pdf_viewer.css";
import "@/styles/pdf-viewer.css";

export interface PdfSearchState {
  current: number;
  total: number;
  pending: boolean;
}

export interface PdfJsController {
  jumpToPage: (zeroBased: number) => void;
  search: (query: string) => void;
  nextMatch: () => void;
  previousMatch: () => void;
}

interface PdfJsRendererProps {
  fileUrl: string;
  scale: number;
  viewMode: "single" | "continuous";
  initialPage: number;
  onReady: (controller: PdfJsController, numPages: number) => void;
  onPageChange: (zeroBased: number) => void;
  onSearchChange?: (state: PdfSearchState) => void;
  onError: (message: string) => void;
}

interface PageLocation {
  pageNumber: number;
  left: number;
  top: number;
}

interface ActiveViewer {
  viewer: PDFViewer;
  ready: boolean;
  location: PageLocation | null;
  restoreLocation: () => void;
}

const LOAD_ERROR = "The PDF could not be displayed. The extracted source text is still available.";
const PAGE_ERROR = "This PDF page could not be rendered. The extracted source text is still available.";

/** PDF.js owns the inner DOM; React owns its lifetime and surrounding controls. */
export default function PdfJsRenderer(props: PdfJsRendererProps) {
  const { fileUrl, viewMode, scale } = props;
  const containerRef = useRef<HTMLDivElement>(null);
  const pagesRef = useRef<HTMLDivElement>(null);
  const callbacksRef = useRef(props);
  callbacksRef.current = props;
  const activeRef = useRef<ActiveViewer | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    const pages = pagesRef.current;
    if (!container || !pages || !fileUrl) return;

    // Also releases PDF.js's own scroll listener and ResizeObserver.
    const lifetime = new AbortController();
    let loadingTask: PDFDocumentLoadingTask | null = null;
    let active: ActiveViewer | null = null;
    let stopListeners: (() => void) | null = null;
    let resizeObserver: ResizeObserver | null = null;
    let resizeFrame: number | null = null;
    let reportedError = false;
    let query = "";
    const isCurrent = () => !lifetime.signal.aborted;
    const reportError = (message: string) => {
      if (!isCurrent() || reportedError) return;
      reportedError = true;
      callbacksRef.current.onError(message);
    };

    async function start(container: HTMLDivElement, pages: HTMLDivElement) {
      // The viewer reads pdfjsLib installed by the core module. Load sequentially
      // and only in the browser: the core uses DOMMatrix during initialization.
      const pdfjs = await import("pdfjs-dist");
      if (!isCurrent()) return;
      const { PDFViewer, PDFLinkService, PDFFindController, EventBus, ScrollMode, LinkTarget, FindState } =
        await import("pdfjs-dist/web/pdf_viewer.mjs");
      if (!isCurrent()) return;

      const assets = `/pdfjs/${pdfjs.version}`;
      pdfjs.GlobalWorkerOptions.workerSrc = `${assets}/pdf.worker.min.mjs`;
      const eventBus = new EventBus();
      const linkService = new PDFLinkService({
        eventBus,
        externalLinkTarget: LinkTarget.BLANK,
        externalLinkRel: "noopener noreferrer nofollow",
        ignoreDestinationZoom: true,
      });
      const findController = new PDFFindController({ eventBus, linkService });
      const viewerOptions = {
        container,
        viewer: pages,
        eventBus,
        linkService,
        findController,
        // The viewer enables PDF scripting only when a scripting manager exists;
        // there is no enableScripting constructor flag in the PDF.js API.
        scriptingManager: undefined,
        annotationMode: pdfjs.AnnotationMode.ENABLE,
        annotationEditorMode: pdfjs.AnnotationEditorType.DISABLE,
        imageResourcesPath: `${assets}/images/`,
        supportsPinchToZoom: false,
        enableAutoLinking: false,
        abortSignal: lifetime.signal,
      };
      const viewer = new PDFViewer(viewerOptions);
      viewer.scrollMode = viewMode === "single" ? ScrollMode.PAGE : ScrollMode.VERTICAL;
      linkService.setViewer(viewer);
      active = {
        viewer,
        ready: false,
        location: null,
        restoreLocation() {
          if (!isCurrent() || !active?.ready) return;
          const location = active.location;
          if (location) {
            viewer.scrollPageIntoView({
              pageNumber: location.pageNumber,
              destArray: [null, { name: "XYZ" }, location.left, location.top, null],
              ignoreDestinationZoom: true,
              allowNegativeOffset: true,
            });
          }
          viewer.update();
        },
      };
      activeRef.current = active;

      const find = (type: "" | "again", findPrevious = false) => {
        if (!isCurrent() || !active?.ready) return;
        eventBus.dispatch("find", {
          source: container, type, query, caseSensitive: false,
          entireWord: false, highlightAll: true, findPrevious, matchDiacritics: false,
        });
      };
      const controller: PdfJsController = {
        jumpToPage(zeroBased) {
          if (!isCurrent() || !active?.ready) return;
          if (!Number.isInteger(zeroBased) || zeroBased < 0 || zeroBased >= viewer.pagesCount) {
            throw new RangeError("The requested page is outside this PDF.");
          }
          viewer.scrollPageIntoView({ pageNumber: zeroBased + 1, ignoreDestinationZoom: true });
          viewer.update();
          callbacksRef.current.onPageChange(viewer.currentPageNumber - 1);
        },
        search(nextQuery) {
          if (!isCurrent() || !active?.ready) return;
          query = nextQuery.trim();
          callbacksRef.current.onSearchChange?.({ current: 0, total: 0, pending: Boolean(query) });
          find("");
        },
        nextMatch() { if (query) find("again"); },
        previousMatch() { if (query) find("again", true); },
      };

      const onPagesInit = () => {
        if (!isCurrent() || !active || active.ready) return;
        try {
          const { scale, initialPage } = callbacksRef.current;
          if (!Number.isFinite(scale) || scale <= 0 || !Number.isInteger(initialPage) || initialPage < 0 || initialPage >= viewer.pagesCount) {
            reportError(LOAD_ERROR);
            return;
          }
          viewer.currentScale = scale;
          viewer.scrollPageIntoView({ pageNumber: initialPage + 1, ignoreDestinationZoom: true });
          viewer.update();
          active.ready = true;
          // The parent may have a newer source jump queued during loading.
          // Never notify it of the initial page before it can apply that jump.
          callbacksRef.current.onReady(controller, viewer.pagesCount);
          callbacksRef.current.onPageChange(viewer.currentPageNumber - 1);
        } catch {
          reportError(LOAD_ERROR);
        }
      };
      const onPageChanging = ({ pageNumber }: { pageNumber: number }) => {
        if (isCurrent() && active?.ready) callbacksRef.current.onPageChange(pageNumber - 1);
      };
      const onViewArea = ({ location }: { location: PageLocation }) => {
        if (isCurrent() && active) active.location = { ...location };
      };
      const onFindCount = ({ matchesCount }: { matchesCount: { current: number; total: number } }) => {
        // The generated SDK declaration says state is always null, but the
        // implementation exposes its active find request through this getter.
        const currentQuery = (findController.state as { query?: unknown } | null)?.query;
        if (isCurrent() && query && currentQuery === query) {
          callbacksRef.current.onSearchChange?.({ ...matchesCount, pending: false });
        }
      };
      const onFindState = ({ state, matchesCount, rawQuery }: { state: number; matchesCount: { current: number; total: number }; rawQuery: string }) => {
        if (isCurrent() && query && rawQuery === query) callbacksRef.current.onSearchChange?.({ ...matchesCount, pending: state === FindState.PENDING });
      };
      const onRendered = ({ error }: { error?: unknown }) => {
        if (error) reportError(PAGE_ERROR);
      };
      eventBus.on("pagesinit", onPagesInit);
      eventBus.on("pagechanging", onPageChanging);
      eventBus.on("updateviewarea", onViewArea);
      eventBus.on("updatefindmatchescount", onFindCount);
      eventBus.on("updatefindcontrolstate", onFindState);
      eventBus.on("pagerendered", onRendered);
      stopListeners = () => {
        eventBus.off("pagesinit", onPagesInit);
        eventBus.off("pagechanging", onPageChanging);
        eventBus.off("updateviewarea", onViewArea);
        eventBus.off("updatefindmatchescount", onFindCount);
        eventBus.off("updatefindcontrolstate", onFindState);
        eventBus.off("pagerendered", onRendered);
        linkService.setDocument(null);
      };

      let previousWidth = container.clientWidth;
      let previousHeight = container.clientHeight;
      resizeObserver = new ResizeObserver(() => {
        if (!isCurrent() || !active?.ready) return;
        const { clientWidth: width, clientHeight: height } = container;
        if (width === previousWidth && height === previousHeight) return;
        previousWidth = width;
        previousHeight = height;
        if (resizeFrame != null) cancelAnimationFrame(resizeFrame);
        resizeFrame = requestAnimationFrame(() => {
          resizeFrame = null;
          active?.restoreLocation();
        });
      });
      resizeObserver.observe(container);

      loadingTask = pdfjs.getDocument(securePdfDocumentOptions({
        url: fileUrl,
        cMapUrl: `${assets}/cmaps/`, cMapPacked: true,
        standardFontDataUrl: `${assets}/standard_fonts/`,
        wasmUrl: `${assets}/wasm/`, iccUrl: `${assets}/iccs/`,
        useWorkerFetch: true, enableXfa: false,
        verbosity: pdfjs.VerbosityLevel.ERRORS,
      }));
      loadingTask.onPassword = () => {
        reportError("Password-protected PDFs are not supported. Open an unlocked copy instead.");
        void loadingTask?.destroy().catch(() => {});
      };
      const document = await loadingTask.promise;
      if (!isCurrent()) return;
      linkService.setDocument(document);
      viewer.setDocument(document);
      void viewer.pagesPromise?.catch(() => reportError(LOAD_ERROR));
    }

    void start(container, pages).catch(() => reportError(LOAD_ERROR));
    return () => {
      lifetime.abort();
      if (resizeFrame != null) cancelAnimationFrame(resizeFrame);
      resizeObserver?.disconnect();
      stopListeners?.();
      if (activeRef.current === active) activeRef.current = null;
      if (active) {
        active.ready = false;
        // PDF.js accepts null to cancel page rendering and release document
        // listeners; its generated declaration incorrectly excludes null.
        active.viewer.setDocument(null!);
      }
      void loadingTask?.destroy().catch(() => {});
    };
  }, [fileUrl, viewMode]);

  useEffect(() => {
    const active = activeRef.current;
    if (!active?.ready || !Number.isFinite(scale) || scale <= 0 || active.viewer.currentScale === scale) return;
    active.viewer.currentScale = scale;
    active.restoreLocation();
  }, [scale]);

  return (
    <div className="pdfjs-renderer">
      <div ref={containerRef} className="pdfjs-scroll-container" tabIndex={0} aria-label="PDF document pages">
        <div ref={pagesRef} className="pdfViewer" />
      </div>
    </div>
  );
}
