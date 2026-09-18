import apiClient, { type APIResponse } from "@/lib/api";
import type {
  DocumentSourceResponse, ReviewWorkspaceResponse, ReviewWorkspaceOperation,
} from "@clauseiq/shared-types";

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
    return unwrap(await apiClient.get<ReviewWorkspaceResponse>(`/documents/${encodeURIComponent(documentId)}/review-workspace`));
  },
  async source(documentId: string): Promise<DocumentSourceResponse> {
    return unwrap(await apiClient.get<DocumentSourceResponse>(`/documents/${encodeURIComponent(documentId)}/source`));
  },
  async document(documentId: string): Promise<{ id: string; filename: string }> {
    return unwrap(await apiClient.get<{ id: string; filename: string }>(`/documents/${encodeURIComponent(documentId)}`));
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
  async generate(documentId: string, revision: number, requestId: string, modelId: string): Promise<ReviewWorkspaceResponse> {
    return unwrap(await apiClient.post<ReviewWorkspaceResponse>(`/documents/${encodeURIComponent(documentId)}/review-workspace/generate`, {
      expected_revision: revision, request_id: requestId, model_id: modelId,
    }, { timeout: 210000 }));
  },
  async interrupt(documentId: string, revision: number, runId: string): Promise<ReviewWorkspaceResponse> {
    return unwrap(await apiClient.post<ReviewWorkspaceResponse>(`/documents/${encodeURIComponent(documentId)}/review-workspace/runs/${encodeURIComponent(runId)}/interrupt`, {
      expected_revision: revision,
    }));
  },
};

export type ReviewWorkspaceTransport = Pick<typeof reviewWorkspaceApi, "load" | "update" | "fixture" | "generate" | "interrupt">;
