import {
  AuthOptions,
  BranchAccessManifestStatus,
  CacheElementSearchResponse,
  CacheApiKeyCreateRequest,
  CacheApiKeyCreateResponse,
  CacheApiKeySummary,
  CacheApiManifest,
  StereotypeElementSearchResponse,
  CacheServerEntry,
  CacheIngestTokenRequest,
  BranchSummary,
  BranchTombstoneRecord,
  CacheIngestTokenRotateResponse,
  CacheIngestTokenStatus,
  CapabilitySummary,
  CompareResult,
  CurrentPermissionStatus,
  DashboardPayload,
  ItemDetails,
  JobRecord,
  ProjectSummary,
  ProjectTombstoneRecord,
  ProjectUsageResponse,
  ServerHealth,
  ServerPermissionInventoryStatus,
  ServerProfile,
  ServerProfileInput,
  SessionPreferences,
  SessionSnapshot,
  SwaggerContractManifest,
  SwaggerExecuteRequest,
  SwaggerExecuteResponse,
  TokenLoginRequest,
  TreeNode,
  OpenWebUIModelEntry,
  WorkbenchAuthAdminStatus,
  WorkbenchAgentChatRequest,
  WorkbenchAgentChatResponse,
  WorkbenchAgentConfigRequest,
  WorkbenchAgentStatus,
  WorkbenchFirstAdminSetupRequest,
  WorkbenchLocalLoginRequest,
  WorkbenchUserCreateRequest,
  WorkbenchUserSummary,
  WorkbenchUserUpdateRequest,
} from "../models/api";

const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...options,
  });

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  const bodyText = await response.text();

  if (!response.ok) {
    let message = response.statusText;
    if (bodyText) {
      if (contentType.includes("application/json")) {
        try {
          const payload = JSON.parse(bodyText) as { detail?: string };
          message = payload.detail ?? bodyText;
        } catch {
          message = bodyText;
        }
      } else {
        message = bodyText;
      }
    }
    throw new ApiError(message, response.status);
  }

  if (!bodyText) {
    return undefined as T;
  }

  if (contentType.includes("application/json")) {
    return JSON.parse(bodyText) as T;
  }

  return bodyText as T;
}

function jsonHeaders(csrfToken?: string) {
  return {
    "Content-Type": "application/json",
    ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
  };
}

