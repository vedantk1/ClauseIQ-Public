import type { DocumentSourceResponse } from "@clauseiq/shared-types";

export type WorkspaceReadStatus = "loading" | "ready" | "error";

export interface WorkspaceReadSnapshot {
  source: DocumentSourceResponse | null;
  filename: string;
  sourceStatus: WorkspaceReadStatus;
  metadataStatus: WorkspaceReadStatus;
  sourceError: string | null;
  metadataError: string | null;
}

export interface WorkspaceReadTransport {
  source(documentId: string, options?: { signal?: AbortSignal }): Promise<DocumentSourceResponse>;
  document(documentId: string, options?: { signal?: AbortSignal }): Promise<{ id: string; filename: string }>;
}

export const initialWorkspaceReads = (): WorkspaceReadSnapshot => ({
  source: null,
  filename: "Agreement",
  sourceStatus: "loading",
  metadataStatus: "loading",
  sourceError: null,
  metadataError: null,
});

/** Independent, read-only loads. Retries never touch the saved-work controller. */
export class WorkspaceReads {
  private snapshot = initialWorkspaceReads();
  private listeners = new Set<() => void>();
  private requests: Partial<Record<"source" | "metadata", AbortController>> = {};
  private disposed = false;

  constructor(private documentId: string, private transport: WorkspaceReadTransport) {}

  getSnapshot = () => this.snapshot;

  subscribe(listener: () => void) {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  private publish(changes: Partial<WorkspaceReadSnapshot>) {
    this.snapshot = { ...this.snapshot, ...changes };
    this.listeners.forEach(listener => listener());
  }

  load() {
    void this.retrySource();
    void this.retryMetadata();
  }

  retrySource = () => this.read("source");
  retryMetadata = () => this.read("metadata");

  private async read(resource: "source" | "metadata") {
    // One request per resource at a time, with no automatic retry loop.
    if (this.disposed || this.requests[resource]) return;
    const request = new AbortController();
    this.requests[resource] = request;
    this.publish(resource === "source"
      ? { source: null, sourceStatus: "loading", sourceError: null }
      : { metadataStatus: "loading", metadataError: null });
    const isCurrent = () => !this.disposed && this.requests[resource] === request;
    try {
      if (resource === "source") {
        const source = await this.transport.source(this.documentId, { signal: request.signal });
        if (isCurrent()) this.publish({ source, sourceStatus: "ready" });
      } else {
        const document = await this.transport.document(this.documentId, { signal: request.signal });
        if (isCurrent()) this.publish({ filename: document.filename, metadataStatus: "ready" });
      }
    } catch {
      if (isCurrent()) this.publish(resource === "source"
        ? { sourceStatus: "error", sourceError: "Source details could not be loaded. Retry loading source to check evidence; your saved work and drafts are unchanged." }
        : { metadataStatus: "error", metadataError: "The agreement name could not be loaded. Your review and source can still load independently." });
    } finally {
      if (isCurrent()) delete this.requests[resource];
    }
  }

  dispose() {
    this.disposed = true;
    this.listeners.clear();
    Object.values(this.requests).forEach(request => request.abort());
    this.requests = {};
  }
}
