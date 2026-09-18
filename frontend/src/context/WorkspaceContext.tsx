"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { AvailableModel } from "@clauseiq/shared-types";
import apiClient from "@/lib/api";
import { clearToastCache } from "@/lib/toast";

export interface WorkspaceSettings {
  has_api_key: boolean;
  api_key_needs_reentry?: boolean;
  model_id: string;
  query_gate_model_id: string;
  available_models: AvailableModel[];
  retention_days: number;
  toast_notifications_enabled: boolean;
}

export type WorkspaceSettingsUpdate = Partial<Pick<WorkspaceSettings,
  "model_id" | "query_gate_model_id" | "retention_days" | "toast_notifications_enabled"
>>;

interface WorkspaceContextValue {
  settings: WorkspaceSettings | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  updateSettings: (settings: WorkspaceSettingsUpdate) => Promise<void>;
  saveApiKey: (apiKey: string) => Promise<void>;
  removeApiKey: () => Promise<void>;
}

const WorkspaceContext = createContext<WorkspaceContextValue | undefined>(undefined);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<WorkspaceSettings | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    const response = await apiClient.get<WorkspaceSettings>("/workspace");
    if (response.success && response.data) {
      setSettings(response.data);
      setError(null);
    } else {
      setError(response.error?.message || "Unable to connect to the local workspace.");
    }
    setIsLoading(false);
  }, []);

  useEffect(() => {
    // Discard obsolete browser credentials from the account-based application.
    try {
      localStorage.removeItem("access_token");
      localStorage.removeItem("refresh_token");
    } catch {
      // Browser storage is optional; a privacy setting must not block startup.
    }
    void refresh();
  }, [refresh]);

  const updateSettings = useCallback(async (update: WorkspaceSettingsUpdate) => {
    const response = await apiClient.put<WorkspaceSettings>("/workspace/settings", update);
    if (!response.success || !response.data) {
      throw new Error(response.error?.message || "Unable to save workspace settings.");
    }
    setSettings(response.data);
    setError(null);
    clearToastCache();
  }, []);

  const saveApiKey = useCallback(async (apiKey: string) => {
    const response = await apiClient.put<{ has_api_key: boolean }>("/workspace/api-key", { api_key: apiKey });
    if (!response.success || !response.data) {
      throw new Error(response.error?.message || "Unable to save the API key.");
    }
    setSettings((current) => current ? { ...current, has_api_key: response.data!.has_api_key, api_key_needs_reentry: false } : current);
  }, []);

  const removeApiKey = useCallback(async () => {
    const response = await apiClient.delete<{ has_api_key: boolean }>("/workspace/api-key");
    if (!response.success || !response.data) {
      throw new Error(response.error?.message || "Unable to remove the API key.");
    }
    setSettings((current) => current ? { ...current, has_api_key: response.data!.has_api_key, api_key_needs_reentry: false } : current);
  }, []);

  return <WorkspaceContext.Provider value={{ settings, isLoading, error, refresh, updateSettings, saveApiKey, removeApiKey }}>
    {children}
  </WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error("useWorkspace must be used within a WorkspaceProvider");
  return context;
}
