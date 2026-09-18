/**
 * Centralized state management using React Context and Reducers
 */
"use client";

import React, { createContext, useContext, useReducer, ReactNode } from "react";
import type {
  Clause,
  RiskSummary,
  SourceMetadata,
} from "@clauseiq/shared-types";
import { StructuredSummary } from "../context/AnalysisContext";
import type { DocumentItem } from "@/types/documents";

// State interfaces
export interface AnalysisState {
  documents: DocumentItem[];
  currentDocument: SourceMetadata & {
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
}

export interface AppState {
  analysis: AnalysisState;
  ui: {
    sidebarOpen: boolean;
    theme: "light" | "dark";
    notifications: Array<{
      id: string;
      type: "info" | "success" | "warning" | "error";
      message: string;
      timestamp: number;
    }>;
  };
}

// Action types
export type AnalysisAction =
  | { type: "ANALYSIS_SET_LOADING"; payload: boolean }
  | { type: "ANALYSIS_SET_ERROR"; payload: string | null }
  | { type: "ANALYSIS_SET_DOCUMENTS"; payload: DocumentItem[] }
  | { type: "ANALYSIS_ADD_DOCUMENT"; payload: DocumentItem }
  | {
      type: "ANALYSIS_SET_CURRENT_DOCUMENT";
      payload: Partial<AnalysisState["currentDocument"]>;
    }
  | {
      type: "ANALYSIS_UPDATE_CURRENT_DOCUMENT";
      payload: Partial<AnalysisState["currentDocument"]>;
    }
  | { type: "ANALYSIS_SET_SELECTED_CLAUSE"; payload: Clause | null }
  | { type: "ANALYSIS_RESET" };

export type UIAction =
  | { type: "UI_TOGGLE_SIDEBAR" }
  | { type: "UI_SET_THEME"; payload: "light" | "dark" }
  | { type: "UI_ADD_NOTIFICATION"; payload: { type: string; message: string } }
  | { type: "UI_REMOVE_NOTIFICATION"; payload: string };

export type AppAction = AnalysisAction | UIAction;

// Initial states
const initialAnalysisState: AnalysisState = {
  documents: [],
  currentDocument: {
    id: null,
    filename: "",
    clauses: [],
    summary: "",
    structuredSummary: null,
    fullText: "",
    riskSummary: { high: 0, medium: 0, low: 0 },
    selectedClause: null,
    contract_type: undefined,
    last_viewed: null,
  },
  isLoading: false,
  error: null,
};

const initialAppState: AppState = {
  analysis: initialAnalysisState,
  ui: {
    sidebarOpen: false,
    theme: "dark", // Default to dark theme
    notifications: [],
  },
};

// Reducers
export const analysisReducer = (
  state: AnalysisState,
  action: AnalysisAction,
): AnalysisState => {

  switch (action.type) {
    case "ANALYSIS_SET_LOADING":
      return { ...state, isLoading: action.payload };

    case "ANALYSIS_SET_ERROR":
      return { ...state, error: action.payload };

    case "ANALYSIS_SET_DOCUMENTS":
      return { ...state, documents: action.payload };

    case "ANALYSIS_ADD_DOCUMENT":
      return {
        ...state,
        documents: [action.payload, ...state.documents],
      };

    case "ANALYSIS_SET_CURRENT_DOCUMENT":
      return {
        ...state,
        currentDocument: { ...initialAnalysisState.currentDocument, ...action.payload },
      };

    case "ANALYSIS_UPDATE_CURRENT_DOCUMENT":
      return {
        ...state,
        currentDocument: { ...state.currentDocument, ...action.payload },
      };

    case "ANALYSIS_SET_SELECTED_CLAUSE":
      return {
        ...state,
        currentDocument: {
          ...state.currentDocument,
          selectedClause: action.payload,
        },
      };

    case "ANALYSIS_RESET":
      return initialAnalysisState;

    default:
      return state;
  }
};

const uiReducer = (state: AppState["ui"], action: UIAction): AppState["ui"] => {
  switch (action.type) {
    case "UI_TOGGLE_SIDEBAR":
      return { ...state, sidebarOpen: !state.sidebarOpen };

    case "UI_SET_THEME":
      return { ...state, theme: action.payload };

    case "UI_ADD_NOTIFICATION":
      return {
        ...state,
        notifications: [
          ...state.notifications,
          {
            id: Math.random().toString(36).substr(2, 9),
            type: action.payload.type as
              | "info"
              | "success"
              | "warning"
              | "error",
            message: action.payload.message,
            timestamp: Date.now(),
          },
        ],
      };

    case "UI_REMOVE_NOTIFICATION":
      return {
        ...state,
        notifications: state.notifications.filter(
          (n) => n.id !== action.payload,
        ),
      };

    default:
      return state;
  }
};

const appReducer = (state: AppState, action: AppAction): AppState => {
  // Route actions to appropriate reducers
  if (action.type.startsWith("ANALYSIS_")) {
    return {
      ...state,
      analysis: analysisReducer(state.analysis, action as AnalysisAction),
    };
  }

  if (action.type.startsWith("UI_")) {
    return { ...state, ui: uiReducer(state.ui, action as UIAction) };
  }

  return state;
};

// Context
const AppStateContext = createContext<
  | {
      state: AppState;
      dispatch: React.Dispatch<AppAction>;
    }
  | undefined
>(undefined);

// Provider component
export const AppStateProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [state, dispatch] = useReducer(appReducer, initialAppState);

  return (
    <AppStateContext.Provider value={{ state, dispatch }}>
      {children}
    </AppStateContext.Provider>
  );
};

// Hook to use the app state
export const useAppState = () => {
  const context = useContext(AppStateContext);
  if (context === undefined) {
    throw new Error("useAppState must be used within an AppStateProvider");
  }
  return context;
};

// Selector hooks for specific state slices
export const useAnalysisState = () => {
  const { state } = useAppState();
  return state.analysis;
};

export const useUIState = () => {
  const { state } = useAppState();
  return state.ui;
};
