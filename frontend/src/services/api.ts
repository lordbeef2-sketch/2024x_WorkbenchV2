import {
  AuthOptions,
  CapabilitySummary,
  CompareResult,
  DashboardPayload,
  ItemDetails,
  OSLCAuthorizationStatus,
  OSLCGenerateConsumerRequest,
  OSLCGenerateConsumerResponse,
  OSLCStoreConsumerRequest,
  OSLCExecuteRequest,
  OSLCExecuteResponse,
  ProjectSummary,
  ServerHealth,
  ServerProfile,
  ServerProfileInput,
  SessionPreferences,
  SessionSnapshot,
  SwaggerContractManifest,
  SwaggerExecuteRequest,
  SwaggerExecuteResponse,
  TokenLoginRequest,
  TreeNode,
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

  if (!response.ok) {
    let message = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: string };
      message = payload.detail ?? message;
    } catch {
      const text = await response.text();
      message = text || message;
    }
    throw new ApiError(message, response.status);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return (await response.json()) as T;
  }

  return (await response.text()) as T;
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
  oslcSignInUrl() {
    return `${API_BASE}/auth/oslc/signin`;
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
  getOslcStatus() {
    return request<OSLCAuthorizationStatus>("/workspace/oslc/status");
  },
  executeOslcRequest(payload: OSLCExecuteRequest, csrfToken: string) {
    return request<OSLCExecuteResponse>("/workspace/oslc/request", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  disconnectOslc(csrfToken: string) {
    return request<{ ok: boolean }>("/workspace/oslc/disconnect", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
    });
  },
  generateOslcConsumer(payload: OSLCGenerateConsumerRequest, csrfToken: string) {
    return request<OSLCGenerateConsumerResponse>("/workspace/oslc/consumer/generate", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  storeOslcConsumer(payload: OSLCStoreConsumerRequest, csrfToken: string) {
    return request<OSLCAuthorizationStatus>("/workspace/oslc/consumer/session", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  clearOslcConsumer(csrfToken: string) {
    return request<{ ok: boolean }>("/workspace/oslc/consumer/session", {
      method: "DELETE",
      headers: jsonHeaders(csrfToken),
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
  getProjects() {
    return request<ProjectSummary[]>("/workspace/projects");
  },
  getTree(projectId?: string, branchId?: string) {
    const params = new URLSearchParams();
    if (projectId) {
      params.set("projectId", projectId);
    }
    if (branchId) {
      params.set("branchId", branchId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<TreeNode[]>(`/workspace/tree${suffix}`);
  },
  getItem(itemId: string, projectId?: string, branchId?: string) {
    const params = new URLSearchParams();
    if (projectId) {
      params.set("projectId", projectId);
    }
    if (branchId) {
      params.set("branchId", branchId);
    }
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return request<ItemDetails>(`/workspace/items/${itemId}${suffix}`);
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
  refreshCapabilities(csrfToken: string) {
    return request<CapabilitySummary>("/workspace/capabilities/refresh", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
    });
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
};
