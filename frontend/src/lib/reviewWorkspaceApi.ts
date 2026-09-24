import apiClient, { type APIResponse } from "@/lib/api";
import type {
  DocumentSourceResponse, ReviewWorkspaceResponse, ReviewWorkspaceOperation,
} from "@clauseiq/shared-types";

export const WORKSPACE_READ_TIMEOUT_MS = 20000;

export class ReviewWorkspaceError extends Error {
  constructor(message: string, public code: string) {
    super(message);
    this.name = "ReviewWorkspaceError";
  }
}

function unwrap<T>(response: APIResponse<T>): T {
  if (!response.success || !response.data) {
    throw new ReviewWorkspaceError(response.error?.message || "The workspace could not be saved.",
      response.error?.code || "INVALID_RESPONSE");
  }
  return response.data;
}

export const reviewWorkspaceApi = {
  async load(documentId: string): Promise<ReviewWorkspaceResponse> {
    return unwrap(await apiClient.get<ReviewWorkspaceResponse>(`/documents/${encodeURIComponent(documentId)}/review-workspace`, undefined,
      { timeout: WORKSPACE_READ_TIMEOUT_MS, diagnosticScope: "workspace-state" }));
  },
  async source(documentId: string, options?: { signal?: AbortSignal }): Promise<DocumentSourceResponse> {
    return unwrap(await apiClient.get<DocumentSourceResponse>(`/documents/${encodeURIComponent(documentId)}/source`, undefined,
      { signal: options?.signal, timeout: WORKSPACE_READ_TIMEOUT_MS, diagnosticScope: "workspace-source" }));
  },
  async document(documentId: string, options?: { signal?: AbortSignal }): Promise<{ id: string; filename: string }> {
    return unwrap(await apiClient.get<{ id: string; filename: string }>(`/documents/${encodeURIComponent(documentId)}`, undefined,
      { signal: options?.signal, timeout: WORKSPACE_READ_TIMEOUT_MS, diagnosticScope: "workspace-metadata" }));
  },
  async update(documentId: string, revision: number, operation: ReviewWorkspaceOperation): Promise<ReviewWorkspaceResponse> {
    return unwrap(await apiClient.put<ReviewWorkspaceResponse>(`/documents/${encodeURIComponent(documentId)}/review-workspace`, {
      expected_revision: revision, operation,
    }));
  },
  async fixture(documentId: string, revision: number): Promise<ReviewWorkspaceResponse> {
    return unwrap(await apiClient.post<ReviewWorkspaceResponse>(`/documents/${encodeURIComponent(documentId)}/review-workspace/fixture`, {
      expected_revision: revision,
    }));
  },
  async generate(documentId: string, revision: number, requestId: string, modelId: string, reasoningEffort = "medium"): Promise<ReviewWorkspaceResponse> {
    return unwrap(await apiClient.post<ReviewWorkspaceResponse>(`/documents/${encodeURIComponent(documentId)}/review-workspace/generate`, {
      expected_revision: revision, request_id: requestId, model_id: modelId, reasoning_effort: reasoningEffort,
    }, { timeout: 210000 }));
  },
  async interrupt(documentId: string, revision: number, runId: string): Promise<ReviewWorkspaceResponse> {
    return unwrap(await apiClient.post<ReviewWorkspaceResponse>(`/documents/${encodeURIComponent(documentId)}/review-workspace/runs/${encodeURIComponent(runId)}/interrupt`, {
      expected_revision: revision,
    }));
  },
  async ask(documentId: string, revision: number, requestId: string, modelId: string,
    runId: string, findingId: string, question: string, includeHistory: boolean, reasoningEffort = "medium"): Promise<ReviewWorkspaceResponse> {
    return unwrap(await apiClient.post<ReviewWorkspaceResponse>(`/documents/${encodeURIComponent(documentId)}/review-workspace/runs/${encodeURIComponent(runId)}/findings/${encodeURIComponent(findingId)}/ask`, {
      expected_revision: revision, request_id: requestId, model_id: modelId, question, include_history: includeHistory, reasoning_effort: reasoningEffort,
    }, { timeout: 210000 }));
  },
  async interruptAsk(documentId: string, revision: number, turnId: string): Promise<ReviewWorkspaceResponse> {
    return unwrap(await apiClient.post<ReviewWorkspaceResponse>(`/documents/${encodeURIComponent(documentId)}/review-workspace/ask/${encodeURIComponent(turnId)}/interrupt`, {
      expected_revision: revision,
    }));
  },
};

export type ReviewWorkspaceTransport = Pick<typeof reviewWorkspaceApi, "load" | "update" | "fixture" | "generate" | "interrupt" | "ask" | "interruptAsk">;
