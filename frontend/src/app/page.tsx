"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useAnalysis } from "@/context/AnalysisContext";
import { useAuthRedirect } from "@/hooks/useAuthRedirect";
import config from "@/config/config";
import Button from "@/components/Button";
import Card from "@/components/Card";
import clsx from "clsx";
import apiClient from "@/lib/api";
import toast from "@/lib/toast";
import ConfirmModal from "@/components/ui/ConfirmModal";

export default function Home() {
  const { isAuthenticated } = useAuthRedirect();
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const router = useRouter();
  const {
    analyzeDocument,
    resetAnalysis,
    isLoading: analysisLoading,
  } = useAnalysis();

  // API key status state
  const [hasApiKey, setHasApiKey] = useState<boolean | null>(null);
  const [checkingApiKey, setCheckingApiKey] = useState(false);

  // Analysis progress state
  const [analysisProgress, setAnalysisProgress] = useState(0);
  const [analysisStep, setAnalysisStep] = useState("");

  // Document limit modal state
  const [showLimitModal, setShowLimitModal] = useState(false);
  const [documentLimitInfo, setDocumentLimitInfo] = useState<{
    current: number;
    max: number;
  } | null>(null);

  // Validation modal state (avoid window.alert which can be blocked by the browser)
  const [validationModal, setValidationModal] = useState<{
    title: string;
    message: string;
  } | null>(null);

  // Fetch API key status when authenticated
  useEffect(() => {
    const fetchApiKeyStatus = async () => {
      if (!isAuthenticated) {
        setHasApiKey(null);
        return;
      }

      setCheckingApiKey(true);
      try {
        const response = await apiClient.get<{ has_api_key: boolean }>("/auth/api-key/status");
        if (response.success && response.data) {
          setHasApiKey(response.data.has_api_key ?? false);
        }
      } catch {
        console.error("Failed to check API key status:");
        setHasApiKey(false);
      } finally {
        setCheckingApiKey(false);
      }
    };

    fetchApiKeyStatus();
  }, [isAuthenticated]);

  // Keep the native file input in sync when the selected file is cleared
  useEffect(() => {
    if (!file && fileInputRef.current?.value) {
      fileInputRef.current.value = "";
    }
  }, [file]);

  const handleFileChange = (selectedFile: File | null) => {

    if (!selectedFile) {
      console.warn("⚠️ [DEBUG] No file provided to handleFileChange");
      return;
    }

    try {
      // File size validation
      const maxSizeBytes = config.maxFileSizeMB * 1024 * 1024;
      if (selectedFile.size > maxSizeBytes) {
        console.error("❌ [DEBUG] File too large:");
      setValidationModal({
        title: "File Too Large",
        message: `File is too large. Max size: ${config.maxFileSizeMB}MB.`,
      });
      return;
    }

      // File type validation
    if (!selectedFile.name.toLowerCase().endsWith(".pdf")) {
        console.error("❌ [DEBUG] Invalid file type:");
      setValidationModal({
        title: "Invalid File Type",
        message: "Please upload a PDF file.",
      });
      return;
    }

    setFile(selectedFile);

    } catch {
      console.error("❌ [DEBUG] Error in handleFileChange:");
    }
  };

  const handleRemoveFile = () => {

    resetAnalysis();
    setFile(null);

    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }

  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;

    try {
      if (files && files.length > 0) {
        handleFileChange(files[0]);
    } else {
        console.warn("⚠️ [DEBUG] onChange fired but no files selected");
      }
    } catch {
      console.error("❌ [DEBUG] Error in handleInputChange:");
    }
  };

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();


    if (e.type === "dragenter" || e.type === "dragover") {
      // Only activate if dragging files
      if (e.dataTransfer?.types?.includes("Files")) {
      setDragActive(true);
      }
    } else if (e.type === "dragleave") {
      // Only deactivate if leaving the entire drop zone
      const rect = e.currentTarget.getBoundingClientRect();
      const x = e.clientX;
      const y = e.clientY;

      if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
      setDragActive(false);
      }
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);

    const droppedFiles = Array.from(e.dataTransfer.files);

    if (droppedFiles.length === 0) {
      console.warn("⚠️ [DEBUG] Drop event but no files found");
      return;
    }

    if (droppedFiles.length > 1) {
      console.warn("⚠️ [DEBUG] Multiple files dropped, using first file only:");
    }

    handleFileChange(droppedFiles[0]);
  };

  const handleProcessDocument = async () => {

    if (!file) {
      console.error("❌ [DEBUG] No file to process");
      return;
    }

    if (!isAuthenticated) {
      toast.error("Please sign in to analyze documents");
      router.push("/login");
      return;
    }

    // Check if user has API key set
    if (hasApiKey === false) {
      toast.error("Please add your OpenAI API key in Settings before analyzing documents.", {
        duration: 5000,
      });
      router.push("/settings");
      return;
    }

    // Reset and start progress simulation
    setAnalysisProgress(0);
    setAnalysisStep("Uploading document...");

    // Simulate progress steps while actual API call runs
    const progressSteps = [
      { progress: 10, step: "Uploading document...", delay: 500 },
      { progress: 20, step: "Extracting text from PDF...", delay: 1500 },
      { progress: 35, step: "Analyzing contract structure...", delay: 3000 },
      { progress: 50, step: "Identifying clauses with AI...", delay: 5000 },
      { progress: 65, step: "Assessing risk levels...", delay: 7000 },
      { progress: 75, step: "Generating summary...", delay: 9000 },
      { progress: 85, step: "Processing for chat...", delay: 11000 },
      { progress: 90, step: "Finalizing analysis...", delay: 13000 },
    ];

    // Start progress simulation
    const progressTimeouts: NodeJS.Timeout[] = [];
    progressSteps.forEach(({ progress, step, delay }) => {
      const timeout = setTimeout(() => {
        setAnalysisProgress(progress);
        setAnalysisStep(step);
      }, delay);
      progressTimeouts.push(timeout);
    });

    try {
      const documentId = await analyzeDocument(file);

      // Clear all pending progress timeouts
      progressTimeouts.forEach(clearTimeout);

      if (documentId) {
        // Complete progress
        setAnalysisProgress(100);
        setAnalysisStep("Analysis complete!");


        // Brief delay to show completion, then redirect
        setTimeout(() => {
          setAnalysisProgress(0);
          setAnalysisStep("");
          window.open(`/review?documentId=${documentId}`, "_blank");
        }, 500);
      } else {
        setAnalysisProgress(0);
        setAnalysisStep("");
        console.error("❌ [DEBUG] Analysis complete but no document ID found");
        toast.error("Document processed but unable to open review page.");
      }
    } catch (error) {
      // Clear all pending progress timeouts
      progressTimeouts.forEach(clearTimeout);
      setAnalysisProgress(0);
      setAnalysisStep("");

      console.error("❌ [DEBUG] Document analysis failed:");

      const errorMessage = error instanceof Error ? error.message : String(error);

      // Check if error is about document limit - show modal instead of toast
      if (errorMessage.includes("DOCUMENT_LIMIT_REACHED") || errorMessage.includes("Document limit reached")) {
        // Parse the count from the message if possible (e.g., "You have 10/10 documents")
        const match = errorMessage.match(/(\d+)\/(\d+)/);
        if (match) {
          setDocumentLimitInfo({ current: parseInt(match[1]), max: parseInt(match[2]) });
        } else {
          setDocumentLimitInfo({ current: 10, max: 10 }); // Default fallback
        }
        setShowLimitModal(true);
        return;
      }

      // Check if error is about API key
      if (errorMessage.includes("API_KEY_REQUIRED") || errorMessage.includes("API key")) {
        toast.error("Please add your OpenAI API key in Settings.", { duration: 5000 });
        router.push("/settings");
      } else {
        toast.error("Failed to process document. Please try again.");
      }
    }
  };

  return (
    <div className="min-h-screen bg-bg-primary">
      {/* Document Limit Modal */}
      {showLimitModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-black/60 backdrop-blur-sm"
            onClick={() => setShowLimitModal(false)}
          />

          {/* Modal */}
          <div className="relative bg-bg-surface border border-border-muted rounded-2xl shadow-2xl max-w-md w-full mx-4 overflow-hidden">
            {/* Header */}
            <div className="px-6 py-5 border-b border-border-muted bg-gradient-to-r from-amber-500/10 to-orange-500/10">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-amber-500/20 flex items-center justify-center">
                  <svg className="w-5 h-5 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                  </svg>
                </div>
                <div>
                  <h3 className="text-lg font-semibold text-text-primary">Document Limit Reached</h3>
                  <p className="text-sm text-text-secondary">Storage limit exceeded</p>
                </div>
              </div>
            </div>

            {/* Content */}
            <div className="px-6 py-5 space-y-4">
              {/* Usage indicator */}
              {documentLimitInfo && (
                <div className="bg-bg-elevated rounded-xl p-4">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-sm text-text-secondary">Documents Used</span>
                    <span className="text-sm font-mono font-medium text-text-primary">
                      {documentLimitInfo.current} / {documentLimitInfo.max}
                    </span>
                  </div>
                  <div className="w-full bg-bg-primary rounded-full h-2.5">
                    <div
                      className="bg-gradient-to-r from-amber-500 to-orange-500 h-2.5 rounded-full"
                      style={{ width: '100%' }}
                    />
                  </div>
                </div>
              )}

              <p className="text-text-secondary text-sm leading-relaxed">
                You&apos;ve reached the maximum number of documents allowed for your account.
                To analyze new contracts, please delete some existing documents first.
              </p>

              {/* Info box */}
              <div className="bg-bg-elevated/50 border border-border-muted rounded-lg p-3 flex gap-3">
                <svg className="w-4 h-4 text-text-secondary flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <p className="text-xs text-text-secondary">
                  Deleting a document removes all associated data including the PDF, analysis results, and chat history.
                </p>
              </div>
            </div>

            {/* Actions */}
            <div className="px-6 py-4 bg-bg-elevated/30 border-t border-border-muted flex gap-3">
              <button
                onClick={() => setShowLimitModal(false)}
                className="flex-1 px-4 py-2.5 text-sm font-medium text-text-secondary hover:text-text-primary bg-bg-elevated hover:bg-bg-surface border border-border-muted rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => {
                  setShowLimitModal(false);
                  router.push("/documents");
                }}
                className="flex-1 px-4 py-2.5 text-sm font-medium text-white bg-accent-purple hover:bg-purple-600 rounded-lg transition-colors flex items-center justify-center gap-2"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Manage Documents
              </button>
            </div>
          </div>
        </div>
      )}

      <ConfirmModal
        isOpen={!!validationModal}
        title={validationModal?.title || "Notice"}
        message={<p className="text-sm">{validationModal?.message || ""}</p>}
        confirmText="OK"
        showCancel={false}
        onClose={() => setValidationModal(null)}
        onConfirm={() => setValidationModal(null)}
      />

      {/* Hero Section - Two Column Layout */}
      <div className="relative overflow-hidden">
        <div className="max-w-7xl mx-auto px-6 lg:px-8 pt-24 pb-20">
          <div className="flex flex-col xl:flex-row xl:items-center gap-12 xl:gap-16">
            {/* Left Column - Content (60%) */}
            <div className="flex-1 xl:flex-[3]">
              <h1 className="font-heading text-4xl sm:text-5xl lg:text-6xl font-semibold text-text-primary mb-8 leading-tight">
              Understand any
              <span className="text-accent-purple"> contract</span>
              <br />
                in 60 seconds
            </h1>
              <div className="mb-10 max-w-2xl">
                <p className="text-xl text-text-secondary leading-relaxed mb-4">
                  Upload your legal document and get instant AI-powered analysis in plain English.
            </p>
                <p className="text-lg text-text-secondary/80 leading-relaxed">
                  Chat with your contract, identify risks, and make informed decisions.
                </p>
              </div>

              {/* Key Differentiators */}
              <div className="space-y-4 mb-12">
                <div className="flex items-center gap-4">
                  <div className="w-8 h-8 bg-accent-green/20 rounded-lg flex items-center justify-center">
                    <svg className="w-4 h-4 text-accent-green" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
                    </svg>
                  </div>
                  <span className="text-text-primary font-medium">Chat with your document in natural language</span>
                </div>
                <div className="flex items-center gap-4">
                  <div className="w-8 h-8 bg-accent-purple/20 rounded-lg flex items-center justify-center">
                    <svg className="w-4 h-4 text-accent-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                  </div>
                  <span className="text-text-primary font-medium">AI suggestions and rewrites</span>
                </div>
                <div className="flex items-center gap-4">
                  <div className="w-8 h-8 bg-accent-amber/20 rounded-lg flex items-center justify-center">
                    <svg className="w-4 h-4 text-accent-amber" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" />
                    </svg>
                  </div>
                  <span className="text-text-primary font-medium">Smart clause navigation and extraction</span>
                </div>
              </div>

              {/* Social Proof */}
              <div className="grid grid-cols-3 gap-6 max-w-lg">
                <div className="text-center p-4 bg-accent-purple/5 border border-accent-purple/10 rounded-xl hover:bg-accent-purple/10 transition-all duration-300">
                  <div className="text-3xl font-bold text-accent-purple mb-2">10+</div>
                  <div className="text-sm text-text-secondary font-medium">Contract<br />Types</div>
                </div>
                <div className="text-center p-4 bg-accent-green/5 border border-accent-green/10 rounded-xl hover:bg-accent-green/10 transition-all duration-300">
                  <div className="text-3xl font-bold text-accent-green mb-2">&lt;1min</div>
                  <div className="text-sm text-text-secondary font-medium">Analysis<br />Time</div>
                </div>
                <div className="text-center p-4 bg-accent-amber/5 border border-accent-amber/10 rounded-xl hover:bg-accent-amber/10 transition-all duration-300">
                  <div className="flex justify-center mb-2">
                    <svg className="w-8 h-8 text-accent-amber" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                    </svg>
                  </div>
                  <div className="text-sm text-text-secondary font-medium">Leading<br />AI Models</div>
                </div>
              </div>
            </div>

            {/* Right Column - Upload Widget (40%) */}
            <div className="flex-1 xl:flex-[2]">
              <Card className="p-8 shadow-xl border border-border-muted/50 bg-gradient-to-br from-bg-surface to-bg-elevated">
                <div className="text-center mb-8">
                  <h3 className="font-heading text-xl font-semibold text-text-primary mb-3">
                    Try it now
                  </h3>
                  <p className="text-text-secondary">
                    Upload your PDF contract
                  </p>
                </div>

                {/* API Key Warning Banner */}
                {isAuthenticated && hasApiKey === false && !checkingApiKey && (
                  <div className="mb-6 p-4 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg">
                    <div className="flex items-start gap-3">
                      <svg className="w-5 h-5 text-amber-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.732-.833-2.5 0L4.314 16.5c-.77.833.192 2.5 1.732 2.5z" />
                      </svg>
                      <div>
                        <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
                          API Key Required
                        </p>
                        <p className="text-sm text-amber-700 dark:text-amber-300 mt-1">
                          Add your OpenAI API key in{" "}
                          <button
                            onClick={() => router.push("/settings")}
                            className="underline hover:no-underline font-medium"
                          >
                            Settings
                          </button>{" "}
                          to analyze documents.
                        </p>
                      </div>
                    </div>
                  </div>
                )}

                {/* Enhanced Upload Zone */}
              <div
                className={clsx(
                    "relative border-2 border-dashed rounded-xl p-10 text-center transition-all duration-300 cursor-pointer group",
                  dragActive || file
                      ? "border-accent-purple bg-gradient-to-br from-accent-purple/10 to-accent-purple/5 shadow-lg scale-[1.02]"
                      : "border-border-muted hover:border-accent-purple/60 hover:bg-gradient-to-br hover:from-accent-purple/5 hover:to-transparent hover:shadow-md hover:scale-[1.01]"
                )}
                onDragEnter={handleDrag}
                onDragLeave={handleDrag}
                onDragOver={handleDrag}
                onDrop={handleDrop}
                onClick={() => {
                  if (fileInputRef.current && !analysisLoading) {
                    fileInputRef.current.click();
                  }
                }}
              >
                {/* Hidden file input - positioned off-screen but accessible */}
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".pdf"
                  onChange={handleInputChange}
                  className="sr-only"
                  disabled={analysisLoading}
                  tabIndex={-1}
                />



                  {file ? (
                    <div className="space-y-3">
                      <div className="w-12 h-12 bg-accent-green/20 rounded-full flex items-center justify-center mx-auto">
                        <svg className="w-6 h-6 text-accent-green" fill="currentColor" viewBox="0 0 20 20">
                          <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                      </svg>
                      </div>
                      <p className="font-semibold text-text-primary">{file.name}</p>
                      <p className="text-sm text-text-secondary">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                    </div>
                  ) : (
                    <div className="space-y-4">
                      <div className="w-16 h-16 bg-accent-purple/10 rounded-full flex items-center justify-center mx-auto group-hover:bg-accent-purple/20 transition-all duration-300">
                        <svg className="w-8 h-8 text-accent-purple group-hover:scale-110 transition-transform duration-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                      </svg>
                      </div>
                      <div>
                        <p className="text-text-primary font-semibold text-lg">
                          Drop PDF or <span className="text-accent-purple group-hover:text-accent-purple/80 transition-colors">browse</span>
                        </p>
                        <p className="text-sm text-text-secondary mt-2">Max {config.maxFileSizeMB}MB • Secure & Private</p>
                      </div>
                    </div>
                  )}
              </div>



              {file && (
                  <div className="mt-6 space-y-4">
                  {analysisLoading ? (
                    // Progress bar during analysis
                    <div className="space-y-3">
                      <div className="flex justify-between text-sm">
                        <span className="text-text-secondary">{analysisStep}</span>
                        <span className="text-text-primary font-mono">{analysisProgress}%</span>
                      </div>
                      <div className="w-full bg-bg-elevated rounded-full h-2.5 overflow-hidden">
                        <div
                          className="bg-gradient-to-r from-accent-purple to-accent-purple/80 h-2.5 rounded-full transition-all duration-500 ease-out"
                          style={{ width: `${analysisProgress}%` }}
                        />
                      </div>
                      <p className="text-xs text-text-secondary text-center mt-2">
                        This may take 30-60 seconds depending on document size
                      </p>
                    </div>
                  ) : (
                    // Normal button state
                    <>
                      <Button
                        onClick={handleProcessDocument}
                        size="md"
                        className="w-full"
                      >
                        Analyze Contract
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={handleRemoveFile}
                        size="sm"
                        className="w-full"
                      >
                        Remove
                      </Button>
                    </>
                  )}
                </div>
              )}

              </Card>
            </div>
          </div>
        </div>
      </div>

      {/* How It Works Section */}
      <div className="py-24 bg-bg-surface">
        <div className="max-w-7xl mx-auto px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="font-heading text-4xl font-semibold text-text-primary mb-6">
              How ClauseIQ works
            </h2>
            <p className="text-xl text-text-secondary max-w-3xl mx-auto">
              Get professional legal analysis in three simple steps
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-12">
            <div className="text-center">
              <div className="w-20 h-20 bg-accent-purple/10 rounded-full flex items-center justify-center mx-auto mb-6">
                <span className="text-3xl font-bold text-accent-purple">1</span>
              </div>
              <h3 className="font-heading text-xl font-semibold text-text-primary mb-4">
                Upload Contract
              </h3>
              <p className="text-text-secondary leading-relaxed">
                Drop your PDF contract and our AI instantly identifies the document type and structure
              </p>
            </div>

            <div className="text-center">
              <div className="w-20 h-20 bg-accent-green/10 rounded-full flex items-center justify-center mx-auto mb-6">
                <span className="text-3xl font-bold text-accent-green">2</span>
              </div>
              <h3 className="font-heading text-xl font-semibold text-text-primary mb-4">
                AI Analysis
              </h3>
              <p className="text-text-secondary leading-relaxed">
                Advanced AI extracts clauses, assesses risks, and prepares your document for interactive chat
              </p>
            </div>

            <div className="text-center">
              <div className="w-20 h-20 bg-accent-amber/10 rounded-full flex items-center justify-center mx-auto mb-6">
                <span className="text-3xl font-bold text-accent-amber">3</span>
              </div>
              <h3 className="font-heading text-xl font-semibold text-text-primary mb-4">
                Chat & Explore
              </h3>
              <p className="text-text-secondary leading-relaxed">
                Ask questions, navigate clauses, and get plain-English explanations of complex legal terms
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Chat Feature Showcase */}
      <div className="py-24">
        <div className="max-w-7xl mx-auto px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
            <div>
              <h2 className="font-heading text-4xl font-semibold text-text-primary mb-6">
                Chat with your contract like ChatGPT
              </h2>
              <p className="text-text-secondary mb-8 text-xl leading-relaxed">
                Ask any question about your contract in natural language. Get instant answers
                with exact citations from your document.
                </p>

              <div className="space-y-6">
                <div className="flex items-start gap-4">
                  <div className="w-8 h-8 bg-accent-green/10 rounded-full flex items-center justify-center flex-shrink-0 mt-1">
                    <svg className="w-4 h-4 text-accent-green" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <div>
                    <p className="font-semibold text-text-primary text-lg">&quot;What&apos;s my notice period?&quot;</p>
                    <p className="text-text-secondary mt-1">Get instant answers with source citations</p>
                  </div>
                </div>

                <div className="flex items-start gap-4">
                  <div className="w-8 h-8 bg-accent-green/10 rounded-full flex items-center justify-center flex-shrink-0 mt-1">
                    <svg className="w-4 h-4 text-accent-green" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <div>
                    <p className="font-semibold text-text-primary text-lg">&quot;Are there any concerning clauses?&quot;</p>
                    <p className="text-text-secondary mt-1">AI highlights potential risks and red flags</p>
                  </div>
                </div>

                <div className="flex items-start gap-4">
                  <div className="w-8 h-8 bg-accent-green/10 rounded-full flex items-center justify-center flex-shrink-0 mt-1">
                    <svg className="w-4 h-4 text-accent-green" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <div>
                    <p className="font-semibold text-text-primary text-lg">&quot;Explain this clause in simple terms&quot;</p>
                    <p className="text-text-secondary mt-1">Complex legal jargon translated to plain English</p>
                  </div>
                </div>
              </div>
            </div>

            <div className="lg:order-first">
              {/* Chat Interface Mockup */}
              <Card className="p-8 shadow-lg">
                <div className="space-y-6">
                  {/* User Message */}
                  <div className="flex justify-end">
                    <div className="bg-accent-purple text-white rounded-2xl px-6 py-3 max-w-xs">
                      <p className="text-sm">What happens if I want to leave this job?</p>
                    </div>
                  </div>

                  {/* AI Response */}
                  <div className="flex justify-start">
                    <div className="bg-bg-elevated border border-border-muted rounded-2xl px-6 py-4 max-w-sm">
                      <p className="text-sm text-text-primary mb-3">
                        According to your contract, you need to provide <strong>30 days written notice</strong> before leaving. There&apos;s no penalty for resignation.
                      </p>
                      <div className="text-xs text-accent-purple">
                        📎 Source: Section 4.2 - Termination
                      </div>
                    </div>
                  </div>

                  {/* User Message */}
                  <div className="flex justify-end">
                    <div className="bg-accent-purple text-white rounded-2xl px-6 py-3 max-w-xs">
                      <p className="text-sm">What about my benefits?</p>
                    </div>
                  </div>

                  {/* Typing Indicator */}
                  <div className="flex justify-start">
                    <div className="bg-bg-elevated border border-border-muted rounded-2xl px-6 py-4">
                      <div className="flex items-center gap-1">
                        <div className="w-2 h-2 bg-text-secondary rounded-full animate-pulse"></div>
                        <div className="w-2 h-2 bg-text-secondary rounded-full animate-pulse" style={{animationDelay: '0.2s'}}></div>
                        <div className="w-2 h-2 bg-text-secondary rounded-full animate-pulse" style={{animationDelay: '0.4s'}}></div>
                      </div>
                    </div>
                  </div>
              </div>
            </Card>
            </div>
          </div>
        </div>
      </div>

      {/* Clause Navigator Feature */}
      <div className="py-24 bg-bg-surface">
        <div className="max-w-7xl mx-auto px-6 lg:px-8">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-16 items-center">
            <div>
              <h2 className="font-heading text-4xl font-semibold text-text-primary mb-6">
                Smart clause analysis & navigation
              </h2>
              <p className="text-text-secondary mb-8 text-xl leading-relaxed">
                Every clause automatically categorized and risk-assessed. Navigate your contract
                with color-coded risk levels and smart filtering.
              </p>

              <div className="space-y-6">
                <div className="flex items-center gap-4">
                  <div className="w-4 h-4 bg-accent-rose rounded-full"></div>
                  <span className="text-text-primary font-semibold text-lg">High Risk Clauses</span>
                  <span className="text-text-secondary">- Review carefully</span>
                </div>
                <div className="flex items-center gap-4">
                  <div className="w-4 h-4 bg-accent-amber rounded-full"></div>
                  <span className="text-text-primary font-semibold text-lg">Medium Risk Clauses</span>
                  <span className="text-text-secondary">- Consider implications</span>
                </div>
                <div className="flex items-center gap-4">
                  <div className="w-4 h-4 bg-accent-green rounded-full"></div>
                  <span className="text-text-primary font-semibold text-lg">Low Risk Clauses</span>
                  <span className="text-text-secondary">- Generally favorable</span>
                </div>
              </div>
            </div>

            <div>
              {/* Clause Navigator Mockup */}
              <Card className="p-6 shadow-lg">
                <div className="space-y-4">
                  <div className="flex items-center justify-between mb-6">
                    <h4 className="font-semibold text-text-primary text-lg">Contract Clauses</h4>
                    <span className="text-text-secondary">12 found</span>
                  </div>

                  <div className="p-4 bg-accent-rose/5 border border-accent-rose/20 rounded-xl">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <p className="font-semibold text-text-primary">Termination Clause</p>
                        <p className="text-sm text-text-secondary mt-2">Immediate dismissal for gross misconduct...</p>
                      </div>
                      <span className="px-3 py-1 bg-accent-rose text-white text-sm rounded-full font-medium">High</span>
                    </div>
                  </div>

                  <div className="p-4 bg-accent-amber/5 border border-accent-amber/20 rounded-xl">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <p className="font-semibold text-text-primary">Non-Compete Clause</p>
                        <p className="text-sm text-text-secondary mt-2">6-month restriction period...</p>
                      </div>
                      <span className="px-3 py-1 bg-accent-amber text-white text-sm rounded-full font-medium">Medium</span>
                    </div>
                  </div>

                  <div className="p-4 bg-accent-green/5 border border-accent-green/20 rounded-xl">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <p className="font-semibold text-text-primary">Salary Review</p>
                        <p className="text-sm text-text-secondary mt-2">Annual performance-based review...</p>
                      </div>
                      <span className="px-3 py-1 bg-accent-green text-white text-sm rounded-full font-medium">Low</span>
                    </div>
                  </div>

                  <div className="text-center pt-4">
                    <button className="text-accent-purple hover:text-accent-purple/80 font-medium">
                      View all clauses →
                    </button>
                  </div>
                </div>
              </Card>
            </div>
          </div>
        </div>
      </div>

      {/* Contract Types Section */}
      <div className="py-24">
        <div className="max-w-7xl mx-auto px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="font-heading text-4xl font-semibold text-text-primary mb-6">
              Built for real people and businesses
            </h2>
            <p className="text-xl text-text-secondary max-w-3xl mx-auto">
              Whether you&apos;re a small business owner, HR manager, or individual, ClauseIQ makes legal documents accessible
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-10 mb-16">
            <Card density="compact" className="text-center p-8 h-full flex flex-col">
              <div className="w-16 h-16 bg-accent-blue/10 rounded-xl flex items-center justify-center mx-auto mb-6">
                <svg className="w-8 h-8 text-accent-blue" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                </svg>
              </div>
              <h3 className="font-heading text-xl font-semibold text-text-primary mb-4">
                Small Business Owners
              </h3>
              <p className="text-text-secondary leading-relaxed flex-grow">
                Review vendor contracts, service agreements, and partnership deals with confidence
              </p>
            </Card>

            <Card density="compact" className="text-center p-8 h-full flex flex-col">
              <div className="w-16 h-16 bg-accent-purple/10 rounded-xl flex items-center justify-center mx-auto mb-6">
                <svg className="w-8 h-8 text-accent-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                </svg>
              </div>
              <h3 className="font-heading text-xl font-semibold text-text-primary mb-4">
                HR Teams
              </h3>
              <p className="text-text-secondary leading-relaxed flex-grow">
                Analyze employment contracts, NDAs, and consultant agreements for your team
              </p>
            </Card>

            <Card density="compact" className="text-center p-8 h-full flex flex-col">
              <div className="w-16 h-16 bg-accent-green/10 rounded-xl flex items-center justify-center mx-auto mb-6">
                <svg className="w-8 h-8 text-accent-green" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                </svg>
              </div>
              <h3 className="font-heading text-xl font-semibold text-text-primary mb-4">
                Individuals
              </h3>
              <p className="text-text-secondary leading-relaxed flex-grow">
                Understand your employment contract, lease agreement, or any legal document
              </p>
            </Card>
          </div>

          {/* Contract Types */}
          <div className="text-center">
            <h3 className="font-heading text-2xl font-semibold text-text-primary mb-8">
              Supports 10+ contract types
            </h3>
            <div className="flex flex-wrap justify-center gap-4">
              {[
                'Employment', 'NDAs', 'Service Agreements', 'Leases',
                'Purchase Agreements', 'Partnership', 'License', 'Consulting',
                'Contractor', 'Generic'
              ].map((type) => (
                <span key={type} className="px-4 py-2 bg-bg-elevated border border-border-muted rounded-full text-text-secondary font-medium">
                  {type}
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Advanced AI Features Section */}
      <div className="py-24 bg-bg-surface">
        <div className="max-w-7xl mx-auto px-6 lg:px-8">
          <div className="text-center mb-16">
            <h2 className="font-heading text-4xl font-semibold text-text-primary mb-6">
              Advanced AI capabilities
            </h2>
            <p className="text-xl text-text-secondary max-w-3xl mx-auto">
              Powered by cutting-edge AI that catches what humans miss and provides strategic insights for better decisions.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
            <div className="text-center">
              <div className="w-16 h-16 bg-accent-rose/10 rounded-xl flex items-center justify-center mx-auto mb-6">
                <svg className="w-8 h-8 text-accent-rose" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v3m0 0v3m0-3h3m-3 0H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <h4 className="font-semibold text-text-primary mb-3 text-lg">Finds Hidden Risks</h4>
              <p className="text-text-secondary leading-relaxed">Spots problematic clauses lawyers miss</p>
            </div>

            <div className="text-center">
              <div className="w-16 h-16 bg-accent-purple/10 rounded-xl flex items-center justify-center mx-auto mb-6">
                <svg className="w-8 h-8 text-accent-purple" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3a4 4 0 118 0v4m-8 0h8m-8 0v9a2 2 0 002 2h4.586a1 1 0 01.707.293l2.414 2.414a1 1 0 00.707.293H20a2 2 0 002-2V7m-8 0V3a4 4 0 118 0v4" />
                </svg>
              </div>
              <h4 className="font-semibold text-text-primary mb-3 text-lg">Deadline Extraction</h4>
              <p className="text-text-secondary leading-relaxed">Never miss critical dates again</p>
            </div>

            <div className="text-center">
              <div className="w-16 h-16 bg-accent-green/10 rounded-xl flex items-center justify-center mx-auto mb-6">
                <svg className="w-8 h-8 text-accent-green" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <h4 className="font-semibold text-text-primary mb-3 text-lg">Compliance Checking</h4>
              <p className="text-text-secondary leading-relaxed">Highlights regulatory violations automatically</p>
            </div>

            <div className="text-center">
              <div className="w-16 h-16 bg-accent-amber/10 rounded-xl flex items-center justify-center mx-auto mb-6">
                <svg className="w-8 h-8 text-accent-amber" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                </svg>
              </div>
              <h4 className="font-semibold text-text-primary mb-3 text-lg">Negotiation Intel</h4>
              <p className="text-text-secondary leading-relaxed">Shows where you have leverage to improve terms</p>
            </div>
          </div>
        </div>
      </div>


    </div>
  );
}
