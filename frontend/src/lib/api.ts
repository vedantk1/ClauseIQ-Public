/**
 * Centralized API client with standardized response handling
 */

import toast from "@/lib/toast";

// A required non-simple header, combined with the backend's local origin/host
// checks, prevents unrelated browser pages from invoking the local API.
export const LOCAL_API_HEADERS = { "X-ClauseIQ-Local": "1" } as const;

// API Response types based on backend standardization
export interface APIResponse<T = unknown> {
  success: boolean;
  data?: T;
  error?: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
  meta?: Record<string, unknown>;
  correlation_id?: string;
}

export interface PaginationMeta {
  page: number;
  page_size: number;
  total_items: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}

type WorkspaceDiagnosticScope = "workspace-source" | "workspace-metadata" | "workspace-state";

interface ReadOptions {
  signal?: AbortSignal;
  timeout?: number;
  diagnosticScope?: WorkspaceDiagnosticScope;
}

// Only fixed labels and transport metadata: never response bodies, URLs, IDs,
// filenames, exception messages, credentials or extracted text.
function reportWorkspaceReadFailure(scope: WorkspaceDiagnosticScope | undefined,
  response: APIResponse<unknown>, startedAt: number, phase: "headers" | "body", status?: number) {
  if (!scope || response.success || response.error?.code === "REQUEST_CANCELLED") return;
  const code = response.error?.code;
  const category = code === "NETWORK_ERROR" ? "network"
    : code === "REQUEST_TIMEOUT" ? "timeout"
      : code === "PARSE_ERROR" ? "response-format"
        : status && status >= 400 ? "http" : "application";
  // Serialize fixed fields so browser log collectors retain useful diagnostics
  // rather than reducing the object to an uninspectable "Object" label.
  console.error("Workspace read failed", JSON.stringify({
    resource: scope,
    category,
    phase,
    ...(status ? { status } : {}),
    elapsedMs: Math.max(0, Date.now() - startedAt),
    online: typeof navigator === "undefined" ? "unknown" : navigator.onLine,
  }));
}

