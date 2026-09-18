"use client";
import React, { useState, useEffect, useMemo, useCallback, useRef, Suspense } from "react";
import { useAnalysis } from "@/context/AnalysisContext";
import { useRouter, useSearchParams } from "next/navigation";
import { useUserInteractions } from "@/hooks/useUserInteractions";
import { useClauseFiltering } from "@/hooks/useClauseFiltering";
import { useDocumentViewing } from "@/hooks/useDocumentViewing";
import Card from "@/components/Card";
import Button from "@/components/Button";
import Modal from "@/components/ui/Modal";
import PDFViewer from "@/components/PDFViewer";
import ReviewSidebar from "@/components/ReviewSidebar";
import SummaryContent from "@/components/review/SummaryContent";
import ClausesContent from "@/components/review/ClausesContent";
import ChatContent from "@/components/review/ChatContent";
import { Clause } from "@clauseiq/shared-types";
import toast from "@/lib/toast";
import apiClient, { getApiBaseUrl, LOCAL_API_HEADERS } from "@/lib/api";
import { getDocumentSourceStatus, hasCompletedAnalysis } from "@/lib/sourceStatus";

function ReviewWorkspaceContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const { currentDocument, setSelectedClause, loadDocument } = useAnalysis();
  const { trackDocumentView } = useDocumentViewing();
  const requestedDocument = useRef<string | null>(null);
  const analysisReady = hasCompletedAnalysis(currentDocument);

  useEffect(() => {
    const loadDocumentIfNeeded = async () => {
      const documentId = searchParams.get("documentId");

      // If no document ID in URL, redirect to documents page
      if (!documentId) {
        router.push("/documents");
        return;
      }

      // Refresh unfinished imports once on entry, not on each state update.
      if (requestedDocument.current !== documentId) {
        requestedDocument.current = documentId;
        try {
          await loadDocument(documentId);

          // Track that this document has been viewed
          await trackDocumentView(documentId);
        } catch {
          console.error("Failed to load document");
          toast.error("Failed to load document. Please try again.");
          // Redirect back to documents page on error
          router.push("/documents");
        }
      }
    };

    loadDocumentIfNeeded();
  }, [
    searchParams,
    currentDocument.id,
    loadDocument,
    router,
    trackDocumentView,
  ]);

  const {
    filename: fileName,
    clauses,
    summary,
    structuredSummary,
    fullText,
    riskSummary,
    selectedClause,
    id: documentId,
    contract_type,
    last_viewed: lastViewed,
  } = currentDocument;

  // Safe access with defaults - now memoized
  const safeRiskSummary = useMemo(
    () => riskSummary || { high: 0, medium: 0, low: 0 },
    [riskSummary]
  );
  const [clauseFilter, setClauseFilter] = useState<
    "all" | "high" | "medium" | "low"
  >("all");
  const [clauseTypeFilter, setClauseTypeFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [sortBy, setSortBy] = useState<string>("document_order");

  // Sidebar state for new Canva-inspired layout
  const [activeSidebarTab, setActiveSidebarTab] = useState<string | null>(
    "summary"
  );
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);

  // Section state management for persistent expanded/collapsed state
  const [sectionStates, setSectionStates] = useState<Record<string, boolean>>({
    summary: true, // Default expanded
    "key-parties": false,
    "important-dates": false,
    "major-obligations": false,
    "risk-highlights": false,
    "key-insights": false,
  });

  // Memoized handler for section toggle to prevent unnecessary recreations
  const handleSectionToggle = useCallback(
    (sectionId: string, isExpanded: boolean) => {
      setSectionStates((prev) => ({
        ...prev,
        [sectionId]: isExpanded,
      }));
    },
    []
  );

  // Clear selected clause when switching away from clauses tab or when sidebar collapses
  useEffect(() => {
    if (activeSidebarTab !== "clauses" || isSidebarCollapsed) {
      setSelectedClause(null);
    }
  }, [activeSidebarTab, isSidebarCollapsed, setSelectedClause]);

  const {
    flaggedClauses,
    addNote,
    editNote,
    deleteNote,
    toggleFlag,
    hasNotes,
    getAllNotes,
    getNotesCount,
  } = useUserInteractions(analysisReady ? documentId ?? null : null);

  const [isDownloadingPdf, setIsDownloadingPdf] = useState(false);
  const [isDownloadingOriginalPdf, setIsDownloadingOriginalPdf] =
    useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);

  // Use filtering hook for clause logic - moved to top to avoid conditional hook call
  const filteredClauses = useClauseFiltering({
    clauses: (clauses as Clause[]) || [],
    clauseFilter,
    clauseTypeFilter,
    searchQuery,
    sortBy,
    flaggedClauses,
  });

  // Memoize tab content to prevent component recreation and state loss
  const summaryContent = useMemo(
    () => (
      <SummaryContent
        structuredSummary={structuredSummary || undefined}
        summary={summary ?? undefined}
        fullText={fullText ?? undefined}
        clauses={clauses as Clause[] | undefined}
        riskSummary={{
          high: safeRiskSummary?.high ?? 0,
          medium: safeRiskSummary?.medium ?? 0,
          low: safeRiskSummary?.low ?? 0,
        }}
        sectionStates={sectionStates}
        onSectionToggle={handleSectionToggle}
        onClausesClick={() => setActiveSidebarTab("clauses")}
        lastViewed={lastViewed}
      />
    ),
    [
      structuredSummary,
      summary,
      fullText,
      clauses,
      safeRiskSummary,
      sectionStates,
      handleSectionToggle,
      setActiveSidebarTab,
      lastViewed,
    ]
  );

  // PDF Download function
  const handleDownloadPdf = useCallback(async () => {
    if (!documentId) {
      // Defer toast to avoid state update during render
      setTimeout(() => {
        toast.error("No document available to generate report");
      }, 0);
      return;
    }

    setIsDownloadingPdf(true);
    try {
      // Get API base URL from config
      const apiUrl = getApiBaseUrl();

      // Make direct fetch call for PDF download
      const response = await fetch(
        `${apiUrl}/api/v1/reports/documents/${documentId}/pdf`,
        {
          method: "GET",
          headers: {
            ...LOCAL_API_HEADERS,
          },
        }
      );

      if (!response.ok) {
        throw new Error(`Failed to generate PDF: ${response.status}`);
      }

      // Get the PDF blob
      const blob = await response.blob();

      // Create download link
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;

      // Generate filename
      const cleanFileName = (fileName || "document").replace(".pdf", "");
      link.download = `${cleanFileName}_analysis_report.pdf`;

      // Trigger download
      document.body.appendChild(link);
      link.click();

      // Cleanup
      window.URL.revokeObjectURL(url);
      document.body.removeChild(link);

      // Defer toast to avoid state update during render
      setTimeout(() => {
        toast.success("PDF report downloaded successfully!");
      }, 0);
    } catch (error) {
      console.error("Error downloading PDF");
      // Defer toast to avoid state update during render
      setTimeout(() => {
        toast.error(
          error instanceof Error
            ? error.message
            : "Failed to download PDF report"
        );
      }, 0);
    } finally {
      setIsDownloadingPdf(false);
    }
  }, [documentId, fileName]);

  // Download Original PDF function
  const handleDownloadOriginalPdf = useCallback(async () => {
    if (!documentId) {
      setTimeout(() => {
        toast.error("No document available to download");
      }, 0);
      return;
    }

    setIsDownloadingOriginalPdf(true);
    try {
      // Get API base URL from config
      const apiUrl = getApiBaseUrl();

      // Make direct fetch call for original PDF download
      const response = await fetch(
        `${apiUrl}/api/v1/documents/${documentId}/pdf`,
        {
          method: "GET",
          headers: {
            ...LOCAL_API_HEADERS,
          },
        }
      );

      if (!response.ok) {
        if (response.status === 404) {
          throw new Error("Original PDF file not available for this document");
        }
        throw new Error(`Failed to download PDF: ${response.status}`);
      }

      // Get the PDF blob
      const blob = await response.blob();

      // Create download link
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;

      // Use original filename or default
      link.download = fileName || "document.pdf";

      // Trigger download
      document.body.appendChild(link);
      link.click();

      // Cleanup
      window.URL.revokeObjectURL(url);
      document.body.removeChild(link);

      setTimeout(() => {
        toast.success("Original document downloaded successfully!");
      }, 0);
    } catch (error) {
      console.error("Error downloading original PDF");
      setTimeout(() => {
        toast.error(
          error instanceof Error
            ? error.message
            : "Failed to download original PDF"
        );
      }, 0);
    } finally {
      setIsDownloadingOriginalPdf(false);
    }
  }, [documentId, fileName]);

  // Delete Document Functions
  const handleDeleteDocument = useCallback(() => {
    setShowDeleteConfirmation(true);
  }, []);

  const handleConfirmDelete = async () => {
    if (!documentId) {
      setTimeout(() => {
        toast.error("No document available to delete");
      }, 0);
      return;
    }

    setIsDeleting(true);
    try {
      // Call delete endpoint
      const response = await apiClient.delete(`/documents/${documentId}`);

      if (!response.success) {
        throw new Error(response.error?.message || "Failed to delete document");
      }

      setTimeout(() => {
        toast.success("Document deleted successfully!");
      }, 0);

      // Close modal and redirect to homepage
      setShowDeleteConfirmation(false);
      router.push("/");
    } catch (error) {
      console.error("Error deleting document");
      setTimeout(() => {
        toast.error(
          error instanceof Error ? error.message : "Failed to delete document"
        );
      }, 0);
    } finally {
      setIsDeleting(false);
    }
  };

  const handleCancelDelete = () => {
    setShowDeleteConfirmation(false);
  };

  // Memoize dropdown menu items for PDF viewer
  const pdfViewerDropdownItems = useMemo(
    () => [
      {
        label: isDownloadingPdf ? "Generating..." : "Export Analysis",
        icon: (
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
              d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
            />
          </svg>
        ),
        onClick: handleDownloadPdf,
        disabled: isDownloadingPdf,
      },
      {
        label: isDownloadingOriginalPdf
          ? "Downloading..."
          : "Download Document",
        icon: (
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
              d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
            />
          </svg>
        ),
        onClick: handleDownloadOriginalPdf,
        disabled: isDownloadingOriginalPdf,
      },
      {
        label: "Upload Another",
        icon: (
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
              d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
            />
          </svg>
        ),
        onClick: () => router.push("/"),
      },
      {
        label: isDeleting ? "Deleting..." : "Delete Document",
        icon: (
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
              d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
            />
          </svg>
        ),
        onClick: handleDeleteDocument,
        disabled: isDeleting,
        variant: "danger" as const,
      },
    ],
    [
      isDownloadingPdf,
      isDownloadingOriginalPdf,
      isDeleting,
      handleDownloadPdf,
      handleDownloadOriginalPdf,
      handleDeleteDocument,
      router,
    ]
  );

  // Handler functions for ClauseDetailsPanel
  const handleAddNote = async (clause: { id?: string }, noteText?: string) => {
    if (noteText && clause.id) {
      try {
        await addNote(clause.id, noteText);
      } catch {
        // Error handling is done in the hook
      }
    }
  };

  const handleDeleteNote = async (clause: { id?: string }, noteId?: string) => {
    if (clause.id && hasNotes(clause.id)) {
      const notes = getAllNotes(clause.id);
      const targetNoteId = noteId || notes[0]?.id;

      if (targetNoteId) {
        // Confirmation is now handled by the UI component
        try {
          await deleteNote(clause.id, targetNoteId);
        } catch {
          // Error handling is done in the hook
        }
      }
    }
  };

  const handleEditNote = async (
    clause: { id?: string },
    noteId?: string,
    editedText?: string
  ) => {
    if (clause.id && hasNotes(clause.id)) {
      const notes = getAllNotes(clause.id);
      const targetNote = noteId ? notes.find((n) => n.id === noteId) : notes[0];

      if (targetNote && editedText && editedText !== targetNote.text) {
        if (editedText.trim() === "") {
          await handleDeleteNote(clause, targetNote.id);
        } else {
          try {
            await editNote(clause.id, targetNote.id, editedText);
          } catch {
            // Error handling is done in the hook
          }
        }
      }
    }
  };

  const handleFlagForReview = async (
    clause: { id?: string },
    event?: React.MouseEvent
  ) => {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }

    if (clause.id) {
      try {
        await toggleFlag(clause.id);
      } catch {
        // Error handling is done in the hook
      }
    }
  };

  // Copy clause functionality removed.

  if (documentId && !analysisReady) {
    const sourceStatus = getDocumentSourceStatus(currentDocument);
    const originalAvailable = currentDocument.source_status === "stored";
    return (
      <div className="h-screen bg-bg-primary flex flex-col">
        <Card className="m-4 p-6 flex-shrink-0">
          <p className="text-sm text-text-secondary mb-2">{fileName}</p>
          <h1 className="font-heading text-heading-sm text-text-primary mb-2">
            {sourceStatus.label}
          </h1>
          <p className="text-text-secondary max-w-3xl">{sourceStatus.message}</p>
          <p className="text-sm text-text-tertiary mt-2">
            {originalAvailable
              ? "You can read or download the saved original without running AI."
              : "The original PDF is not available to open from this record."}
          </p>
          <div className="flex flex-wrap gap-3 mt-4">
            <Button variant="secondary" onClick={() => router.push("/documents")}>
              Back to documents
            </Button>
            {originalAvailable && (
              <Button
                variant="secondary"
                onClick={handleDownloadOriginalPdf}
                disabled={isDownloadingOriginalPdf}
              >
                {isDownloadingOriginalPdf ? "Downloading..." : "Download original PDF"}
              </Button>
            )}
          </div>
        </Card>
        {originalAvailable && (
          <div className="flex-1 min-h-0">
            <PDFViewer documentId={documentId} fileName={fileName} className="h-full" />
          </div>
        )}
      </div>
    );
  }

  if (!summary && !fileName && (!clauses || clauses.length === 0)) {
    return (
      <div className="min-h-screen bg-bg-primary flex items-center justify-center p-6">
        <Card className="text-center max-w-md mx-auto">
          <div className="mb-6">
            <svg
              className="w-16 h-16 text-text-secondary mx-auto mb-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <h2 className="font-heading text-heading-sm text-text-primary mb-2">
              No document to review
            </h2>
            <p className="text-text-secondary">
              Upload a contract to start your analysis and see detailed insights
              here.
            </p>
          </div>
          <Button onClick={() => router.push("/")}>Upload a Document</Button>
        </Card>
      </div>
    );
  }

  // Define sidebar tabs for new Canva-inspired layout
  const sidebarTabs = [
    {
      id: "summary",
      label: "Document Overview",
      icon: (
        <svg
          className="w-5 h-5"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
      ),
      content: summaryContent,
    },
    {
      id: "clauses",
      label: "Clause Navigator",
      icon: (
        <svg
          className="w-5 h-5"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 6h16M4 10h16M4 14h16M4 18h16"
          />
        </svg>
      ),
      content: (
        <ClausesContent
          clauses={(clauses as Clause[]) || []}
          filteredClauses={filteredClauses}
          selectedClause={selectedClause}
          onClauseSelect={setSelectedClause}
          riskSummary={{
            high: safeRiskSummary?.high ?? 0,
            medium: safeRiskSummary?.medium ?? 0,
            low: safeRiskSummary?.low ?? 0,
          }}
          clauseFilter={clauseFilter}
          onClauseFilterChange={setClauseFilter}
          clauseTypeFilter={clauseTypeFilter}
          onClauseTypeFilterChange={setClauseTypeFilter}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          sortBy={sortBy}
          onSortByChange={setSortBy}
          flaggedClauses={flaggedClauses}
          hasNotes={hasNotes}
          getAllNotes={getAllNotes}
          getNotesCount={getNotesCount}
          contractType={contract_type ?? undefined}
          documentId={documentId ?? undefined}
          onAddNote={handleAddNote}
          onEditNote={handleEditNote}
          onDeleteNote={handleDeleteNote}
          onFlagForReview={handleFlagForReview}
          // Copy clause functionality removed
        />
      ),
    },
    {
      id: "chat",
      label: "Chat with your document",
      icon: (
        <svg
          className="w-5 h-5"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
          />
        </svg>
      ),
      content: <ChatContent documentId={documentId || ""} />,
    },
  ];

  return (
    <div className="h-screen bg-bg-primary flex flex-col">
      {/* Canva-inspired Layout: Vertical Sidebar + Main Content */}
      <div className="flex-1 flex min-h-0">
        {/* ReviewSidebar - Controlled width container */}
        <div
          className={`
          ${
            isSidebarCollapsed || !activeSidebarTab
              ? "w-16"
              : "w-1/3 min-w-[360px] max-w-[550px]"
          }
          transition-all duration-300 ease-in-out flex-shrink-0
        `}
        >
          <ReviewSidebar
            activeTab={activeSidebarTab}
            onTabChange={setActiveSidebarTab}
            tabs={sidebarTabs}
            isCollapsed={isSidebarCollapsed}
            onToggleCollapse={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            onExpandAndSelectTab={(tabId) => {
              setActiveSidebarTab(tabId);
              setIsSidebarCollapsed(false);
            }}
            className="h-full"
          />
        </div>

        {/* Main Content Area - Now contains Document + Optional Right Panel */}
        <div className="flex-1 flex min-w-0">
          {/* Document Viewer Container - Full height, no header */}
          <div className="flex-1 bg-gray-50 h-full">
            <PDFViewer
              documentId={documentId || ""}
              fileName={fileName}
              className="h-full"
              highlightClause={selectedClause}
              onHighlightComplete={(result) => {
                if (!result.found) {
                  // Could show a toast notification here
                  console.warn("Clause not found in PDF");
                }
              }}
              dropdownMenuItems={pdfViewerDropdownItems}
            />
          </div>
        </div>
      </div>

      {/* Delete Confirmation Modal */}
      <Modal
        isOpen={showDeleteConfirmation}
        onClose={handleCancelDelete}
        title="Delete Document"
        size="md"
        className="text-center"
      >
        <div className="space-y-4">
          <div className="mx-auto w-12 h-12 bg-red-100 rounded-full flex items-center justify-center">
            <svg
              className="w-6 h-6 text-red-600"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.5 0L4.314 16.5c-.77.833.192 2.5 1.732 2.5z"
              />
            </svg>
          </div>
          <div>
            <h3 className="text-lg font-semibold text-text-primary mb-2">
              Are you sure?
            </h3>
            <p className="text-text-secondary">
              This will permanently delete &ldquo;{fileName || "this document"}
              &rdquo; and all its analysis data. This action cannot be undone.
            </p>
          </div>
          <div className="flex gap-3 justify-center pt-4">
            <Button
              variant="secondary"
              onClick={handleCancelDelete}
              disabled={isDeleting}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={handleConfirmDelete}
              disabled={isDeleting}
              className="bg-red-600 hover:bg-red-700 text-white"
            >
              {isDeleting ? (
                <>
                  <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2"></div>
                  Deleting...
                </>
              ) : (
                "Delete Document"
              )}
            </Button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

// Wrap the main component in Suspense for useSearchParams
export default function ReviewWorkspace() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-bg-primary flex items-center justify-center">
        <div className="text-center">
          <div className="w-8 h-8 border-2 border-accent-purple border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-text-secondary">Loading review workspace...</p>
        </div>
      </div>
    }>
      <ReviewWorkspaceContent />
    </Suspense>
  );
}
