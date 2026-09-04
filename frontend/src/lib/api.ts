/**
 * Centralized API client with standardized response handling
 */

import toast from "@/lib/toast";

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

class APIClient {
  private baseURL: string;
  private authTokenProvider?: () => string | null;
  private refreshTokenProvider?: () => Promise<void>;

  constructor(baseURL: string) {
    this.baseURL = baseURL;
  }

  setAuthTokenProvider(provider: () => string | null) {
    this.authTokenProvider = provider;
  }

  setRefreshTokenProvider(provider: () => Promise<void>) {
    this.refreshTokenProvider = provider;
  }

  private getAuthToken(): string | null {
    return this.authTokenProvider ? this.authTokenProvider() : null;
  }

  private async request<T>(
    endpoint: string,
    options: RequestInit & { timeout?: number } = {},
  ): Promise<APIResponse<T>> {
    const url = `${this.baseURL}${endpoint}`;
    const token = this.getAuthToken();


    // Prepare headers
    const headers: Record<string, string> = {
      ...(options.headers as Record<string, string>),
    };

    // Set content type for non-FormData requests
    if (!(options.body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
    }

    // Add auth token if available
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }

    // Setup timeout if specified
    const { timeout, ...fetchOptions } = options;
    let timeoutId: NodeJS.Timeout | undefined;
    let abortController: AbortController | undefined;

    if (timeout) {
      abortController = new AbortController();
      timeoutId = setTimeout(() => {
        abortController?.abort();
      }, timeout);
      fetchOptions.signal = abortController.signal;
    }


    try {
      const response = await fetch(url, {
        ...fetchOptions,
        headers,
      });

      // Clear timeout on successful response
      if (timeoutId) {
        clearTimeout(timeoutId);
      }


      // Handle token refresh for 401 errors
      if (response.status === 401 && token && this.refreshTokenProvider) {
        try {
          await this.refreshTokenProvider();
          const newToken = this.getAuthToken();


          if (newToken) {
            headers["Authorization"] = `Bearer ${newToken}`;

            const retryResponse = await fetch(url, {
              ...fetchOptions,
              headers,
            });


            return this.parseResponse<T>(retryResponse);
          } else {
            console.warn("Token refresh completed without a replacement token");
          }
        } catch {
          console.error("Token refresh failed");
          throw new Error("Session expired. Please login again.");
        }
      }

      return this.parseResponse<T>(response);
    } catch (error) {
      // Clear timeout on error
      if (timeoutId) {
        clearTimeout(timeoutId);
      }

      // Handle abort error (timeout)
      if (error instanceof Error && error.name === "AbortError") {
        console.error("API request timed out");

        return {
          success: false,
          error: {
            code: "REQUEST_TIMEOUT",
            message: `Request timed out after ${timeout ? timeout / 1000 : "?"} seconds`,
            details: { timeout, url, method: fetchOptions.method || "GET" },
          },
        };
      }

      console.error("API request failed");
      return {
        success: false,
        error: {
          code: "NETWORK_ERROR",
          message:
            error instanceof Error ? error.message : "Network error occurred",
        },
      };
    }
  }

  private async parseResponse<T>(response: Response): Promise<APIResponse<T>> {

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
  ): Promise<APIResponse<T>> {
    const url = params
      ? `${endpoint}?${new URLSearchParams(params).toString()}`
      : endpoint;

    return this.request<T>(url, { method: "GET" });
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

// Create and configure the main API client
// In production with Nginx proxy, use relative URLs to avoid CORS
// In development, use full URL to backend
export const getApiBaseUrl = () => {
  // If NEXT_PUBLIC_API_URL is set (from build-time env), use it
  if (process.env.NEXT_PUBLIC_API_URL) {
    return process.env.NEXT_PUBLIC_API_URL;
  }

  // Otherwise, detect environment
  // In browser, check if we're on localhost development or production
  if (typeof window !== "undefined") {
    const isDev =
      window.location.hostname === "localhost" &&
      window.location.port === "3000";
    return isDev ? "http://localhost:8000" : "";
  }

  // Server-side rendering: default to localhost for development
  return "http://localhost:8000";
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
