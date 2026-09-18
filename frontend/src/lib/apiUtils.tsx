"use client";

import { apiClient } from "@/lib/api";

/**
 * A fetch-like interface for callers using the centralized local API client.
 */
export const useApiCall = () => {
  return async (endpoint: string, options: RequestInit = {}) => {

    try {
      const method = (options.method || "GET").toUpperCase();
      let apiResponse;

      // Parse body data
      let data;
      if (options.body) {

        if (options.body instanceof FormData) {
          data = options.body;
        } else if (typeof options.body === "string") {
          try {
            data = JSON.parse(options.body);
          } catch {
            data = options.body;
          }
        } else {
          data = options.body;
        }
      }


      // Call appropriate method on apiClient
      switch (method) {
        case "GET":
          apiResponse = await apiClient.get(endpoint);
          break;
        case "POST":
          apiResponse = await apiClient.post(endpoint, data);
          break;
        case "PUT":
          apiResponse = await apiClient.put(endpoint, data);
          break;
        case "PATCH":
          apiResponse = await apiClient.patch(endpoint, data);
          break;
        case "DELETE":
          apiResponse = await apiClient.delete(endpoint);
          break;
        default:
          throw new Error(`Unsupported HTTP method: ${method}`);
      }



      // Convert APIResponse back to fetch-like response for backwards compatibility
      const fetchResponse = {
        ok: apiResponse.success,
        status: apiResponse.success ? 200 : 400,
        statusText: apiResponse.success ? "OK" : "Error",
        json: async () => {
          if (apiResponse.success) {
            return apiResponse.data;
          } else {
            throw new Error(apiResponse.error?.message || "API Error");
          }
        },
        text: async () => {
          if (apiResponse.success) {
            return JSON.stringify(apiResponse.data);
          } else {
            return apiResponse.error?.message || "API Error";
          }
        },
      };

      return fetchResponse;
    } catch (error) {
      console.error("API request failed");
      throw error;
    }
  };
};
