import {
  AttachmentInfo,
  AuthOptions,
  Bookmark,
  BranchSummary,
  BranchUpdateRequest,
  CollaboratorDocument,
  CommentEntry,
  CompareResult,
  DashboardPayload,
  ExportRequest,
  JobRecord,
  ProjectSummary,
  SavedSearch,
  SearchResponse,
  ServerHealth,
  ServerProfile,
  ServerProfileInput,
  SessionPreferences,
  SessionSnapshot,
  SimulationConfig,
  SimulationRunRequest,
  TokenLoginRequest,
  TreeNode,
  ItemDetails,
  PublishRequest,
  CapabilitySummary,
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
  jobArtifactUrl(jobId: string) {
    return `${API_BASE}/jobs/${jobId}/artifact`;
  },
  attachmentDownloadUrl(documentId: string, attachmentId: string) {
    return `${API_BASE}/workspace/collaborator/documents/${documentId}/attachments/${attachmentId}/download`;
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
  getProjects() {
    return request<ProjectSummary[]>("/workspace/projects");
  },
  updateBranch(projectId: string, branchId: string, payload: BranchUpdateRequest, csrfToken: string) {
    return request<BranchSummary>(`/workspace/projects/${projectId}/branches/${branchId}`, {
      method: "PATCH",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
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
  search(query: string) {
    return request<SearchResponse>(`/workspace/search?query=${encodeURIComponent(query)}`);
  },
  compare(leftId: string, rightId: string) {
    return request<CompareResult>(`/workspace/compare?leftId=${encodeURIComponent(leftId)}&rightId=${encodeURIComponent(rightId)}`);
  },
  getSimulationConfigurations(projectId?: string) {
    const suffix = projectId ? `?projectId=${encodeURIComponent(projectId)}` : "";
    return request<SimulationConfig[]>(`/workspace/simulations/configurations${suffix}`);
  },
  getSimulationHistory() {
    return request<JobRecord[]>("/workspace/simulations/history");
  },
  runSimulation(payload: SimulationRunRequest, csrfToken: string) {
    return request<JobRecord>("/workspace/simulations/runs", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  refreshCapabilities(csrfToken: string) {
    return request<CapabilitySummary>("/workspace/capabilities/refresh", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
    });
  },
  publish(payload: PublishRequest, csrfToken: string) {
    return request<JobRecord>("/workspace/publish", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  getDocuments() {
    return request<CollaboratorDocument[]>("/workspace/collaborator/documents");
  },
  getDocument(documentId: string) {
    return request<CollaboratorDocument>(`/workspace/collaborator/documents/${documentId}`);
  },
  updateDocument(documentId: string, bodyMarkdown: string, csrfToken: string) {
    return request<CollaboratorDocument>(`/workspace/collaborator/documents/${documentId}`, {
      method: "PUT",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify({ body_markdown: bodyMarkdown }),
    });
  },
  getAttachments(documentId: string) {
    return request<AttachmentInfo[]>(`/workspace/collaborator/documents/${documentId}/attachments`);
  },
  async uploadAttachment(documentId: string, file: File, csrfToken: string) {
    const formData = new FormData();
    formData.append("file", file);
    return request<AttachmentInfo>(`/workspace/collaborator/documents/${documentId}/attachments`, {
      method: "POST",
      headers: csrfToken ? { "X-CSRF-Token": csrfToken } : undefined,
      body: formData,
    });
  },
  deleteAttachment(documentId: string, attachmentId: string, csrfToken: string) {
    return request<{ ok: boolean }>(`/workspace/collaborator/documents/${documentId}/attachments/${attachmentId}`, {
      method: "DELETE",
      headers: jsonHeaders(csrfToken),
    });
  },
  getComments(documentId: string) {
    return request<CommentEntry[]>(`/workspace/collaborator/documents/${documentId}/comments`);
  },
  addComment(documentId: string, content: string, csrfToken: string) {
    return request<CommentEntry>(`/workspace/collaborator/documents/${documentId}/comments`, {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify({ content }),
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
  addBookmark(payload: Bookmark, csrfToken: string) {
    return request<Bookmark[]>("/workspace/bookmarks", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  deleteBookmark(bookmarkId: string, csrfToken: string) {
    return request<Bookmark[]>(`/workspace/bookmarks/${bookmarkId}`, {
      method: "DELETE",
      headers: jsonHeaders(csrfToken),
    });
  },
  saveSearch(payload: SavedSearch, csrfToken: string) {
    return request<SavedSearch[]>("/workspace/saved-searches", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  deleteSearch(searchId: string, csrfToken: string) {
    return request<SavedSearch[]>(`/workspace/saved-searches/${searchId}`, {
      method: "DELETE",
      headers: jsonHeaders(csrfToken),
    });
  },
  addRecent(payload: Bookmark, csrfToken: string) {
    return request<Bookmark[]>("/workspace/recent", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  exportData(payload: ExportRequest, csrfToken: string) {
    return request<JobRecord>("/workspace/exports", {
      method: "POST",
      headers: jsonHeaders(csrfToken),
      body: JSON.stringify(payload),
    });
  },
  listJobs() {
    return request<JobRecord[]>("/jobs");
  },
  getJob(jobId: string) {
    return request<JobRecord>(`/jobs/${jobId}`);
  },
  cancelJob(jobId: string, csrfToken: string) {
    return request<JobRecord>(`/jobs/${jobId}/cancel`, {
      method: "POST",
      headers: jsonHeaders(csrfToken),
    });
  },
};