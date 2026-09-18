/**
 * Enhanced AnalysisContext with improved state management
 */

"use client";
import React, {
  createContext,
  useContext,
  ReactNode,
  useCallback,
  useRef,
} from "react";
import { useAppState } from "../store/appState";
import { apiClient, handleAPIError, handleAPISuccess } from "../lib/api";
import { loadWorkspaceDocuments } from "@/lib/documentsApi";
import type { DocumentItem } from "@/types/documents";
import type {
  Clause,
  RiskSummary,
  Document,
  ContractType,
} from "@clauseiq/shared-types";

// Type for AI structured summary data
export interface StructuredSummary {
  overview?: string;
  key_parties?: string[];
  important_dates?: string[];
  major_obligations?: string[];
  risk_highlights?: string[];
  key_insights?: string[];
  [key: string]: string | string[] | undefined; // Allow additional fields
}

interface AnalysisContextType {
  // State from store
  documents: DocumentItem[];
  currentDocument: {
    id: string | null;
    filename: string;
    clauses: Clause[];
    summary: string;
    structuredSummary: StructuredSummary | null;
    fullText: string;
    riskSummary: RiskSummary;
    selectedClause: Clause | null;
    contract_type?: string;
    last_viewed?: string | null;
  };
  isLoading: boolean;
  error: string | null;

  // Actions
  analyzeDocument: (file: File) => Promise<string | null>;
  loadDocuments: () => Promise<void>;
  loadDocument: (documentId: string) => Promise<void>;
  setSelectedClause: (clause: Clause | null) => void;
  clearError: () => void;
  resetAnalysis: () => void;
}

const AnalysisContext = createContext<AnalysisContextType | undefined>(
  undefined
);

