import { useCallback, useEffect, useState } from "react";
import { loadWorkspaceDocuments } from "@/lib/documentsApi";
import toast from "@/lib/toast";
import type { DocumentItem } from "@/types/documents";

export const useDocumentsData = () => {
  const [documents, setDocuments] = useState<DocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setDocuments(await loadWorkspaceDocuments());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to load documents");
      void toast.error("Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void fetchDocuments(); }, [fetchDocuments]);

  return { documents, setDocuments, loading, error, retryFetch: fetchDocuments };
};
