import apiClient from "@/lib/api";
import type { DocumentItem } from "@/types/documents";

/** Decode the workspace library response without an implicit document cap. */
export async function loadWorkspaceDocuments(): Promise<DocumentItem[]> {
  const response = await apiClient.get<{ documents: DocumentItem[] }>("/documents/");
  if (!response.success) {
    throw new Error(response.error?.message || "Unable to load documents.");
  }
  if (!Array.isArray(response.data?.documents)) {
    throw new Error("The document library returned an unexpected response.");
  }
  return response.data.documents;
}