export const AnalysisProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const { state, dispatch } = useAppState();
  const analysisState = state.analysis;

  // API call deduplication to prevent duplicate requests
  const activeRequests = useRef<Map<string, Promise<void>>>(new Map());

  // Action implementations
  const analyzeDocument = async (file: File): Promise<string | null> => {

    try {
      dispatch({ type: "ANALYSIS_SET_LOADING", payload: true });
      dispatch({ type: "ANALYSIS_SET_ERROR", payload: null });


      const response = await apiClient.uploadFile<{
        id: string;
        workspace_id: string;
        filename: string;
        summary: string;
        ai_structured_summary?: StructuredSummary;
        clauses: Clause[];
        total_clauses: number;
        risk_summary: RiskSummary;
        full_text?: string;
        contract_type?: string;
      }>("/analysis/analyze/", file);


      if (response.success && response.data) {
        const {
          id,
          workspace_id,
          filename,
          summary,
          ai_structured_summary,
          clauses,
          risk_summary,
          full_text,
          contract_type,
        } = response.data;


        // Add to documents list
        const newDocument: Document = {
          id,
          filename,
          upload_date: new Date().toISOString(),
          contract_type: contract_type as ContractType | null,
          text: full_text || "",
          ai_full_summary: summary,
          ai_structured_summary: ai_structured_summary || null,
          clauses,
          risk_summary: risk_summary,
          workspace_id,
          user_interactions: null,
          last_viewed: null, // Add missing property
        };

        dispatch({ type: "ANALYSIS_ADD_DOCUMENT", payload: newDocument });

        // Set as current document
        dispatch({
          type: "ANALYSIS_SET_CURRENT_DOCUMENT",
          payload: {
            id,
            filename,
            contract_type,
            summary,
            structuredSummary: ai_structured_summary || null,
            clauses,
            riskSummary: risk_summary,
            fullText: full_text || "",
            selectedClause: null,
          },
        });


        handleAPISuccess("Document analyzed successfully!");
        return id; // Return the document ID
      } else {
        const errorMessage =
          response.error?.message || "Failed to analyze document";
        console.error("❌ [DEBUG] Document analysis API error:");
        dispatch({ type: "ANALYSIS_SET_ERROR", payload: errorMessage });
        handleAPIError(response, "Document analysis failed");
        throw new Error(errorMessage);
      }
    } catch (error) {
      const errorMessage =
        error instanceof Error ? error.message : "Unknown error occurred";
      console.error("❌ [DEBUG] Document analysis exception:");
      dispatch({ type: "ANALYSIS_SET_ERROR", payload: errorMessage });
      throw error;
    } finally {
      dispatch({ type: "ANALYSIS_SET_LOADING", payload: false });
    }
  };

  const loadDocuments = useCallback(async (): Promise<void> => {
    try {
      dispatch({ type: "ANALYSIS_SET_LOADING", payload: true });

      const documents = await loadWorkspaceDocuments();
      dispatch({ type: "ANALYSIS_SET_DOCUMENTS", payload: documents });
    } catch (error) {
      dispatch({ type: "ANALYSIS_SET_ERROR", payload: error instanceof Error ? error.message : "Failed to load documents" });
      throw error;
    } finally {
      dispatch({ type: "ANALYSIS_SET_LOADING", payload: false });
    }
  }, [dispatch]);

  const loadDocument = useCallback(
    async (documentId: string): Promise<void> => {
      // Skip if already loading this document or document already loaded
      if (analysisState.currentDocument.id === documentId) {
        return;
      }

      // Check for existing active request to prevent duplicates
      const requestKey = `load-document-${documentId}`;
      const existingRequest = activeRequests.current.get(requestKey);
      if (existingRequest) {
        return existingRequest;
      }

      // Create new request and store it for deduplication
      const loadRequest = async (): Promise<void> => {
        try {
          dispatch({ type: "ANALYSIS_SET_LOADING", payload: true });


          const response = await apiClient.get<{
            id: string;
            filename: string;
            contract_type?: string;
            text: string;
            ai_full_summary: string;
            ai_structured_summary?: StructuredSummary;
            clauses: Clause[];
            risk_summary: RiskSummary;
            last_viewed?: string | null;
          }>(`/documents/${documentId}`);

          if (response.success && response.data) {
            const {
              id,
              filename,
              contract_type,
              text,
              ai_full_summary,
              ai_structured_summary,
              clauses,
              risk_summary,
              last_viewed,
            } = response.data;

            dispatch({
              type: "ANALYSIS_SET_CURRENT_DOCUMENT",
              payload: {
                id,
                filename,
                contract_type,
                fullText: text,
                summary: ai_full_summary,
                structuredSummary: ai_structured_summary || null,
                clauses: clauses || [],
                riskSummary: risk_summary || { high: 0, medium: 0, low: 0 },
                selectedClause: null,
                last_viewed,
              },
            });

          } else {
            const errorMessage =
              response.error?.message || "Failed to load document";
            dispatch({ type: "ANALYSIS_SET_ERROR", payload: errorMessage });
            handleAPIError(response, "Failed to load document");
            throw new Error(errorMessage);
          }
        } catch (error) {
          const errorMessage =
            error instanceof Error ? error.message : "Unknown error occurred";
          dispatch({ type: "ANALYSIS_SET_ERROR", payload: errorMessage });
          throw error;
        } finally {
          dispatch({ type: "ANALYSIS_SET_LOADING", payload: false });
          // Clean up the active request
          activeRequests.current.delete(requestKey);
        }
      };

      // Store and execute the request
      const promise = loadRequest();
      activeRequests.current.set(requestKey, promise);

      return promise;
    },
    [analysisState.currentDocument.id, dispatch]
  );

  const setSelectedClause = useCallback(
    (clause: Clause | null) => {
      dispatch({ type: "ANALYSIS_SET_SELECTED_CLAUSE", payload: clause });
    },
    [dispatch]
  );

  const clearError = useCallback(() => {
    dispatch({ type: "ANALYSIS_SET_ERROR", payload: null });
  }, [dispatch]);

  const resetAnalysis = useCallback(() => {
    dispatch({ type: "ANALYSIS_RESET" });
  }, [dispatch]);

  const contextValue: AnalysisContextType = {
    // State from store
    documents: analysisState.documents,
    currentDocument: analysisState.currentDocument,
    isLoading: analysisState.isLoading,
    error: analysisState.error,

    // Actions
    analyzeDocument,
    loadDocuments,
    loadDocument,
    setSelectedClause,
    clearError,
    resetAnalysis,
  };

  return (
    <AnalysisContext.Provider value={contextValue}>
      {children}
    </AnalysisContext.Provider>
  );
};

export const useAnalysis = () => {
  const context = useContext(AnalysisContext);
  if (context === undefined) {
    throw new Error("useAnalysis must be used within an AnalysisProvider");
  }
  return context;
};