class APIClient {
  private baseURL: string;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit & { timeout?: number; diagnosticScope?: WorkspaceDiagnosticScope } = {},
  ): Promise<APIResponse<T>> {
    const url = `${this.baseURL}${endpoint}`;
    // Prepare headers
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
      ...LOCAL_API_HEADERS,
    };

    // Set content type for non-FormData requests
    if (!(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }

    // Setup timeout if specified
    const { timeout, diagnosticScope, ...fetchOptions } = options;
    const startedAt = Date.now();
    const callerSignal = options.signal;
    let timeoutId: NodeJS.Timeout | undefined;
    let abortController: AbortController | undefined;
    let timedOut = false;
    let phase: "headers" | "body" = "headers";
    const abortFromCaller = () => abortController?.abort();

    if (timeout) {
      abortController = new AbortController();
      timeoutId = setTimeout(() => {
        timedOut = true;
        abortController?.abort();
      }, timeout);
      if (callerSignal?.aborted) abortFromCaller();
      else callerSignal?.addEventListener("abort", abortFromCaller, { once: true });
      fetchOptions.signal = abortController.signal;
    }


    try {
      const response = await fetch(url, {
        ...fetchOptions,
        headers,
      });
      phase = "body";

      // Keep existing write/legacy timeout semantics unchanged. Workspace reads
      // alone keep their bounded timer through response-body consumption.
      if (!diagnosticScope && timeoutId) clearTimeout(timeoutId);
      const parsed = await this.parseResponse<T>(response, fetchOptions.signal);
      reportWorkspaceReadFailure(diagnosticScope, parsed, startedAt, phase, response.status);
      return parsed;
    } catch (error) {
      // This only represents an explicit caller cancellation, not an arbitrary
      // transport AbortError. Read cleanup may cancel without showing an error.
      if (callerSignal?.aborted && !timedOut) {
        return { success: false, error: { code: "REQUEST_CANCELLED", message: "Request cancelled." } };
      }

      // Handle abort error (timeout)
      if (timedOut || (error instanceof Error && error.name === "AbortError")) {
        if (!diagnosticScope) console.error("API request timed out");
        const result: APIResponse<T> = {
          success: false,
          error: {
            code: "REQUEST_TIMEOUT",
            message: `Request timed out after ${timeout ? timeout / 1000 : "?"} seconds`,
            details: { timeout, ...(!diagnosticScope ? { url } : {}), method: fetchOptions.method || "GET" },
          },
        };
        reportWorkspaceReadFailure(diagnosticScope, result, startedAt, phase);
        return result;
      }

      if (!diagnosticScope) console.error("API request failed");
      const result: APIResponse<T> = {
        success: false,
        error: {
          code: "NETWORK_ERROR",
          message:
            diagnosticScope ? "The local API could not be reached."
              : error instanceof Error ? error.message : "Network error occurred",
        },
      };
      reportWorkspaceReadFailure(diagnosticScope, result, startedAt, phase);
      return result;
    } finally {
      if (timeoutId) clearTimeout(timeoutId);
      callerSignal?.removeEventListener("abort", abortFromCaller);
    }
  }

  private async parseResponse<T>(response: Response, signal?: AbortSignal | null): Promise<APIResponse<T>> {

    try {
      const data = await response.json();


      // Check if response follows our standardized format
      if (typeof data.success === "boolean") {
        return data as APIResponse<T>;
      }

      // Legacy response format - wrap in standardized format
      if (response.ok) {
        return {
          success: true,
          data: data as T,
        };
      } else {
        return {
          success: false,
          error: {
            code: `HTTP_${response.status}`,
            message: data.detail || data.message || response.statusText,
            details: data,
          },
        };
      }
    } catch (parseError) {
      // Let request distinguish deliberate cleanup from its own timeout.
      if (signal?.aborted) throw parseError;
      console.error("Failed to parse API response");

      return {
        success: false,
        error: {
          code: "PARSE_ERROR",
          message: "Failed to parse response",
          details: {
            parseError:
              parseError instanceof Error
                ? parseError.message
                : "Unknown error",
            status: response.status,
            statusText: response.statusText,
          },
        },
      };
    }
  }

  // HTTP Methods
  async get<T>(
    endpoint: string,
    params?: Record<string, string>,
    options?: ReadOptions,
  ): Promise<APIResponse<T>> {
    const url = params
      ? `${endpoint}?${new URLSearchParams(params).toString()}`
      : endpoint;

    return this.request<T>(url, { ...options, method: "GET" });
  }

  async post<T>(
    endpoint: string,
    data?: unknown,
    options?: { timeout?: number },
  ): Promise<APIResponse<T>> {
    const body = data instanceof FormData ? data : JSON.stringify(data);
    return this.request<T>(endpoint, {
      method: "POST",
      body,
      timeout: options?.timeout,
    });
  }

  async put<T>(endpoint: string, data?: unknown): Promise<APIResponse<T>> {
    const body = data instanceof FormData ? data : JSON.stringify(data);
    return this.request<T>(endpoint, { method: "PUT", body });
  }

  async patch<T>(endpoint: string, data?: unknown): Promise<APIResponse<T>> {
    const body = data instanceof FormData ? data : JSON.stringify(data);
    return this.request<T>(endpoint, { method: "PATCH", body });
  }

  async delete<T>(endpoint: string): Promise<APIResponse<T>> {
    return this.request<T>(endpoint, { method: "DELETE" });
  }

  // Clause rewrite helper
  async generateClauseRewrite(
    clauseId: string,
    documentId: string,
  ): Promise<
    APIResponse<{
      rewrite_suggestion: string;
      rewrite_generated_at: string;
      cached: boolean;
    }>
  > {
    return this.post(`/analysis/clauses/${clauseId}/rewrite`, {
      document_id: documentId,
    });
  }

  // File upload helper
  async uploadFile<T>(
    endpoint: string,
    file: File,
    additionalData?: Record<string, unknown>,
    options?: { timeout?: number },
  ): Promise<APIResponse<T>> {
    const formData = new FormData();
    formData.append("file", file);

    if (additionalData) {
      Object.entries(additionalData).forEach(([key, value]) => {
        formData.append(
          key,
          typeof value === "string" ? value : JSON.stringify(value),
        );
      });
    }

    // Set longer timeout for document analysis endpoints
    const timeout =
      options?.timeout ||
      (endpoint.includes("/analysis/") ? 120000 : undefined); // 2 minutes for analysis

    return this.request<T>(endpoint, {
      method: "POST",
      body: formData,
      timeout,
    });
  }
}

// Local development is the supported runtime. An explicit setting can change
// the backend port; do not infer a hosted reverse proxy from the frontend URL.
export const getApiBaseUrl = () => {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
};

export const apiClient = new APIClient(`${getApiBaseUrl()}/api/v1`);

// Error handling utilities
export const handleAPIError = (
  response: APIResponse<unknown>,
  customMessage?: string,
) => {
  if (!response.success && response.error) {
    const message =
      customMessage || response.error.message || "An error occurred";
    // Defer toast to avoid state update during render
    setTimeout(() => {
      toast.error(message);
    }, 0);
    console.error("API Error:");
  }
};

export const handleAPISuccess = async (message?: string) => {
  if (message) {
    // Await the toast to ensure it's displayed
    await toast.success(message);
  }
};

export default apiClient;
