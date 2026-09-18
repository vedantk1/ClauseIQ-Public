import apiClient from "@/lib/api";
import type { SourceMetadata } from "@clauseiq/shared-types";

export class SourceImportError extends Error {
  constructor(message: string, public documentId?: string) {
    super(message);
    this.name = "SourceImportError";
  }
}

export async function importSource(file: File): Promise<SourceMetadata & { id: string }> {
  const result = await apiClient.uploadFile<SourceMetadata & { id: string }>("/documents/import", file);
  if (result.success && result.data?.id) return result.data;
  const knownId = result.error?.details?.document_id;
  throw new SourceImportError(
    result.error?.message || "The import could not be confirmed. Check the library before uploading again.",
    typeof knownId === "string" ? knownId : undefined,
  );
}