export const api = {
  errorClass: ApiError,
  signInUrl(serverId: string) {
    return `${API_BASE}/auth/signin/${serverId}`;
  },
  getSession() {
    return request<SessionSnapshot>("/auth/session");
  },
  getAuthOptions() {
    return request<AuthOptions>("/auth/options");
  },
  logout(csrfToken: string) {
    return request<{ ok: boolean }>("/auth/logout", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
    });
  },
  tokenLogin(payload: TokenLoginRequest) {
    return request<SessionSnapshot>("/auth/token", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });
  },
  localLogin(payload: WorkbenchLocalLoginRequest) {
    return request<SessionSnapshot>("/auth/local", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });
  },
  setupFirstWorkbenchAdmin(payload: WorkbenchFirstAdminSetupRequest) {
    return request<SessionSnapshot>("/auth/local/setup-first-admin", {
      method: "POST",
      headers: jsonHeaders(),
      body: JSON.stringify(payload),
    });
  },
  getAuthManagementStatus() {
    return request<WorkbenchAuthAdminStatus>("/auth/management/status");
  },
  updateAuthManagementSettings(payload: Partial<WorkbenchAuthAdminStatus["settings"]>, csrfToken: string) {
    return request<WorkbenchAuthAdminStatus>("/auth/management/settings", {
      method: "PUT",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  listWorkbenchUsers() {
    return request<WorkbenchUserSummary[]>("/auth/management/users");
  },
  createWorkbenchUser(payload: WorkbenchUserCreateRequest, csrfToken: string) {
    return request<WorkbenchUserSummary>("/auth/management/users", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  updateWorkbenchUser(username: string, payload: WorkbenchUserUpdateRequest, csrfToken: string) {
    return request<WorkbenchUserSummary>(`/auth/management/users/${encodeURIComponent(username)}`, {
      method: "PUT",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  deleteWorkbenchUser(username: string, csrfToken: string) {
    return request<{ ok: boolean }>(`/auth/management/users/${encodeURIComponent(username)}`, {
      method: "DELETE",
      headers: jsonHeaders(csrfToken),
    });
  },
  listServers() {
    return request<ServerProfile[]>("/servers");
  },
  listManagedServers() {
    return request<ServerProfile[]>("/servers/manage");
  },
  createServer(payload: ServerProfileInput, csrfToken: string) {
    return request<ServerProfile>("/servers", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  updateServer(serverId: string, payload: Partial<ServerProfileInput>, csrfToken: string) {
    return request<ServerProfile>(`/servers/${serverId}`, {
      method: "PUT",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  deleteServer(serverId: string, csrfToken: string) {
    return request<void>(`/servers/${serverId}`, {
      method: "DELETE",
      headers: jsonHeaders(csrfToken),
    });
  },
  reorderServers(serverIds: string[], csrfToken: string) {
    return request<ServerProfile[]>("/servers/reorder", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify({ server_ids: serverIds }),
    });
  },
  getServerHealth(serverId: string) {
    return request<ServerHealth>(`/servers/${serverId}/health`);
  },
  getDashboard() {
    return request<DashboardPayload>("/workspace/dashboard");
  },
  getCacheIngestTokenStatus() {
    return request<CacheIngestTokenStatus>("/workspace/cache-ingest-token");
  },
  getPermissionInventoryStatus() {
    return request<ServerPermissionInventoryStatus>("/workspace/permission-inventory/status");
  },
  retryPermissionInventory(csrfToken: string) {
    return request<JobRecord>("/workspace/permission-inventory/retry", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
    });
  },
  listBranchTombstones() {
    return request<BranchTombstoneRecord[]>("/workspace/branch-tombstones?limit=20");
  },
  listProjectTombstones() {
    return request<ProjectTombstoneRecord[]>("/workspace/project-tombstones?limit=20");
  },
  listCacheApiKeys() {
    return request<CacheApiKeySummary[]>("/workspace/cache-api-keys");
  },
  createCacheApiKey(payload: CacheApiKeyCreateRequest, csrfToken: string) {
    return request<CacheApiKeyCreateResponse>("/workspace/cache-api-keys", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  deleteCacheApiKey(keyId: string, csrfToken: string) {
    return request<{ ok: boolean }>(`/workspace/cache-api-keys/${keyId}`, {
      method: "DELETE",
      headers: jsonHeaders(csrfToken),
    });
  },
  rotateCacheIngestToken(csrfToken: string) {
    return request<CacheIngestTokenRotateResponse>("/workspace/cache-ingest-token/rotate", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
    });
  },
  updateCacheIngestToken(payload: CacheIngestTokenRequest, csrfToken: string) {
    return request<CacheIngestTokenStatus>("/workspace/cache-ingest-token", {
      method: "PUT",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  clearCacheIngestToken(csrfToken: string) {
    return request<CacheIngestTokenStatus>("/workspace/cache-ingest-token", {
      method: "DELETE",
      headers: jsonHeaders(csrfToken),
    });
  },
  getCacheApiManifest(token: string) {
    return request<CacheApiManifest>("/cache", {
      headers: { Authorization: `Bearer ${token}` },
      credentials: "omit",
    });
  },
  getCachedServers(token: string) {
    return request<CacheServerEntry[]>("/cache/servers", {
      headers: { Authorization: `Bearer ${token}` },
      credentials: "omit",
    });
  },
  getContractManifest() {
    return request<SwaggerContractManifest>("/workspace/contract");
  },
  executeContractOperation(payload: SwaggerExecuteRequest, csrfToken: string) {
    return request<SwaggerExecuteResponse>("/workspace/contract/execute", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  executeContractUpload(
    operationKey: string,
    pathParams: Record<string, unknown>,
    queryParams: Record<string, unknown>,
    file: File,
    csrfToken: string,
  ) {
    const body = new FormData();
    body.set("operationKey", operationKey);
    body.set("pathParams", JSON.stringify(pathParams));
    body.set("queryParams", JSON.stringify(queryParams));
    body.set("file", file);
    return request<SwaggerExecuteResponse>("/workspace/contract/execute-upload", {
      method: "POST",
      headers: csrfToken ? { "X-CSRF-Token": csrfToken } : undefined,
      body,
    });
  },
  getProjects(refresh = false) {
    const params = new URLSearchParams();
    if (refresh) {
      params.set("refresh", "true");
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<ProjectSummary[]>(`/workspace/projects${suffix}`);
  },
  getProjectBranches(projectId: string, workspaceId?: string, refresh = false) {
    const params = new URLSearchParams();
    if (workspaceId) {
      params.set("workspaceId", workspaceId);
    }
    if (refresh) {
      params.set("refresh", "true");
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<BranchSummary[]>(`/workspace/projects/${projectId}/branches${suffix}`);
  },
  getProjectUsages(projectId: string, branchId: string, workspaceId?: string, refresh = false) {
    const params = new URLSearchParams();
    if (workspaceId) {
      params.set("workspaceId", workspaceId);
    }
    if (refresh) {
      params.set("refresh", "true");
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<ProjectUsageResponse>(`/workspace/projects/${projectId}/branches/${branchId}/usages${suffix}`);
  },
  getTree(projectId?: string, branchId?: string, workspaceId?: string, refresh = false, depth?: number) {
    const params = new URLSearchParams();
    if (projectId) {
      params.set("projectId", projectId);
    }
    if (branchId) {
      params.set("branchId", branchId);
    }
    if (workspaceId) {
      params.set("workspaceId", workspaceId);
    }
    if (refresh) {
      params.set("refresh", "true");
    }
    if (typeof depth === "number") {
      params.set("depth", String(depth));
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<TreeNode[]>(`/workspace/tree${suffix}`);
  },
  getTreeChildren(projectId: string, branchId: string, parentId: string, modelId?: string, workspaceId?: string, refresh = false) {
    const params = new URLSearchParams({
      projectId,
      branchId,
      parentId,
    });
    if (modelId) {
      params.set("modelId", modelId);
    }
    if (workspaceId) {
      params.set("workspaceId", workspaceId);
    }
    if (refresh) {
      params.set("refresh", "true");
    }
    return request<TreeNode[]>(`/workspace/tree/children?${params.toString()}`);
  },
  getBranchAccessManifestStatus(projectId: string, branchId: string) {
    const params = new URLSearchParams({ projectId, branchId });
    return request<BranchAccessManifestStatus>(`/workspace/model-cache/access-map?${params.toString()}`);
  },
  refreshBranchAccessManifest(projectId: string, branchId: string, csrfToken: string) {
    const params = new URLSearchParams({ projectId, branchId });
    return request<BranchAccessManifestStatus>(`/workspace/model-cache/access-map/refresh?${params.toString()}`, {
      method: "POST",
      headers: jsonHeaders(csrfToken),
    });
  },
  getItem(itemId: string, projectId?: string, branchId?: string, workspaceId?: string, refresh = false) {
    const params = new URLSearchParams();
    if (projectId) {
      params.set("projectId", projectId);
    }
    if (branchId) {
      params.set("branchId", branchId);
    }
    if (workspaceId) {
      params.set("workspaceId", workspaceId);
    }
    if (refresh) {
      params.set("refresh", "true");
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<ItemDetails>(`/workspace/items/${itemId}${suffix}`);
  },
  searchCachedElements(
    payload: {
      projectId: string;
      branchId: string;
      q?: string;
      itemType?: string;
      metaclass?: string;
      stereotype?: string;
      ownerId?: string;
      includeDetails?: boolean;
      limit?: number;
      offset?: number;
    },
  ) {
    const params = new URLSearchParams({
      projectId: payload.projectId,
      branchId: payload.branchId,
    });
    if (payload.q) {
      params.set("q", payload.q);
    }
    if (payload.itemType) {
      params.set("itemType", payload.itemType);
    }
    if (payload.metaclass) {
      params.set("metaclass", payload.metaclass);
    }
    if (payload.stereotype) {
      params.set("stereotype", payload.stereotype);
    }
    if (payload.ownerId) {
      params.set("ownerId", payload.ownerId);
    }
    if (typeof payload.includeDetails === "boolean") {
      params.set("includeDetails", String(payload.includeDetails));
    }
    if (typeof payload.limit === "number") {
      params.set("limit", String(payload.limit));
    }
    if (typeof payload.offset === "number") {
      params.set("offset", String(payload.offset));
    }
    return request<CacheElementSearchResponse>(`/workspace/model-cache/elements/search?${params.toString()}`);
  },
  searchCachedElementsByStereotype(
    payload: {
      projectId: string;
      branchId: string;
      stereotype: string;
      includeDetails?: boolean;
      limit?: number;
      offset?: number;
    },
  ) {
    const params = new URLSearchParams({
      projectId: payload.projectId,
      branchId: payload.branchId,
      stereotype: payload.stereotype,
    });
    if (typeof payload.includeDetails === "boolean") {
      params.set("includeDetails", String(payload.includeDetails));
    }
    if (typeof payload.limit === "number") {
      params.set("limit", String(payload.limit));
    }
    if (typeof payload.offset === "number") {
      params.set("offset", String(payload.offset));
    }
    return request<StereotypeElementSearchResponse>(`/workspace/model-cache/elements/by-stereotype?${params.toString()}`);
  },
  updateItem(itemId: string, payload: Partial<ItemDetails>, csrfToken: string, projectId?: string, branchId?: string) {
    const params = new URLSearchParams();
    if (projectId) {
      params.set("projectId", projectId);
    }
    if (branchId) {
      params.set("branchId", branchId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<ItemDetails>(`/workspace/items/${itemId}${suffix}`, {
      method: "PUT",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  compare(
    leftId: string,
    rightId: string,
    leftProjectId?: string,
    leftBranchId?: string,
    rightProjectId?: string,
    rightBranchId?: string,
  ) {
    const params = new URLSearchParams({
      leftId,
      rightId,
    });
    if (leftProjectId) {
      params.set("leftProjectId", leftProjectId);
    }
    if (leftBranchId) {
      params.set("leftBranchId", leftBranchId);
    }
    if (rightProjectId) {
      params.set("rightProjectId", rightProjectId);
    }
    if (rightBranchId) {
      params.set("rightBranchId", rightBranchId);
    }
    return request<CompareResult>(`/workspace/compare?${params.toString()}`);
  },
  compareBranches(leftProjectId: string, leftBranchId: string, rightProjectId: string, rightBranchId: string) {
    const params = new URLSearchParams({
      leftProjectId,
      leftBranchId,
      rightProjectId,
      rightBranchId,
    });
    return request<CompareResult>(`/workspace/compare/branches?${params.toString()}`);
  },
  refreshCapabilities(
    csrfToken: string,
    payload?: { selected_project_id?: string; selected_branch_id?: string; selected_model_id?: string },
  ) {
    return request<CapabilitySummary>("/workspace/capabilities/refresh", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload ?? {}),
    });
  },
  getCurrentPermissionStatus(projectId: string, branchId: string, modelId?: string) {
    const params = new URLSearchParams({ projectId, branchId });
    if (modelId) {
      params.set("modelId", modelId);
    }
    return request<CurrentPermissionStatus>(`/workspace/permissions/current?${params.toString()}`);
  },
  getPreferences() {
    return request<SessionPreferences>("/workspace/preferences");
  },
  updatePreferences(payload: SessionPreferences, csrfToken: string) {
    return request<SessionPreferences>("/workspace/preferences", {
      method: "PUT",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  getWorkbenchAgentStatus() {
    return request<WorkbenchAgentStatus>("/workspace/agent");
  },
  updateWorkbenchAgentConfig(payload: WorkbenchAgentConfigRequest, csrfToken: string) {
    return request<WorkbenchAgentStatus>("/workspace/agent", {
      method: "PUT",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  clearWorkbenchAgentConfig(csrfToken: string) {
    return request<WorkbenchAgentStatus>("/workspace/agent", {
      method: "DELETE",
      headers: jsonHeaders(csrfToken),
    });
  },
  listWorkbenchAgentModels() {
    return request<OpenWebUIModelEntry[]>("/workspace/agent/models");
  },
  startWorkbenchAgentKnowledgeSync(payload: { project_id: string; branch_id: string }, csrfToken: string) {
    return request<JobRecord>("/workspace/agent/knowledge/sync", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  getJob(jobId: string) {
    return request<JobRecord>(`/workspace/jobs/${jobId}`);
  },
  runWorkbenchAgentChat(payload: WorkbenchAgentChatRequest, csrfToken: string) {
    return request<WorkbenchAgentChatResponse>("/workspace/agent/chat", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
};
