"use client";

import { useEffect, useState } from "react";
import type { AvailableModel } from "@clauseiq/shared-types";
import { useWorkspace, type WorkspaceSettingsUpdate } from "@/context/WorkspaceContext";
import { effortForModel, formatModelRate, getModelSelectionError, getSelectableModels, reasoningLabel } from "@/lib/modelSelection";
import Button from "@/components/Button";
import Card from "@/components/Card";
import ConfirmModal from "@/components/ui/ConfirmModal";
import styles from "./Settings.module.css";

const inputClass = "w-full bg-bg-elevated border border-border-muted rounded-md px-3 py-2 text-text-primary focus:outline-none focus:ring-2 focus:ring-accent-purple disabled:opacity-50";

function ModelDetails({ model }: { model: AvailableModel }) {
  return <details className={styles.modelDetails}>
    <summary>Model details and reference pricing</summary>
    <div className="space-y-2 text-sm text-text-secondary">
    <p>{model.description}</p>
    <p>Model ID: <code className="break-all text-text-primary">{model.id}</code></p>
    <p>Base price per 1 million tokens (USD): {formatModelRate(model.input_price_per_million)} input · {formatModelRate(model.output_price_per_million)} output.</p>
    <p className="text-xs">Reference prices checked {model.pricing_verified_on}, not a quote for a document. {model.pricing_note} <a className="text-accent-purple underline" href="https://developers.openai.com/api/docs/pricing" target="_blank" rel="noopener noreferrer">Check OpenAI pricing</a>.</p>
    {model.legacy && <p className="text-xs text-accent-amber">Your saved legacy model is preserved. Choose another model explicitly when you are ready to change it.</p>}
    </div>
  </details>;
}

