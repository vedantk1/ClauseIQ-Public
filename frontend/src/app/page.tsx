"use client";

import { useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FileText, Upload } from "lucide-react";
import { useAnalysis } from "@/context/AnalysisContext";
import { useWorkspace } from "@/context/WorkspaceContext";
import config from "@/config/config";
import Button from "@/components/Button";
import Card from "@/components/Card";
import ConfirmModal from "@/components/ui/ConfirmModal";

export default function Home() {
  const router = useRouter();
  const fileInput = useRef<HTMLInputElement>(null);
  const { settings, isLoading, error: workspaceError, refresh } = useWorkspace();
  const { analyzeDocument, isLoading: analyzing } = useAnalysis();
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [validation, setValidation] = useState<string | null>(null);

  const selectFile = (candidate?: File) => {
    if (!candidate || analyzing) return;
    if (!candidate.name.toLowerCase().endsWith(".pdf")) {
      setValidation("Please select a PDF document.");
      return;
    }
    if (candidate.size > config.maxFileSizeMB * 1024 * 1024) {
      setValidation(`The maximum file size is ${config.maxFileSizeMB} MB.`);
      return;
    }
    setFile(candidate);
    setError(null);
  };

  const analyze = async () => {
    if (!file || !settings?.has_api_key || analyzing) return;
    setError(null);
    try {
      const documentId = await analyzeDocument(file);
      if (!documentId) throw new Error("Analysis finished without a document. Please try again.");
      router.push(`/review?documentId=${encodeURIComponent(documentId)}`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to analyze this document. Please try again.");
    }
  };

  return <div className="max-w-4xl mx-auto px-6 py-12 space-y-8">
    <header className="space-y-3">
      <p className="text-sm text-accent-purple font-medium">Your local contract workspace</p>
      <h1 className="font-heading text-3xl md:text-4xl font-semibold">Understand an agreement</h1>
      <p className="text-text-secondary text-lg">Upload a PDF to review its clauses, explore potential risks, and ask questions grounded in the document.</p>
    </header>

    {workspaceError && <Card className="p-5 space-y-3">
      <p role="alert" className="text-accent-rose">{workspaceError}</p>
      <Button variant="secondary" onClick={() => void refresh()} loading={isLoading}>Retry connection</Button>
    </Card>}

    {!isLoading && settings && !settings.has_api_key && <Card className="p-5 border-accent-purple space-y-2">
      <h2 className="font-semibold">Add your OpenAI API key to get started</h2>
      <p className="text-sm text-text-secondary">No ClauseIQ account is needed. AI analysis sends document text to OpenAI and uses your API balance.</p>
      <Link href="/settings" className="inline-block text-accent-purple font-medium underline underline-offset-4">Open Settings</Link>
    </Card>}

    <Card className="p-6 md:p-8 space-y-6">
      <div
        onDragOver={(event) => { event.preventDefault(); if (!analyzing) setDragActive(true); }}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => { event.preventDefault(); setDragActive(false); selectFile(event.dataTransfer.files[0]); }}
        className={`border-2 border-dashed rounded-xl p-8 text-center space-y-4 ${dragActive ? "border-accent-purple bg-accent-purple/5" : "border-border-muted"}`}
      >
        <Upload className="w-9 h-9 mx-auto text-accent-purple" aria-hidden="true" />
        <div>
          <h2 className="font-semibold text-lg">Choose your agreement</h2>
          <p className="text-sm text-text-secondary mt-1">Drop one PDF here, or choose a file. Up to {config.maxFileSizeMB} MB.</p>
        </div>
        <input ref={fileInput} type="file" accept=".pdf,application/pdf" className="hidden" aria-label="Choose a PDF agreement"
          disabled={analyzing} onChange={(event) => selectFile(event.target.files?.[0])} />
        <Button variant="secondary" disabled={analyzing} onClick={() => fileInput.current?.click()}>Choose PDF</Button>
      </div>

      {file && <div className="flex items-center gap-3 p-4 bg-bg-elevated rounded-lg">
        <FileText className="w-5 h-5 shrink-0 text-accent-purple" />
        <span className="truncate flex-1 text-sm">{file.name}</span>
        <Button size="sm" variant="tertiary" disabled={analyzing} onClick={() => { setFile(null); if (fileInput.current) fileInput.current.value = ""; }}>Remove</Button>
      </div>}
      {error && <p role="alert" className="text-sm text-accent-rose">{error}</p>}
      <div className="flex flex-col sm:flex-row gap-4 sm:items-center sm:justify-between">
        <p className="text-xs text-text-secondary max-w-lg">Documents stay in your local library until you delete them, unless you opt into automatic deletion in Settings.</p>
        <Button onClick={() => void analyze()} loading={analyzing} disabled={!file || !settings?.has_api_key || isLoading || !!workspaceError}>Analyze agreement</Button>
      </div>
      {analyzing && <p role="status" aria-live="polite" className="text-sm text-text-secondary">Analyzing your agreement and preparing document chat. This can take a few minutes; keep this page open.</p>}
    </Card>

    <div className="flex flex-col sm:flex-row gap-4 justify-between text-sm text-text-secondary">
      <p>AI can make mistakes. Review findings against the source; this is not legal advice.</p>
      <Link href="/documents" className="shrink-0 text-accent-purple underline underline-offset-4">Open document library</Link>
    </div>
    <ConfirmModal isOpen={!!validation} title="Check your file" message={validation} confirmText="Got it" showCancel={false}
      onClose={() => setValidation(null)} onConfirm={() => setValidation(null)} />
  </div>;
}
