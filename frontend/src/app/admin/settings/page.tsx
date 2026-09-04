"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  adminApi,
  AutoDeleteConfig,
  AutoDeleteCleanupResult,
  DocumentLimitConfig,
  UISettingsConfig,
  SystemAIModelConfig,
  QueryGateModelConfig,
  AvailableAIModelsResponse,
} from "@/lib/adminApi";
import clsx from "clsx";
import {
  Trash2,
  Clock,
  AlertTriangle,
  Check,
  RefreshCw,
  Info,
  Play,
  FileStack,
  Bell,
  BellOff,
  Cpu,
} from "lucide-react";
import ConfirmModal from "@/components/ui/ConfirmModal";

export default function AdminSettingsPage() {
  // Auto-delete state
  const [config, setConfig] = useState<AutoDeleteConfig | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [runningCleanup, setRunningCleanup] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [cleanupResult, setCleanupResult] =
    useState<AutoDeleteCleanupResult | null>(null);
  const [confirmRunCleanupOpen, setConfirmRunCleanupOpen] = useState(false);

  // Auto-delete form state
  const [daysInput, setDaysInput] = useState<string>("30");
  const [enabled, setEnabled] = useState(true);

  // Document limit state
  const [docLimitConfig, setDocLimitConfig] =
    useState<DocumentLimitConfig | null>(null);
  const [docLimitEnabled, setDocLimitEnabled] = useState(true);
  const [maxDocsInput, setMaxDocsInput] = useState<string>("10");
  const [savingDocLimit, setSavingDocLimit] = useState(false);

  // UI settings state
  const [uiSettings, setUISettings] = useState<UISettingsConfig | null>(null);
  const [toastEnabled, setToastEnabled] = useState(true);
  const [savingUISettings, setSavingUISettings] = useState(false);

  // System AI model state
  const [systemAIModel, setSystemAIModel] =
    useState<SystemAIModelConfig | null>(null);
  const [savingSystemAIModel, setSavingSystemAIModel] = useState(false);

  // Query gate model state
  const [queryGateModel, setQueryGateModel] =
    useState<QueryGateModelConfig | null>(null);
  const [availableModels, setAvailableModels] =
    useState<AvailableAIModelsResponse | null>(null);
  const [savingQueryGateModel, setSavingQueryGateModel] = useState(false);

  const fetchConfig = useCallback(async () => {
    try {
      setLoading(true);

      // Fetch all configs in parallel
      const [
        autoDeleteResponse,
        docLimitResponse,
        uiSettingsResponse,
        systemAIModelResponse,
        queryGateResponse,
        availableModelsResponse,
      ] = await Promise.all([
        adminApi.getAutoDeleteConfig(),
        adminApi.getDocumentLimitConfig(),
        adminApi.getUISettings(),
        adminApi.getSystemAIModel(),
        adminApi.getQueryGateModel(),
        adminApi.getAvailableAIModels(),
      ]);

      if (autoDeleteResponse.success && autoDeleteResponse.data) {
        setConfig(autoDeleteResponse.data);
        setEnabled(autoDeleteResponse.data.enabled);
        setDaysInput(autoDeleteResponse.data.days.toString());
      } else {
        setError(
          autoDeleteResponse.error?.message ||
            "Failed to load auto-delete settings",
        );
      }

      if (docLimitResponse.success && docLimitResponse.data) {
        setDocLimitConfig(docLimitResponse.data);
        setDocLimitEnabled(docLimitResponse.data.enabled);
        setMaxDocsInput(docLimitResponse.data.max_documents.toString());
      }

      if (uiSettingsResponse.success && uiSettingsResponse.data) {
        setUISettings(uiSettingsResponse.data);
        setToastEnabled(uiSettingsResponse.data.toast_notifications_enabled);
      }

      if (systemAIModelResponse.success && systemAIModelResponse.data) {
        setSystemAIModel(systemAIModelResponse.data);
      }

      if (queryGateResponse.success && queryGateResponse.data) {
        setQueryGateModel(queryGateResponse.data);
      }

      if (availableModelsResponse.success && availableModelsResponse.data) {
        setAvailableModels(availableModelsResponse.data);
      }
    } catch {
      setError("Failed to connect to server");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConfig();
  }, [fetchConfig]);

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccessMessage(null);

      const days = enabled ? parseInt(daysInput, 10) : 0;

      if (enabled && (isNaN(days) || days < 1 || days > 365)) {
        setError("Days must be between 1 and 365");
        return;
      }

      const response = await adminApi.setAutoDeleteConfig(days);

      if (response.success && response.data) {
        setConfig(response.data);
        setSuccessMessage(
          days > 0
            ? `Auto-delete enabled: documents older than ${days} days will be deleted`
            : "Auto-delete disabled",
        );
        setTimeout(() => setSuccessMessage(null), 5000);
      } else {
        setError(response.error?.message || "Failed to save settings");
      }
    } catch {
      setError("Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const handleRunCleanup = () => {
    setConfirmRunCleanupOpen(true);
  };

  const handleRunCleanupConfirmed = async () => {
    try {
      setRunningCleanup(true);
      setError(null);
      setCleanupResult(null);

      const response = await adminApi.runAutoDeleteCleanup();

      if (response.success && response.data) {
        setCleanupResult(response.data);
        if (response.data.deleted_count > 0) {
          setSuccessMessage(
            `Cleanup completed: ${response.data.deleted_count} documents deleted`,
          );
        } else if (response.data.skipped) {
          setSuccessMessage(`Cleanup skipped: ${response.data.reason}`);
        } else {
          setSuccessMessage("Cleanup completed: no documents to delete");
        }
        setTimeout(() => setSuccessMessage(null), 5000);
      } else {
        setError(response.error?.message || "Failed to run cleanup");
      }
    } catch {
      setError("Failed to run cleanup");
    } finally {
      setRunningCleanup(false);
      setConfirmRunCleanupOpen(false);
    }
  };

  const handleSaveDocLimit = async () => {
    try {
      setSavingDocLimit(true);
      setError(null);
      setSuccessMessage(null);

      const maxDocs = docLimitEnabled ? parseInt(maxDocsInput, 10) : 0;

      if (
        docLimitEnabled &&
        (isNaN(maxDocs) || maxDocs < 1 || maxDocs > 1000)
      ) {
        setError("Max documents must be between 1 and 1000");
        return;
      }

      const response = await adminApi.setDocumentLimitConfig(maxDocs);

      if (response.success && response.data) {
        setDocLimitConfig(response.data);
        setSuccessMessage(
          maxDocs > 0
            ? `Document limit set to ${maxDocs} per user`
            : "Document limit disabled (unlimited)",
        );
        setTimeout(() => setSuccessMessage(null), 5000);
      } else {
        setError(response.error?.message || "Failed to save document limit");
      }
    } catch {
      setError("Failed to save document limit");
    } finally {
      setSavingDocLimit(false);
    }
  };

  const handleSaveUISettings = async () => {
    try {
      setSavingUISettings(true);
      setError(null);
      setSuccessMessage(null);

      const response = await adminApi.setUISettings(toastEnabled);

      if (response.success && response.data) {
        setUISettings(response.data);
        setSuccessMessage(
          toastEnabled
            ? "Toast notifications enabled"
            : "Toast notifications disabled",
        );
        setTimeout(() => setSuccessMessage(null), 5000);
      } else {
        setError(response.error?.message || "Failed to save UI settings");
      }
    } catch {
      setError("Failed to save UI settings");
    } finally {
      setSavingUISettings(false);
    }
  };

  const handleChangeQueryGateModel = async (modelId: string) => {
    if (modelId === queryGateModel?.model_id) return;

    setSavingQueryGateModel(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const response = await adminApi.setQueryGateModel(modelId);
      if (response.success && response.data) {
        setQueryGateModel(response.data);
        setSuccessMessage(
          `Query gate model changed to ${response.data.model_name}`,
        );
        setTimeout(() => setSuccessMessage(null), 5000);
      } else {
        setError(
          response.error?.message || "Failed to change query gate model",
        );
      }
    } catch {
      setError("Failed to change query gate model");
    } finally {
      setSavingQueryGateModel(false);
    }
  };

  const handleChangeSystemAIModel = async (modelId: string) => {
    if (modelId === systemAIModel?.model_id) return;

    setSavingSystemAIModel(true);
    setError(null);
    setSuccessMessage(null);

    try {
      const response = await adminApi.setSystemAIModel(modelId);
      if (response.success && response.data) {
        setSystemAIModel(response.data);
        setSuccessMessage(
          `System AI model changed to ${response.data.model_name}`,
        );
        setTimeout(() => setSuccessMessage(null), 5000);
      } else {
        setError(response.error?.message || "Failed to change system AI model");
      }
    } catch {
      setError("Failed to change system AI model");
    } finally {
      setSavingSystemAIModel(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="animate-pulse">
          <div className="h-8 bg-bg-surface rounded w-48 mb-6"></div>
          <div className="h-48 bg-bg-surface rounded-lg"></div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text-primary">Settings</h1>
          <p className="text-text-secondary text-sm font-mono">
            Configure system-wide settings
          </p>
        </div>
        <button
          onClick={fetchConfig}
          className="p-2 text-text-secondary hover:text-text-primary hover:bg-bg-elevated rounded-md transition-colors"
          title="Refresh"
        >
          <RefreshCw className="w-4 h-4" />
        </button>
      </div>

      {/* Error Message */}
      {error && (
        <div className="bg-accent-rose/10 border border-accent-rose/20 rounded-lg p-4 flex items-start gap-3">
          <AlertTriangle className="w-5 h-5 text-accent-rose flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-accent-rose font-mono text-sm">{error}</p>
          </div>
        </div>
      )}

      {/* Success Message */}
      {successMessage && (
        <div className="bg-accent-green/10 border border-accent-green/20 rounded-lg p-4 flex items-start gap-3">
          <Check className="w-5 h-5 text-accent-green flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-accent-green font-mono text-sm">
              {successMessage}
            </p>
          </div>
        </div>
      )}

      {/* Auto-Delete Settings Card */}
      <div className="bg-bg-surface border border-border-muted rounded-lg">
        <div className="p-4 border-b border-border-muted">
          <div className="flex items-center gap-2">
            <Trash2 className="w-5 h-5 text-accent-purple" />
            <h2 className="text-lg font-semibold text-text-primary">
              Document Auto-Delete
            </h2>
          </div>
          <p className="text-text-secondary text-sm mt-1">
            Automatically delete user documents after a specified period
          </p>
        </div>

        <div className="p-4 space-y-6">
          {/* Info Notice */}
          <div className="bg-bg-elevated/50 border border-border-muted rounded-lg p-3 flex items-start gap-3">
            <Info className="w-4 h-4 text-text-secondary flex-shrink-0 mt-0.5" />
            <div className="text-sm text-text-secondary">
              <p>
                Documents will be automatically deleted after the configured
                number of days.
              </p>
              <p className="mt-1">
                Cleanup runs automatically on server startup and can be
                triggered manually below.
              </p>
            </div>
          </div>

          {/* Enable/Disable Toggle */}
          <div className="flex items-center justify-between">
            <div>
              <label className="text-text-primary font-medium">
                Enable Auto-Delete
              </label>
              <p className="text-text-secondary text-sm">
                When enabled, documents older than the configured days will be
                deleted
              </p>
            </div>
            <button
              type="button"
              onClick={() => setEnabled(!enabled)}
              className={clsx(
                "relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-accent-purple focus:ring-offset-2 focus:ring-offset-bg-primary",
                enabled ? "bg-accent-purple" : "bg-bg-elevated",
              )}
            >
              <span
                className={clsx(
                  "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out",
                  enabled ? "translate-x-5" : "translate-x-0",
                )}
              />
            </button>
          </div>

          {/* Days Input */}
          <div className={clsx(!enabled && "opacity-50 pointer-events-none")}>
            <label className="block text-text-primary font-medium mb-2">
              <Clock className="w-4 h-4 inline mr-2" />
              Retention Period (Days)
            </label>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min="1"
                max="365"
                value={daysInput}
                onChange={(e) => setDaysInput(e.target.value)}
                disabled={!enabled}
                className="w-24 px-3 py-2 bg-bg-elevated border border-border-muted rounded-md text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-accent-purple focus:border-transparent"
              />
              <span className="text-text-secondary text-sm">days (1-365)</span>
            </div>
            <p className="text-text-secondary text-xs mt-2">
              Documents older than {daysInput || "30"} days will be
              automatically deleted
            </p>
          </div>

          {/* Current Configuration */}
          {config && (
            <div className="bg-bg-elevated/50 rounded-lg p-3 border border-border-muted">
              <h3 className="text-sm font-medium text-text-secondary mb-2">
                Current Configuration
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm font-mono">
                <div>
                  <p className="text-text-secondary text-xs">Status</p>
                  <p
                    className={clsx(
                      "font-medium",
                      config.enabled
                        ? "text-accent-green"
                        : "text-text-secondary",
                    )}
                  >
                    {config.enabled ? "Enabled" : "Disabled"}
                  </p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs">Retention</p>
                  <p className="text-text-primary">{config.days} days</p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs">Last Updated</p>
                  <p className="text-text-primary">
                    {config.configured_at
                      ? new Date(config.configured_at).toLocaleDateString()
                      : "Never"}
                  </p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs">Updated By</p>
                  <p className="text-text-primary truncate">
                    {config.updated_by || "Default"}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Save Button */}
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleSave}
              disabled={saving}
              className={clsx(
                "px-4 py-2 rounded-md font-medium text-sm transition-colors flex items-center gap-2",
                saving
                  ? "bg-bg-elevated text-text-secondary cursor-not-allowed"
                  : "bg-accent-purple text-white hover:bg-purple-600",
              )}
            >
              {saving ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Check className="w-4 h-4" />
                  Save Settings
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Document Limit Card */}
      <div className="bg-bg-surface border border-border-muted rounded-lg">
        <div className="p-4 border-b border-border-muted">
          <div className="flex items-center gap-2">
            <FileStack className="w-5 h-5 text-accent-purple" />
            <h2 className="text-lg font-semibold text-text-primary">
              User Document Limit
            </h2>
          </div>
          <p className="text-text-secondary text-sm mt-1">
            Limit the number of documents each user can store
          </p>
        </div>

        <div className="p-4 space-y-6">
          {/* Info Notice */}
          <div className="bg-bg-elevated/50 border border-border-muted rounded-lg p-3 flex items-start gap-3">
            <Info className="w-4 h-4 text-text-secondary flex-shrink-0 mt-0.5" />
            <div className="text-sm text-text-secondary">
              <p>
                Limit storage usage by restricting how many documents each user
                can analyze and store. Users who reach their limit will need to
                delete existing documents before uploading more.
              </p>
            </div>
          </div>

          {/* Enable/Disable Toggle */}
          <div className="flex items-center justify-between">
            <div>
              <label className="text-text-primary font-medium">
                Enable Document Limit
              </label>
              <p className="text-text-secondary text-sm">
                When disabled, users can store unlimited documents
              </p>
            </div>
            <button
              type="button"
              onClick={() => setDocLimitEnabled(!docLimitEnabled)}
              className={clsx(
                "relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-accent-purple focus:ring-offset-2 focus:ring-offset-bg-primary",
                docLimitEnabled ? "bg-accent-purple" : "bg-bg-elevated",
              )}
            >
              <span
                className={clsx(
                  "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out",
                  docLimitEnabled ? "translate-x-5" : "translate-x-0",
                )}
              />
            </button>
          </div>

          {/* Max Documents Input */}
          <div
            className={clsx(
              !docLimitEnabled && "opacity-50 pointer-events-none",
            )}
          >
            <label className="block text-text-primary font-medium mb-2">
              <FileStack className="w-4 h-4 inline mr-2" />
              Maximum Documents Per User
            </label>
            <div className="flex items-center gap-3">
              <input
                type="number"
                min="1"
                max="1000"
                value={maxDocsInput}
                onChange={(e) => setMaxDocsInput(e.target.value)}
                disabled={!docLimitEnabled}
                className="w-24 px-3 py-2 bg-bg-elevated border border-border-muted rounded-md text-text-primary font-mono focus:outline-none focus:ring-2 focus:ring-accent-purple focus:border-transparent"
              />
              <span className="text-text-secondary text-sm">
                documents (1-1000)
              </span>
            </div>
            <p className="text-text-secondary text-xs mt-2">
              Users will be blocked from uploading when they reach{" "}
              {maxDocsInput || "10"} documents
            </p>
          </div>

          {/* Current Configuration */}
          {docLimitConfig && (
            <div className="bg-bg-elevated/50 rounded-lg p-3 border border-border-muted">
              <h3 className="text-sm font-medium text-text-secondary mb-2">
                Current Configuration
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm font-mono">
                <div>
                  <p className="text-text-secondary text-xs">Status</p>
                  <p
                    className={clsx(
                      "font-medium",
                      docLimitConfig.enabled
                        ? "text-accent-green"
                        : "text-text-secondary",
                    )}
                  >
                    {docLimitConfig.enabled ? "Enabled" : "Unlimited"}
                  </p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs">Max Docs</p>
                  <p className="text-text-primary">
                    {docLimitConfig.enabled
                      ? docLimitConfig.max_documents
                      : "∞"}
                  </p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs">Last Updated</p>
                  <p className="text-text-primary">
                    {docLimitConfig.configured_at
                      ? new Date(
                          docLimitConfig.configured_at,
                        ).toLocaleDateString()
                      : "Never"}
                  </p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs">Updated By</p>
                  <p className="text-text-primary truncate">
                    {docLimitConfig.updated_by || "Default"}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Save Button */}
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleSaveDocLimit}
              disabled={savingDocLimit}
              className={clsx(
                "px-4 py-2 rounded-md font-medium text-sm transition-colors flex items-center gap-2",
                savingDocLimit
                  ? "bg-bg-elevated text-text-secondary cursor-not-allowed"
                  : "bg-accent-purple text-white hover:bg-purple-600",
              )}
            >
              {savingDocLimit ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Check className="w-4 h-4" />
                  Save Limit
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* UI Settings Card */}
      <div className="bg-bg-surface border border-border-muted rounded-lg">
        <div className="p-4 border-b border-border-muted">
          <div className="flex items-center gap-2">
            {toastEnabled ? (
              <Bell className="w-5 h-5 text-accent-purple" />
            ) : (
              <BellOff className="w-5 h-5 text-text-secondary" />
            )}
            <h2 className="text-lg font-semibold text-text-primary">
              Toast Notifications
            </h2>
          </div>
          <p className="text-text-secondary text-sm mt-1">
            Control whether toast notifications are shown to users
          </p>
        </div>

        <div className="p-4 space-y-6">
          {/* Info Notice */}
          <div className="bg-bg-elevated/50 border border-border-muted rounded-lg p-3 flex items-start gap-3">
            <Info className="w-4 h-4 text-text-secondary flex-shrink-0 mt-0.5" />
            <div className="text-sm text-text-secondary">
              <p>
                Toast notifications are small popup messages that appear in the
                corner of the screen to inform users about actions (success,
                errors, etc.).
              </p>
              <p className="mt-1">
                Disabling this will hide most toast messages. Critical errors
                and modals will still appear.
              </p>
            </div>
          </div>

          {/* Enable/Disable Toggle */}
          <div className="flex items-center justify-between">
            <div>
              <label className="text-text-primary font-medium">
                Enable Toast Notifications
              </label>
              <p className="text-text-secondary text-sm">
                When disabled, users won&apos;t see popup notifications
              </p>
            </div>
            <button
              type="button"
              onClick={() => setToastEnabled(!toastEnabled)}
              className={clsx(
                "relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-accent-purple focus:ring-offset-2 focus:ring-offset-bg-primary",
                toastEnabled ? "bg-accent-purple" : "bg-bg-elevated",
              )}
            >
              <span
                className={clsx(
                  "pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out",
                  toastEnabled ? "translate-x-5" : "translate-x-0",
                )}
              />
            </button>
          </div>

          {/* Current Configuration */}
          {uiSettings && (
            <div className="bg-bg-elevated/50 rounded-lg p-3 border border-border-muted">
              <h3 className="text-sm font-medium text-text-secondary mb-2">
                Current Configuration
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm font-mono">
                <div>
                  <p className="text-text-secondary text-xs">Status</p>
                  <p
                    className={clsx(
                      "font-medium",
                      uiSettings.toast_notifications_enabled
                        ? "text-accent-green"
                        : "text-text-secondary",
                    )}
                  >
                    {uiSettings.toast_notifications_enabled
                      ? "Enabled"
                      : "Disabled"}
                  </p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs">Last Updated</p>
                  <p className="text-text-primary">
                    {uiSettings.configured_at
                      ? new Date(uiSettings.configured_at).toLocaleDateString()
                      : "Never"}
                  </p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs">Updated By</p>
                  <p className="text-text-primary truncate">
                    {uiSettings.updated_by || "Default"}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Save Button */}
          <div className="flex items-center gap-3 pt-2">
            <button
              onClick={handleSaveUISettings}
              disabled={savingUISettings}
              className={clsx(
                "px-4 py-2 rounded-md font-medium text-sm transition-colors flex items-center gap-2",
                savingUISettings
                  ? "bg-bg-elevated text-text-secondary cursor-not-allowed"
                  : "bg-accent-purple text-white hover:bg-purple-600",
              )}
            >
              {savingUISettings ? (
                <>
                  <RefreshCw className="w-4 h-4 animate-spin" />
                  Saving...
                </>
              ) : (
                <>
                  <Check className="w-4 h-4" />
                  Save Settings
                </>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* System AI Model Card */}
      <div className="bg-bg-surface border border-border-muted rounded-lg">
        <div className="p-4 border-b border-border-muted">
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-accent-purple" />
            <h2 className="text-lg font-semibold text-text-primary">
              System AI Model
            </h2>
          </div>
          <p className="text-text-secondary text-sm mt-1">
            Select the AI model used for document analysis across the system
          </p>
        </div>

        <div className="p-4 space-y-6">
          <div className="bg-bg-elevated/50 border border-border-muted rounded-lg p-3 flex items-start gap-3">
            <Info className="w-4 h-4 text-text-secondary flex-shrink-0 mt-0.5" />
            <p className="text-sm text-text-secondary">
              This setting applies to every user and controls the model used to
              analyze uploaded documents.
            </p>
          </div>

          {systemAIModel && (
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium bg-accent-purple/10 text-accent-purple">
              <Check className="w-4 h-4" />
              Current: {systemAIModel.model_name}
            </div>
          )}

          {systemAIModel?.configured_at && (
            <p className="text-xs text-text-secondary font-mono">
              Last changed:{" "}
              {new Date(systemAIModel.configured_at).toLocaleString()}
              {systemAIModel.updated_by && ` by ${systemAIModel.updated_by}`}
            </p>
          )}

          <div className="grid gap-3">
            {availableModels?.models.map((model) => (
              <button
                key={model.id}
                onClick={() => handleChangeSystemAIModel(model.id)}
                disabled={
                  savingSystemAIModel || model.id === systemAIModel?.model_id
                }
                className={clsx(
                  "w-full p-4 rounded-lg border text-left transition-all",
                  model.id === systemAIModel?.model_id
                    ? "border-accent-purple bg-accent-purple/5 cursor-default"
                    : "border-border-muted hover:border-accent-purple/50 hover:bg-bg-elevated cursor-pointer",
                  savingSystemAIModel &&
                    model.id !== systemAIModel?.model_id &&
                    "opacity-50 cursor-not-allowed",
                )}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-text-primary">
                        {model.name}
                      </span>
                      {model.id === systemAIModel?.model_id && (
                        <span className="px-2 py-0.5 text-xs font-medium bg-accent-purple text-white rounded">
                          Active
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-text-secondary mt-1">
                      {model.description}
                    </p>
                  </div>
                  {savingSystemAIModel &&
                    model.id !== systemAIModel?.model_id && (
                      <RefreshCw className="w-4 h-4 animate-spin text-text-secondary" />
                    )}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Query Gate + Rewrite Model Card */}
      <div className="bg-bg-surface border border-border-muted rounded-lg">
        <div className="p-4 border-b border-border-muted">
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-accent-purple" />
            <h2 className="text-lg font-semibold text-text-primary">
              Query Gate + Rewrite Model
            </h2>
          </div>
          <p className="text-text-secondary text-sm mt-1">
            Select the AI model used for both query gate detection and query rewrite
            during chat
          </p>
        </div>

        <div className="p-4 space-y-6">
          {/* Info Notice */}
          <div className="bg-bg-elevated/50 border border-border-muted rounded-lg p-3 flex items-start gap-3">
            <Info className="w-4 h-4 text-text-secondary flex-shrink-0 mt-0.5" />
            <div className="text-sm text-text-secondary">
              <p>
                This model is used for both: (1) query gate checks that determine
                if a user&apos;s chat question needs previous conversation context, and
                (2) query rewrite when follow-up questions need clarification.
              </p>
              <p className="mt-1">
                A faster, cheaper model like GPT-5 Nano is recommended since these
                are lightweight helper calls.
              </p>
            </div>
          </div>

          {/* Current Model Badge */}
          {queryGateModel && (
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-sm font-medium bg-accent-purple/10 text-accent-purple">
              <Check className="w-4 h-4" />
              Current: {queryGateModel.model_name}
            </div>
          )}

          {queryGateModel?.configured_at && (
            <p className="text-xs text-text-secondary font-mono">
              Last changed:{" "}
              {new Date(queryGateModel.configured_at).toLocaleString()}
              {queryGateModel.updated_by && ` by ${queryGateModel.updated_by}`}
            </p>
          )}

          {/* Model Selection */}
          <div className="grid gap-3">
            {availableModels?.models.map((model) => (
              <button
                key={model.id}
                onClick={() => handleChangeQueryGateModel(model.id)}
                disabled={
                  savingQueryGateModel || model.id === queryGateModel?.model_id
                }
                className={clsx(
                  "w-full p-4 rounded-lg border text-left transition-all",
                  model.id === queryGateModel?.model_id
                    ? "border-accent-purple bg-accent-purple/5 cursor-default"
                    : "border-border-muted hover:border-accent-purple/50 hover:bg-bg-elevated cursor-pointer",
                  savingQueryGateModel &&
                    model.id !== queryGateModel?.model_id &&
                    "opacity-50 cursor-not-allowed",
                )}
              >
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-text-primary">
                        {model.name}
                      </span>
                      {model.id === queryGateModel?.model_id && (
                        <span className="px-2 py-0.5 text-xs font-medium bg-accent-purple text-white rounded">
                          Active
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-text-secondary mt-1">
                      {model.description}
                    </p>
                  </div>
                  {savingQueryGateModel &&
                    model.id !== queryGateModel?.model_id && (
                      <RefreshCw className="w-4 h-4 animate-spin text-text-secondary" />
                    )}
                </div>
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Manual Cleanup Card */}
      <div className="bg-bg-surface border border-border-muted rounded-lg">
        <div className="p-4 border-b border-border-muted">
          <div className="flex items-center gap-2">
            <Play className="w-5 h-5 text-accent-purple" />
            <h2 className="text-lg font-semibold text-text-primary">
              Manual Cleanup
            </h2>
          </div>
          <p className="text-text-secondary text-sm mt-1">
            Manually trigger the document cleanup process
          </p>
        </div>

        <div className="p-4 space-y-4">
          {/* Cleanup Result */}
          {cleanupResult && (
            <div
              className={clsx(
                "rounded-lg p-3 border",
                cleanupResult.errors.length > 0
                  ? "bg-accent-rose/10 border-accent-rose/20"
                  : "bg-accent-green/10 border-accent-green/20",
              )}
            >
              <h3 className="text-sm font-medium mb-2 text-text-primary">
                Last Cleanup Result
              </h3>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm font-mono">
                <div>
                  <p className="text-text-secondary text-xs">Deleted</p>
                  <p className="text-text-primary">
                    {cleanupResult.deleted_count}
                  </p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs">Failed</p>
                  <p
                    className={clsx(
                      cleanupResult.failed_count > 0
                        ? "text-accent-rose"
                        : "text-text-primary",
                    )}
                  >
                    {cleanupResult.failed_count}
                  </p>
                </div>
                <div>
                  <p className="text-text-secondary text-xs">Run At</p>
                  <p className="text-text-primary">
                    {new Date(cleanupResult.run_at).toLocaleTimeString()}
                  </p>
                </div>
                {cleanupResult.skipped && (
                  <div>
                    <p className="text-text-secondary text-xs">Skipped</p>
                    <p className="text-text-primary">{cleanupResult.reason}</p>
                  </div>
                )}
              </div>
              {cleanupResult.errors.length > 0 && (
                <div className="mt-2 text-xs text-accent-rose">
                  Errors: {cleanupResult.errors.join(", ")}
                </div>
              )}
            </div>
          )}

          <button
            onClick={handleRunCleanup}
            disabled={runningCleanup || !config?.enabled}
            className={clsx(
              "px-4 py-2 rounded-md font-medium text-sm transition-colors flex items-center gap-2",
              runningCleanup || !config?.enabled
                ? "bg-bg-elevated text-text-secondary cursor-not-allowed"
                : "bg-accent-rose/20 text-accent-rose hover:bg-accent-rose/30 border border-accent-rose/30",
            )}
          >
            {runningCleanup ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Running Cleanup...
              </>
            ) : (
              <>
                <Trash2 className="w-4 h-4" />
                Run Cleanup Now
              </>
            )}
          </button>

          {!config?.enabled && (
            <p className="text-text-secondary text-xs">
              Enable auto-delete above to run manual cleanup
            </p>
          )}
        </div>
      </div>

      <ConfirmModal
        isOpen={confirmRunCleanupOpen}
        title="Run Cleanup"
        message={
          runningCleanup ? (
            <>Running cleanup... Please wait.</>
          ) : (
            <>
              Are you sure you want to run the cleanup now? This will delete all documents older than the configured period.
            </>
          )
        }
        confirmText={runningCleanup ? "Running..." : "Run Cleanup"}
        confirmVariant="danger"
        loading={runningCleanup}
        onClose={() => {
          if (runningCleanup) return;
          setConfirmRunCleanupOpen(false);
        }}
        onConfirm={() => {
          void handleRunCleanupConfirmed();
        }}
      />
    </div>
  );
}
