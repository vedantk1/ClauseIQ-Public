"use client";
import React, { useState, useMemo, useEffect, useRef } from "react";
import { Worker, Viewer, ScrollMode } from "@react-pdf-viewer/core";
import { zoomPlugin } from "@react-pdf-viewer/zoom";
import { pageNavigationPlugin } from "@react-pdf-viewer/page-navigation";
import { searchPlugin } from "@react-pdf-viewer/search";
import "@react-pdf-viewer/core/lib/styles/index.css";
import "@react-pdf-viewer/page-navigation/lib/styles/index.css";
import "@react-pdf-viewer/search/lib/styles/index.css";
import "../styles/pdf-viewer.css";

import Card from "./Card";
import Button from "./Button";
import DropdownMenu from "./DropdownMenu";
import config from "@/config/config";
import "../utils/pdfConsoleFilter";
import {
  getRiskHighlightColor,
  getRiskBorderColor,
  type HighlightResult,
} from "@/utils/pdfHighlightUtils";
import { usePDFHighlighting } from "@/hooks/usePDFHighlighting";
import type { Clause } from "@clauseiq/shared-types";

interface PDFViewerProps {
  documentId: string;
  fileName?: string;
  className?: string;
  // Text to highlight in the PDF (legacy prop for backward compatibility)
  highlightText?: string;
  // Enhanced clause highlighting
  highlightClause?: Clause | null;
  onHighlightComplete?: (result: HighlightResult) => void;
  // Optional dropdown menu props
  dropdownMenuItems?: Array<{
    label: string;
    icon?: React.ReactNode;
    onClick: () => void;
    disabled?: boolean;
    variant?: "default" | "danger";
  }>;
}