export default function Settings() {
  const { settings, isLoading, error: connectionError, refresh, updateSettings, saveApiKey, removeApiKey } = useWorkspace();
  const [apiKey, setApiKey] = useState("");
  const [modelId, setModelId] = useState("");
  const [reasoningEffort, setReasoningEffort] = useState("medium");
  const [queryModelId, setQueryModelId] = useState("");
  const [retentionEnabled, setRetentionEnabled] = useState(false);
  const [retentionDays, setRetentionDays] = useState("30");
  const [toastsEnabled, setToastsEnabled] = useState(true);
  const [saving, setSaving] = useState<"key" | "settings" | "remove" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [pendingSettings, setPendingSettings] = useState<WorkspaceSettingsUpdate | null>(null);
  const models = settings?.available_models ?? [];
  const reviewModel = models.find((model) => model.id === modelId);
  const queryModel = models.find((model) => model.id === queryModelId);
  const selectionError = getModelSelectionError(models, modelId, queryModelId, reasoningEffort);

  useEffect(() => { setModelId(settings?.model_id || ""); }, [settings?.model_id]);
  useEffect(() => { setReasoningEffort(settings?.reasoning_effort || "medium"); }, [settings?.reasoning_effort]);
  useEffect(() => { setQueryModelId(settings?.query_gate_model_id || ""); }, [settings?.query_gate_model_id]);
  useEffect(() => {
    setRetentionEnabled((settings?.retention_days || 0) > 0);
    setRetentionDays(String(settings?.retention_days || 30));
  }, [settings?.retention_days]);
  useEffect(() => { setToastsEnabled(settings?.toast_notifications_enabled ?? true); }, [settings?.toast_notifications_enabled]);

  const saveKey = async () => {
    if (!apiKey.trim()) { setError("Enter your OpenAI API key."); return; }
    setSaving("key"); setError(null); setMessage(null);
    try {
      await saveApiKey(apiKey.trim());
      setApiKey("");
      setMessage("API key saved locally. It will be used for future AI requests.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to save the API key.");
    } finally { setSaving(null); }
  };

  const deleteKey = async () => {
    setSaving("remove"); setError(null); setMessage(null);
    try {
      await removeApiKey();
      setApiKey("");
      setConfirmRemove(false);
      setMessage("API key removed. Saved documents remain available.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to remove the API key.");
      setConfirmRemove(false);
    } finally { setSaving(null); }
  };

  const saveSettings = async (update: WorkspaceSettingsUpdate) => {
    setSaving("settings"); setError(null); setMessage(null);
    try {
      await updateSettings(update);
      setMessage("Workspace settings saved.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to save settings.");
    } finally { setSaving(null); setPendingSettings(null); }
  };

  const requestSettingsSave = () => {
    if (selectionError) { setError(selectionError); return; }
    const days = retentionEnabled ? Number(retentionDays) : 0;
    if (!Number.isInteger(days) || days > 36500 || (retentionEnabled && days < 1)) {
      setError("Enter a whole number of days from 1 to 36500, or turn automatic deletion off.");
      return;
    }
    const update = { model_id: modelId, reasoning_effort: reasoningEffort, query_gate_model_id: queryModelId, retention_days: days, toast_notifications_enabled: toastsEnabled };
    if (days > 0 && days !== settings?.retention_days) setPendingSettings(update);
    else void saveSettings(update);
  };

  if (isLoading && !settings) return <div className={styles.page} role="status">Loading workspace settings…</div>;

  return <div className={styles.page}>
    <header className={styles.intro}>
      <h1>Settings</h1>
      <p>Manage AI access and how your local workspace keeps its documents.</p>
    </header>
    <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <nav aria-label="Settings sections">
          <a href="#ai-access">OpenAI API key</a>
          <a href="#ai-models">AI models</a>
          <a href="#document-library">Document library</a>
          <a href="#notifications">Notifications</a>
        </nav>
        <p>One local workspace. No account or administrator setup.</p>
        <p>Importing, reading and saving your own work do not use AI.</p>
      </aside>
      <div className={styles.content}>
    {connectionError && <Card className="p-5 space-y-3"><p role="alert" className="text-accent-rose">{connectionError}</p><Button variant="secondary" onClick={() => void refresh()} loading={isLoading}>Retry connection</Button></Card>}
    {error && <p role="alert" className="text-accent-rose bg-accent-rose/10 rounded-lg p-4">{error}</p>}
    {message && <p role="status" className="text-accent-green bg-accent-green/10 rounded-lg p-4">{message}</p>}

    {settings && <>
      <section id="ai-access" aria-labelledby="ai-access-title" className={styles.section}>
        <div className={styles.sectionHeading}><div><h2 id="ai-access-title">OpenAI API key</h2><p>{settings.has_api_key ? "Enter a replacement only if you want to change the saved key." : "Add your own key when you are ready to run a review or ask AI."}</p></div><span className={styles.status}>{settings.has_api_key ? "Key saved locally" : "No key saved"}</span></div>
        {settings.api_key_needs_reentry && <p role="alert" className="text-sm text-accent-amber">The previous key could not be restored. Enter your OpenAI API key again; your saved documents are unchanged.</p>}
        <p className="text-sm text-text-secondary">The key is stored encrypted by your local backend, not in browser storage. AI requests send document text to OpenAI and incur charges on your API account. Saving a key does not run an AI request.</p>
        <form onSubmit={(event) => { event.preventDefault(); void saveKey(); }} className="space-y-3">
          <label htmlFor="openai-key" className="block text-sm font-medium">{settings.has_api_key ? "Replacement API key" : "API key"}</label>
          <input id="openai-key" type="password" value={apiKey} autoComplete="off" spellCheck={false} className={inputClass} placeholder="Enter your OpenAI API key" disabled={!!saving}
            onChange={(event) => setApiKey(event.target.value)} />
          <div className="flex flex-wrap gap-3">
            <Button type="submit" loading={saving === "key"} disabled={!apiKey.trim() || !!saving}>{settings.has_api_key ? "Replace key" : "Save key"}</Button>
            {settings.has_api_key && <Button type="button" variant="secondary" disabled={!!saving} onClick={() => setConfirmRemove(true)}>Remove key</Button>}
          </div>
        </form>
      </section>

      <form onSubmit={(event) => { event.preventDefault(); requestSettingsSave(); }} className={styles.settingsForm}>
        <section id="ai-models" aria-labelledby="ai-models-title" className={styles.section}>
          <div className={styles.sectionHeading}><div><h2 id="ai-models-title">AI models</h2><p>Choose deliberately. Saving a selection does not start or rerun a review.</p></div></div>
          <label htmlFor="analysis-model" className="block text-sm font-medium">Review model</label>
          <p id="review-model-help" className="text-sm text-text-secondary">Used for reviews and finding-scoped Ask, as well as earlier analysis, summaries, clause rewrites and chat answers.</p>
          <select id="analysis-model" value={modelId} className={inputClass} aria-describedby="review-model-help" aria-invalid={!reviewModel} disabled={!!saving} onChange={(event) => {
            const next = models.find(model => model.id === event.target.value);
            setModelId(event.target.value);
            if (next) {
              const effort = effortForModel(next, reasoningEffort);
              if (effort !== reasoningEffort) setMessage(`${next.name} does not support ${reasoningLabel(reasoningEffort)} reasoning. Set to ${reasoningLabel(effort)}; save to apply.`);
              setReasoningEffort(effort);
            }
          }}>
            {!reviewModel && <option value={modelId} disabled>{modelId ? `Unavailable model: ${modelId}` : "Choose a review model"}</option>}
            {getSelectableModels(models, modelId).map((model) => <option key={model.id} value={model.id}>{model.name}{model.legacy ? " (saved legacy model)" : ""}</option>)}
          </select>
          <label htmlFor="reasoning-effort" className="block text-sm font-medium">Reasoning effort</label>
          <select id="reasoning-effort" value={reasoningEffort} className={inputClass} aria-describedby="reasoning-help" disabled={!!saving || !reviewModel}
            onChange={event => setReasoningEffort(event.target.value)}>
            {reviewModel && !reviewModel.reasoning_efforts.includes(reasoningEffort) && <option value={reasoningEffort} disabled>Unsupported effort: {reasoningEffort}</option>}
            {reviewModel?.reasoning_efforts.map(effort => <option key={effort} value={effort}>{reasoningLabel(effort)}{effort === "medium" ? " (recommended)" : ""}</option>)}
          </select>
          <p id="reasoning-help" className="text-sm text-text-secondary">Medium is a good starting point. Higher effort can use more time and billed reasoning tokens; it does not guarantee a better answer. The same request limits still apply.</p>
          {reviewModel && <ModelDetails model={reviewModel} />}
          <p className="text-xs text-text-secondary">Changes apply to new AI requests after saving. Saved analyses are not automatically rerun. ClauseIQ will not silently switch models or fall back to a more expensive option. Your API account must have access to the selected model.</p>
          {selectionError && <p role="alert" className="text-sm text-accent-amber">{selectionError}</p>}
          <details className="pt-2">
            <summary className="cursor-pointer text-sm text-text-secondary">Advanced: chat query classification</summary>
            <div className="space-y-3 pt-4">
              <label htmlFor="query-model" className="block text-sm font-medium">Chat query classification model</label>
              <select id="query-model" value={queryModelId} className={inputClass} aria-invalid={!queryModel} disabled={!!saving} onChange={(event) => setQueryModelId(event.target.value)}>
                {!queryModel && <option value={queryModelId} disabled>{queryModelId ? `Unavailable model: ${queryModelId}` : "Choose a classification model"}</option>}
                {getSelectableModels(models, queryModelId).map((model) => <option key={model.id} value={model.id}>{model.name}{model.legacy ? " (saved legacy model)" : ""}</option>)}
              </select>
              <p className="text-xs text-text-secondary">This separate model prepares earlier-analysis chat questions at Low reasoning effort. Changing the review model or effort does not change this selection. Finding-scoped Ask uses the review model and effort directly.</p>
              {queryModel && <ModelDetails model={queryModel} />}
            </div>
          </details>
        </section>

        <section id="document-library" aria-labelledby="document-library-title" className={styles.section}>
          <div className={styles.sectionHeading}><div><h2 id="document-library-title">Document library</h2><p>Keep your agreements until you decide to remove them.</p></div></div>
          <p className="text-sm text-text-secondary">There is no document-count cap. Automatic deletion is off by default, so documents stay until you choose to delete them.</p>
          <label className="flex gap-3 items-start cursor-pointer"><input type="checkbox" checked={retentionEnabled} disabled={!!saving} className="mt-1" onChange={(event) => setRetentionEnabled(event.target.checked)} /><span>Automatically delete older documents</span></label>
          {retentionEnabled && <div className="space-y-2">
            <label htmlFor="retention-days" className="block text-sm font-medium">Delete documents this many days after upload</label>
            <input id="retention-days" type="number" min="1" max="36500" step="1" value={retentionDays} disabled={!!saving} className={inputClass} onChange={(event) => setRetentionDays(event.target.value)} />
            <p className="text-sm text-accent-amber">Deletion permanently removes the original PDF, analysis, notes, chat history, and vector data. Existing older documents are included.</p>
          </div>}
        </section>

        <section id="notifications" aria-labelledby="notifications-title" className={styles.section}>
          <h2 id="notifications-title">Notifications</h2>
          <label className="flex items-center gap-3 cursor-pointer"><input type="checkbox" checked={toastsEnabled} disabled={!!saving} onChange={(event) => setToastsEnabled(event.target.checked)} /><span>Show pop-up notifications</span></label>
        </section>
        <div className={styles.saveBar}><p>Model, library and notification changes take effect after saving.</p><Button type="submit" loading={saving === "settings"} disabled={!!saving || !!connectionError}>Save workspace settings</Button></div>
      </form>
    </>}
      </div>
    </div>

    <ConfirmModal isOpen={confirmRemove} title="Remove your API key?" message="AI features will stop working until you add a key again. Existing documents, notes, and saved results will remain."
      confirmText="Remove key" confirmVariant="danger" loading={saving === "remove"} onClose={() => setConfirmRemove(false)} onConfirm={() => void deleteKey()} />
    <ConfirmModal isOpen={!!pendingSettings} title="Enable automatic deletion?" message={`Documents uploaded more than ${pendingSettings?.retention_days ?? 0} days ago, including documents already in your library, will be eligible for permanent deletion. Their PDFs, analyses, notes, chat history, and vector data cannot be restored from ClauseIQ. Back up anything you need before continuing.`}
      confirmText="Enable and save" confirmVariant="danger" loading={saving === "settings"} onClose={() => setPendingSettings(null)} onConfirm={() => { if (pendingSettings) void saveSettings(pendingSettings); }} />
  </div>;
}
