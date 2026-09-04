/**
 * 🛡️ ZERO-RISK COMPATIBILITY LAYER FOR DOCUMENTCHAT
 *
 * 🚀 FOUNDATIONAL ARCHITECTURE READY!
 *
 * This creates a bridge between raw fetch() and apiClient while maintaining
 * 100% backward compatibility with existing DocumentChat code.
 *
 * STRATEGY: Replace fetch calls one-by-one without changing any other logic.
 *
 * 🎯 FOUNDATIONAL ENDPOINTS AVAILABLE:
 * - /{document_id}/session (get/create THE session)
 * - /{document_id}/message (send message without session_id)
 * - /{document_id}/history (get chat history)
 */

import { apiClient } from "@/lib/api";

/**
 * Compatible wrapper that mimics exact fetch() behavior DocumentChat expects
 */
export const createCompatibleDocumentChatClient = () => {
  return {
    /**
     * GET request that returns fetch-compatible response
     */
    async get(endpoint: string): Promise<{
      ok: boolean;
      status: number;
      statusText: string;
      json: () => Promise<unknown>;
    }> {

      const chatEndpoint = `/chat${endpoint}`;
      const apiResponse = await apiClient.get(chatEndpoint);

      // Create fetch-compatible response object
      return {
        ok: apiResponse.success,
        status: apiResponse.success ? 200 : 400,
        statusText: apiResponse.success ? "OK" : "Error",
        json: async () => {
          if (apiResponse.success) {
            // Return in format DocumentChat expects: {data: actualData}
            return {
              data: apiResponse.data,
            };
          } else {
            // Return error in format DocumentChat expects
            throw new Error(apiResponse.error?.message || "API Error");
          }
        },
      };
    },

    /**
     * POST request that returns fetch-compatible response
     */
    async post(
      endpoint: string,
      body: Record<string, unknown>
    ): Promise<{
      ok: boolean;
      status: number;
      statusText: string;
      json: () => Promise<unknown>;
    }> {

      const chatEndpoint = `/chat${endpoint}`;
      const apiResponse = await apiClient.post(chatEndpoint, body);

      // Create fetch-compatible response object
      return {
        ok: apiResponse.success,
        status: apiResponse.success ? 200 : 400,
        statusText: apiResponse.success ? "OK" : "Error",
        json: async () => {
          if (apiResponse.success) {
            // Return in format DocumentChat expects: {data: actualData}
            return {
              data: apiResponse.data,
            };
          } else {
            // Return error in format DocumentChat expects
            return {
              detail: {
                message: apiResponse.error?.message || "API Error",
              },
            };
          }
        },
      };
    },

    // 🚀 FOUNDATIONAL ARCHITECTURE METHODS

    /**
     * 🎯 Get or create THE session for a document (foundational architecture)
     */
    async getOrCreateSession(documentId: string): Promise<{
      ok: boolean;
      status: number;
      statusText: string;
      json: () => Promise<unknown>;
    }> {

      try {
        const response = await apiClient.post(
          `/chat/${documentId}/session`,
          {}
        );


        return {
          ok: response.success,
          status: response.success ? 200 : 400,
          statusText: response.success ? "OK" : "Bad Request",
          json: async () => {
            // Wrap in the format DocumentChat expects: {data: actualData}
            return {
              data: response.data,
            };
          },
        };
      } catch {
        console.error("💥 [Foundational] Session creation error:");
        return {
          ok: false,
          status: 500,
          statusText: "Internal Server Error",
          json: async () => ({ error: "Network error" }),
        };
      }
    },

    /**
     * 🎯 Send message using foundational architecture (no session_id needed!)
     */
    async sendMessageFoundational(
      documentId: string,
      message: string
    ): Promise<{
      ok: boolean;
      status: number;
      statusText: string;
      json: () => Promise<unknown>;
    }> {

      try {
        const response = await apiClient.post(`/chat/${documentId}/message`, {
          message: message,
        });


        return {
          ok: response.success,
          status: response.success ? 200 : 400,
          statusText: response.success ? "OK" : "Bad Request",
          json: async () => {
            // Wrap in the format DocumentChat expects: {data: actualData}
            return {
              data: response.data,
            };
          },
        };
      } catch {
        console.error("💥 [Foundational] Message send error:");
        return {
          ok: false,
          status: 500,
          statusText: "Internal Server Error",
          json: async () => ({ error: "Network error" }),
        };
      }
    },

    /**
     * 🎯 Get chat history using foundational architecture
     */
    async getChatHistory(documentId: string): Promise<{
      ok: boolean;
      status: number;
      statusText: string;
      json: () => Promise<unknown>;
    }> {

      try {
        const response = await apiClient.get(`/chat/${documentId}/history`);


        return {
          ok: response.success,
          status: response.success ? 200 : 400,
          statusText: response.success ? "OK" : "Bad Request",
          json: async () => {
            // Wrap in the format DocumentChat expects: {data: actualData}
            return {
              data: response.data,
            };
          },
        };
      } catch {
        console.error("💥 [Foundational] History retrieval error:");
        return {
          ok: false,
          status: 500,
          statusText: "Internal Server Error",
          json: async () => ({ error: "Network error" }),
        };
      }
    },

    /**
     * 🗑️ Clear chat history for a document
     */
    async clearChatHistory(documentId: string): Promise<{
      ok: boolean;
      status: number;
      statusText: string;
      json: () => Promise<unknown>;
    }> {

      try {
        const response = await apiClient.delete(`/chat/${documentId}/history`);


        return {
          ok: response.success,
          status: response.success ? 200 : 400,
          statusText: response.success ? "OK" : "Bad Request",
          json: async () => {
            if (response.success) {
              // Return in format DocumentChat expects: {data: actualData}
              return {
                data: response.data,
              };
            } else {
              // Return error in format DocumentChat expects
              throw new Error(
                response.error?.message || "Failed to clear chat history"
              );
            }
          },
        };
      } catch {
        console.error("💥 [DocumentChat-Compat] Clear history error:");
        return {
          ok: false,
          status: 500,
          statusText: "Internal Server Error",
          json: async () => ({ error: "Network error" }),
        };
      }
    },
  };
};

// Export singleton instance
export const documentChatApi = createCompatibleDocumentChatClient();