export default function PDFViewer({
  documentId,
  fileName = "Document",
  className = "",
  highlightText,
  highlightClause,
  onHighlightComplete,
  dropdownMenuItems,
}: PDFViewerProps) {
  const [scale, setScale] = useState(1.0);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [numPages, setNumPages] = useState<number | null>(null);
  const [viewMode, setViewMode] = useState<"single" | "continuous">(
    "continuous",
  );

  // Keep highlight styling responsive without recreating the search plugin each render.
  const riskLevelRef = useRef<Clause["risk_level"] | undefined>(undefined);
  useEffect(() => {
    riskLevelRef.current = highlightClause?.risk_level;
  }, [highlightClause?.risk_level]);

  const onHighlightKeyword = React.useCallback(
    (props: { highlightEle: HTMLElement }) => {
      const riskLevel = riskLevelRef.current;
      props.highlightEle.style.backgroundColor = getRiskHighlightColor(riskLevel);
      props.highlightEle.style.border = `2px solid ${getRiskBorderColor(riskLevel)}`;
      props.highlightEle.style.borderRadius = "3px";
      props.highlightEle.style.padding = "1px 2px";
      props.highlightEle.style.boxShadow = "0 1px 3px rgba(0, 0, 0, 0.1)";
    },
    [],
  );

  // Plugin factories from react-pdf-viewer are hooks internally; call them directly (not inside useMemo callbacks).
  const zoomPluginInstance = zoomPlugin();
  const { zoomTo } = zoomPluginInstance;

  const pageNavigationPluginInstance = pageNavigationPlugin();
  const { GoToPreviousPage, GoToNextPage, CurrentPageLabel } =
    pageNavigationPluginInstance;

  const searchPluginInstance = searchPlugin({ onHighlightKeyword });
  const {
    highlight,
    clearHighlights,
    jumpToMatch,
    jumpToNextMatch,
    jumpToPreviousMatch,
  } = searchPluginInstance;

  const viewerPlugins = useMemo(
    () => [zoomPluginInstance, pageNavigationPluginInstance, searchPluginInstance],
    [zoomPluginInstance, pageNavigationPluginInstance, searchPluginInstance],
  );

  // Enhanced highlighting using custom hook
  const highlighting = usePDFHighlighting({
    highlightFunction: React.useCallback(
      async (terms) => {

        try {
          const result = await highlight(terms);

          return result;
        } catch (error) {
          console.error("PDF search plugin highlight failed");
          throw error;
        }
      },
      [highlight],
    ),
    clearHighlights: React.useCallback(() => {
      clearHighlights();
    }, [clearHighlights]),
    jumpToMatch: React.useCallback(
      (index: number) => {
        jumpToMatch(index);
      },
      [jumpToMatch],
    ),
    jumpToNextMatch: React.useCallback(() => {
      jumpToNextMatch();
    }, [jumpToNextMatch]),
    jumpToPreviousMatch: React.useCallback(() => {
      jumpToPreviousMatch();
    }, [jumpToPreviousMatch]),
    debounceMs: 500,
    viewMode: viewMode, // Pass current view mode for different handling
  });

  // PDF URL with authentication — fetch via Authorization header, serve as blob URL (FND-003)
  const [pdfUrl, setPdfUrl] = useState<string>("");

  useEffect(() => {
    let revoke: string | null = null;

    // Reset state when switching documents
    setError(null);
    setIsLoading(true);
    setPdfUrl("");

    if (!documentId) {
      setIsLoading(false);
      setError("Missing document ID");
      return;
    }

    const token = localStorage.getItem("access_token");
    const baseUrl = `${config.apiUrl}/api/v1/documents/${documentId}/pdf`;

    if (!token) {
      setIsLoading(false);
      setError("Authentication required");
      return;
    }

    // Fetch PDF with Authorization header and create blob URL
    fetch(baseUrl, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error(`PDF fetch failed: ${res.status}`);
        return res.blob();
      })
      .then((blob) => {
        const url = URL.createObjectURL(blob);
        revoke = url;
        setPdfUrl(url);
      })
      .catch(() => {
        console.error("Failed to fetch PDF via header auth:");
        setError("Failed to load PDF");
        setIsLoading(false);
        setPdfUrl("");
      });

    return () => {
      if (revoke) URL.revokeObjectURL(revoke);
    };
  }, [documentId]);

  // Toggle view mode function
  const toggleViewMode = () => {
    setViewMode((prev) => (prev === "single" ? "continuous" : "single"));
  };

  // Handle document load
  const handleDocumentLoad = (e: { doc: { numPages: number } }) => {
    setNumPages(e.doc.numPages);
    setIsLoading(false);
    setError(null);

    // Set initial zoom level
    zoomTo(scale);

  };

  const { executeHighlighting } = highlighting;

  // Enhanced clause highlighting effect
  const executeHighlightingRef = useRef(executeHighlighting);
  const highlightClauseRef = useRef<Clause | null>(highlightClause ?? null);
  const highlightClauseKey = highlightClause?.id ?? null;

  useEffect(() => {
    executeHighlightingRef.current = executeHighlighting;
  }, [executeHighlighting]);

  useEffect(() => {
    highlightClauseRef.current = highlightClause ?? null;
  }, [highlightClause]);

  useEffect(() => {
    void executeHighlightingRef
      .current(highlightClauseRef.current)
      .catch(() => {
        console.error("Error in clause highlighting:");
      });
  }, [highlightClauseKey]);

  // Notify parent component when highlighting completes
  React.useEffect(() => {
    try {
      if (highlighting.highlightResult) {
        onHighlightComplete?.(highlighting.highlightResult);
      }
    } catch {
      console.error("Error in highlight completion callback:");
    }
  }, [highlighting.highlightResult, onHighlightComplete]);

  // Legacy highlighting support (backward compatibility)
  React.useEffect(() => {
    if (highlightText && !isLoading && !highlightClause) {
      // Small delay to ensure PDF is fully loaded
      const timer = setTimeout(() => {
        try {
          // Try exact text first
          highlight(highlightText);
        } catch {
          console.warn("Failed to highlight exact text, trying keywords...");
          // Fallback: extract first and last few words
          const words = highlightText.trim().split(/\s+/);
          if (words.length > 6) {
            const keywords = [...words.slice(0, 3), ...words.slice(-3)];
            highlight(keywords);
          } else {
            highlight(words);
          }
        }
      }, 1000);

      return () => clearTimeout(timer);
    }
  }, [highlightText, isLoading, highlight, highlightClause]);

  // This effect is now handled by the custom hook

  // Debug: Monitor state changes
  // Zoom controls
  const zoomIn = () => {
    const newScale = Math.min(scale + 0.2, 3.0);
    setScale(newScale);
    zoomTo(newScale);
  };

  const zoomOut = () => {
    const newScale = Math.max(scale - 0.2, 0.5);
    setScale(newScale);
    zoomTo(newScale);
  };

  const resetZoom = () => {
    setScale(1.0);
    zoomTo(1.0);
  };

  // Navigation functions are now provided by the hook

  // Show error state if there's an error
  if (error) {
    return (
      <Card
        className={`flex flex-col shadow-lg rounded-lg border border-accent-rose/20 ${className}`}
      >
        <div className="flex items-center justify-center h-full p-8">
          <div className="text-center">
            <div className="text-accent-rose text-lg font-semibold mb-2">
              Failed to Load PDF
            </div>
            <div className="text-text-secondary text-sm mb-4">{error}</div>
            <Button
              onClick={() => window.location.reload()}
              size="sm"
              variant="secondary"
            >
              Retry
            </Button>
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card
      className={`h-full flex flex-col shadow-lg border border-border-muted !p-0 ${className}`}
      rounded={false}
    >
      {/* Header with controls - ClauseIQ Professional Styling */}
      <div className="flex items-center justify-between p-4 border-b border-border-muted bg-gradient-to-r from-bg-surface to-bg-elevated">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold text-text-primary">
            {fileName}
          </h3>
          {numPages && (
            <span className="text-sm text-text-secondary bg-bg-elevated px-2 py-1 rounded-md">
              {numPages} pages
            </span>
          )}
        </div>

        {/* Controls Section - View Mode Toggle, Page Navigation & Zoom */}
        <div className="flex items-center gap-4">
          {/* View Mode Toggle */}
          <div className="flex items-center gap-2">
            <Button
              onClick={toggleViewMode}
              size="sm"
              variant="secondary"
              title={
                viewMode === "single"
                  ? "Switch to continuous view"
                  : "Switch to single-page view"
              }
            >
              {viewMode === "single" ? "Single" : "Scroll"}
            </Button>
          </div>

          {/* Page Navigation - Only show in single mode */}
          {viewMode === "single" && numPages && (
            <div className="flex items-center gap-2 border-l border-border-muted pl-4">
              <GoToPreviousPage>
                {(props) => (
                  <Button
                    onClick={props.onClick}
                    size="sm"
                    variant="secondary"
                    disabled={props.isDisabled}
                    title="Previous page"
                  >
                    ←
                  </Button>
                )}
              </GoToPreviousPage>

              <CurrentPageLabel>
                {(props) => (
                  <span className="text-sm text-text-secondary min-w-16 text-center font-medium">
                    {props.currentPage + 1} / {props.numberOfPages}
                  </span>
                )}
              </CurrentPageLabel>

              <GoToNextPage>
                {(props) => (
                  <Button
                    onClick={props.onClick}
                    size="sm"
                    variant="secondary"
                    disabled={props.isDisabled}
                    title="Next page"
                  >
                    →
                  </Button>
                )}
              </GoToNextPage>
            </div>
          )}

          {/* Highlighting Status & Navigation */}
          {(highlighting.isHighlighting || highlighting.highlightResult) && (
            <div className="flex items-center gap-2 border-l border-border-muted pl-4">
              {highlighting.isHighlighting && (
                <div className="flex items-center gap-2">
                  <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-accent-purple"></div>
                  <span className="text-sm text-text-secondary">
                    Searching...
                  </span>
                </div>
              )}

              {highlighting.highlightResult && !highlighting.isHighlighting && (
                <div className="flex items-center gap-2">
                  {highlighting.highlightResult.found ? (
                    <>
                      <div className="flex items-center gap-1">
                        <div
                          className="w-3 h-3 rounded-full border-2"
                          style={{
                            backgroundColor: getRiskHighlightColor(
                              highlightClause?.risk_level,
                            ),
                            borderColor: getRiskBorderColor(
                              highlightClause?.risk_level,
                            ),
                          }}
                        ></div>
                        <span className="text-sm text-text-secondary">
                          Found ({highlighting.highlightResult.strategy})
                        </span>
                      </div>

                      {highlighting.totalMatches > 1 && (
                        <div className="flex items-center gap-1">
                          <Button
                            onClick={highlighting.goToPreviousMatch}
                            size="sm"
                            variant="secondary"
                            title="Previous match"
                          >
                            ↑
                          </Button>
                          <span className="text-xs text-text-secondary min-w-8 text-center">
                            {highlighting.currentMatchIndex + 1}/
                            {highlighting.totalMatches}
                          </span>
                          <Button
                            onClick={highlighting.goToNextMatch}
                            size="sm"
                            variant="secondary"
                            title="Next match"
                          >
                            ↓
                          </Button>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="flex items-center gap-1">
                      <div className="w-3 h-3 rounded-full bg-gray-300 border-2 border-gray-400"></div>
                      <span className="text-sm text-text-secondary">
                        Not found
                      </span>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Zoom Controls */}
          <div className="flex items-center gap-2 border-l border-border-muted pl-4">
            <Button
              onClick={zoomOut}
              size="sm"
              variant="secondary"
              disabled={scale <= 0.5}
              title="Zoom out"
            >
              -
            </Button>
            <span className="text-sm text-text-secondary min-w-12 text-center font-medium">
              {Math.round(scale * 100)}%
            </span>
            <Button
              onClick={zoomIn}
              size="sm"
              variant="secondary"
              disabled={scale >= 3.0}
              title="Zoom in"
            >
              +
            </Button>
            <Button onClick={resetZoom} size="sm" variant="secondary" title="Reset zoom">
              Reset
            </Button>
          </div>

          {/* Document Actions Menu */}
          {dropdownMenuItems && dropdownMenuItems.length > 0 && (
            <div className="flex items-center border-l border-border-muted pl-4">
              <DropdownMenu
                align="right"
                triggerVariant="default"
                trigger={
                  <svg
                    className="w-4 h-4"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z"
                    />
                  </svg>
                }
                items={dropdownMenuItems}
              />
            </div>
          )}
        </div>
      </div>

      {/* Continuous scroll PDF viewer */}
      {/* NOTE: overflow-hidden on outer container, scrolling handled by rpv-core__inner-pages for cross-browser consistency */}
      <div
        className="flex-1 bg-bg-surface relative min-h-0 overflow-hidden"
        style={{ height: "calc(100vh - 70px)" }}
      >
        {isLoading && (
          <div className="absolute inset-0 bg-bg-surface flex items-center justify-center z-10">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-accent-purple mx-auto mb-2"></div>
              <div className="text-sm text-text-secondary font-medium">
                Loading PDF...
              </div>
            </div>
          </div>
        )}
        <Worker workerUrl="https://unpkg.com/pdfjs-dist@3.11.174/build/pdf.worker.min.js">
          <div style={{ height: "100%" }} className="pdf-viewer-container">
            {pdfUrl ? (
              <Viewer
                fileUrl={pdfUrl}
                // PDF.js mitigation for GHSA-wgrm-67xf-hhpq while the viewer remains on PDF.js 3.
                transformGetDocumentParams={(options) => ({
                  ...options,
                  isEvalSupported: false,
                })}
                onDocumentLoad={handleDocumentLoad}
                plugins={viewerPlugins}
                scrollMode={
                  viewMode === "single" ? ScrollMode.Page : ScrollMode.Vertical
                }
                initialPage={0}
                key={`pdf-viewer-${viewMode}`}
              />
            ) : null}
          </div>
        </Worker>
      </div>
    </Card>
  );
}
