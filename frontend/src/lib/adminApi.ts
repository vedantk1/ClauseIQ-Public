/**
 * Admin API client for admin portal operations
 */

import { apiClient, APIResponse } from "./api";

// ================== Types ==================

export interface AdminStats {
  user_count: number;
  document_count: number;
  recent_documents_7d: number;
  recent_users_7d: number;
  contract_type_breakdown: { type: string; count: number }[];
}

export interface UserListItem {
  id: string;
  email: string;
  full_name: string;
  created_at?: string;
  updated_at?: string;
  preferred_model?: string;
}

export interface UserDetail extends UserListItem {
  document_count: number;
  recent_documents: {
    id: string;
    filename: string;
    contract_type?: string;
    created_at?: string;
  }[];
}

export interface DocumentListItem {
  id: string;
  user_id: string;
  filename: string;
  contract_type?: string;
  created_at?: string;
  updated_at?: string;
  has_pdf_file?: boolean;
  rag_processed?: boolean;
  ready_for_chat?: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface DeleteUserResult {
  user_deleted: boolean;
  documents_deleted: number;
  errors: string[];
}

export interface BulkDeleteResult {
  deleted_count: number;
  failed_ids: string[];
  errors: string[];
}

export interface CollectionInfo {
  name: string;
  document_count: number;
  indexes: { name: string; keys: Record<string, number>; unique: boolean }[];
  sample_document?: Record<string, unknown>;
}

export interface DatabaseSchema {
  database_name: string;
  collections: CollectionInfo[];
  total_size_mb?: number;
}

export interface AuditLogEntry {
  timestamp: string;
  level: string;
  message: string;
  source?: string;
  user_id?: string;
  action?: string;
}

export interface CreateUserRequest {
  email: string;
  full_name: string;
  password: string;
}

export interface UpdateUserRequest {
  email?: string;
  full_name?: string;
  password?: string;
  preferred_model?: string;
}

export interface AutoDeleteConfig {
  enabled: boolean;
  days: number;
  configured_at: string | null;
  updated_by: string | null;
}

export interface AutoDeleteCleanupResult {
  deleted_count: number;
  failed_count: number;
  errors: string[];
  run_at: string;
  skipped?: boolean;
  reason?: string;
}

export interface DocumentLimitConfig {
  enabled: boolean;
  max_documents: number;
  configured_at: string | null;
  updated_by: string | null;
}

export interface UISettingsConfig {
  toast_notifications_enabled: boolean;
  configured_at: string | null;
  updated_by: string | null;
}

export interface SystemAIModelConfig {
  model_id: string;
  model_name: string;
  model_description: string;
  configured_at: string | null;
  updated_by: string | null;
}

export interface QueryGateModelConfig {
  model_id: string;
  model_name: string;
  model_description: string;
  configured_at: string | null;
  updated_by: string | null;
}

export interface AvailableAIModel {
  id: string;
  name: string;
  description: string;
  is_current: boolean;
}

export interface AvailableAIModelsResponse {
  models: AvailableAIModel[];
  current_model_id: string;
}

// ================== Admin API ==================

export const adminApi = {
  // Access check
  async checkAccess(): Promise<
    APIResponse<{ is_admin: boolean; email: string; user_id: string }>
  > {
    return apiClient.get("/admin/check-access");
  },

  // Stats
  async getStats(): Promise<APIResponse<AdminStats>> {
    return apiClient.get("/admin/stats");
  },

  // Users
  async listUsers(params?: {
    limit?: number;
    offset?: number;
    search?: string;
  }): Promise<APIResponse<PaginatedResponse<UserListItem>>> {
    const queryParams: Record<string, string> = {};
    if (params?.limit) queryParams.limit = params.limit.toString();
    if (params?.offset) queryParams.offset = params.offset.toString();
    if (params?.search) queryParams.search = params.search;
    return apiClient.get("/admin/users", queryParams);
  },

  async getUser(userId: string): Promise<APIResponse<UserDetail>> {
    return apiClient.get(`/admin/users/${userId}`);
  },

  async createUser(
    data: CreateUserRequest,
  ): Promise<APIResponse<UserListItem>> {
    return apiClient.post("/admin/users", data);
  },

  async updateUser(
    userId: string,
    data: UpdateUserRequest,
  ): Promise<APIResponse<UserListItem>> {
    return apiClient.put(`/admin/users/${userId}`, data);
  },

  async deleteUser(userId: string): Promise<APIResponse<DeleteUserResult>> {
    return apiClient.delete(`/admin/users/${userId}`);
  },

  async bulkDeleteUsers(ids: string[]): Promise<APIResponse<BulkDeleteResult>> {
    return apiClient.post("/admin/users/bulk-delete", { ids });
  },

  // Documents
  async listDocuments(params?: {
    limit?: number;
    offset?: number;
    user_id?: string;
    search?: string;
  }): Promise<APIResponse<PaginatedResponse<DocumentListItem>>> {
    const queryParams: Record<string, string> = {};
    if (params?.limit) queryParams.limit = params.limit.toString();
    if (params?.offset) queryParams.offset = params.offset.toString();
    if (params?.user_id) queryParams.user_id = params.user_id;
    if (params?.search) queryParams.search = params.search;
    return apiClient.get("/admin/documents", queryParams);
  },

  async deleteDocument(
    docId: string,
    userId: string,
  ): Promise<APIResponse<{ deleted: boolean }>> {
    return apiClient.delete(`/admin/documents/${docId}?user_id=${userId}`);
  },

  async bulkDeleteDocuments(
    ids: string[],
    userId: string,
  ): Promise<APIResponse<BulkDeleteResult>> {
    return apiClient.post(`/admin/documents/bulk-delete?user_id=${userId}`, {
      ids,
    });
  },

  // Database
  async getDatabaseSchema(): Promise<APIResponse<DatabaseSchema>> {
    return apiClient.get("/admin/database/schema");
  },

  async browseCollection(
    collectionName: string,
    params?: { limit?: number; offset?: number },
  ): Promise<APIResponse<PaginatedResponse<Record<string, unknown>>>> {
    const queryParams: Record<string, string> = {};
    if (params?.limit) queryParams.limit = params.limit.toString();
    if (params?.offset) queryParams.offset = params.offset.toString();
    return apiClient.get(
      `/admin/database/collection/${collectionName}`,
      queryParams,
    );
  },

  // Logs
  async getLogs(params?: {
    limit?: number;
    offset?: number;
    level?: string;
    search?: string;
  }): Promise<APIResponse<PaginatedResponse<AuditLogEntry>>> {
    const queryParams: Record<string, string> = {};
    if (params?.limit) queryParams.limit = params.limit.toString();
    if (params?.offset) queryParams.offset = params.offset.toString();
    if (params?.level) queryParams.level = params.level;
    if (params?.search) queryParams.search = params.search;
    return apiClient.get("/admin/logs", queryParams);
  },

  // System AI Model Configuration
  async getSystemAIModel(): Promise<APIResponse<SystemAIModelConfig>> {
    return apiClient.get("/admin/ai-model");
  },

  async getAvailableAIModels(): Promise<
    APIResponse<AvailableAIModelsResponse>
  > {
    return apiClient.get("/admin/ai-model/available");
  },

  async setSystemAIModel(
    modelId: string,
  ): Promise<APIResponse<SystemAIModelConfig>> {
    return apiClient.put("/admin/ai-model", { model_id: modelId });
  },

  // Query Gate Model Configuration
  async getQueryGateModel(): Promise<APIResponse<QueryGateModelConfig>> {
    return apiClient.get("/admin/query-gate-model");
  },

  async setQueryGateModel(
    modelId: string,
  ): Promise<APIResponse<QueryGateModelConfig>> {
    return apiClient.put("/admin/query-gate-model", { model_id: modelId });
  },

  // Auto-Delete Settings
  async getAutoDeleteConfig(): Promise<APIResponse<AutoDeleteConfig>> {
    return apiClient.get("/admin/settings/auto-delete");
  },

  async setAutoDeleteConfig(
    days: number,
  ): Promise<APIResponse<AutoDeleteConfig>> {
    return apiClient.put("/admin/settings/auto-delete", { days });
  },

  async runAutoDeleteCleanup(): Promise<APIResponse<AutoDeleteCleanupResult>> {
    return apiClient.post("/admin/settings/auto-delete/run-cleanup", {});
  },

  // Document Limit Settings
  async getDocumentLimitConfig(): Promise<APIResponse<DocumentLimitConfig>> {
    return apiClient.get("/admin/settings/document-limit");
  },

  async setDocumentLimitConfig(
    maxDocuments: number,
  ): Promise<APIResponse<DocumentLimitConfig>> {
    return apiClient.put("/admin/settings/document-limit", {
      max_documents: maxDocuments,
    });
  },

  // UI Settings
  async getUISettings(): Promise<APIResponse<UISettingsConfig>> {
    return apiClient.get("/admin/settings/ui");
  },

  async setUISettings(
    toastEnabled: boolean,
  ): Promise<APIResponse<UISettingsConfig>> {
    return apiClient.put("/admin/settings/ui", {
      toast_notifications_enabled: toastEnabled,
    });
  },
};

export default adminApi;
