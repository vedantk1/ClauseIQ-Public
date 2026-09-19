type ImportFile = Pick<File, "name" | "size">;

/** Local selection checks only. The server still validates and extracts the PDF. */
export function validateImportFiles(files: readonly ImportFile[], maxFileSizeMB: number): string | null {
  if (files.length !== 1) return "Choose one PDF agreement at a time.";
  const file = files[0];
  if (!file.name.toLowerCase().endsWith(".pdf")) return "Choose a PDF document (.pdf).";
  if (!Number.isFinite(file.size) || file.size <= 0) return "This file is empty. Choose a PDF with content.";
  if (!Number.isFinite(maxFileSizeMB) || maxFileSizeMB <= 0) {
    return "The file-size limit is unavailable. Check the app configuration before importing.";
  }
  if (file.size > maxFileSizeMB * 1024 * 1024) return `The maximum file size is ${maxFileSizeMB} MB.`;
  return null;
}

export function importFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function importedWorkspaceDestination(documentId: string): string {
  return `/workspace?documentId=${encodeURIComponent(documentId)}`;
}

export function savedImportDestination(documentId: string): string {
  return `/review?documentId=${encodeURIComponent(documentId)}`;
}
