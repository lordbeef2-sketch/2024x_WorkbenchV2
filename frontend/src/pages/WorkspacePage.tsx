import { type SyntheticEvent, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  AppBar,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  LinearProgress,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Toolbar,
  Tooltip,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/GridLegacy";
import CompareArrowsRoundedIcon from "@mui/icons-material/CompareArrowsRounded";
import LogoutRoundedIcon from "@mui/icons-material/LogoutRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import SaveRoundedIcon from "@mui/icons-material/SaveRounded";
import SettingsRoundedIcon from "@mui/icons-material/SettingsRounded";

import CapabilityBadges from "../components/CapabilityBadges";
import ProjectTree from "../components/ProjectTree";
import SettingsDialog from "../components/SettingsDialog";
import {
  ElementDiscoveryResult,
  ItemReference,
  ItemDetails,
  OSLCExecuteResponse,
  ProjectSummary,
  SessionPreferences,
  SwaggerContractManifest,
  SwaggerExecuteResponse,
  SwaggerOperationSpec,
  SwaggerParameterSpec,
  TreeNode,
} from "../models/api";
import { api } from "../services/api";
import { useSession } from "../state/SessionProvider";

type WorkspaceTab = "dashboard" | "projects" | "models" | "elements" | "details" | "compare" | "api";

function errorMessage(caught: unknown): string {
  return caught instanceof Error ? caught.message : "The request failed.";
}

function flattenTree(nodes: TreeNode[]): TreeNode[] {
  const flattened: TreeNode[] = [];
  const visit = (node: TreeNode) => {
    flattened.push(node);
    node.children.forEach(visit);
  };
  nodes.forEach(visit);
  return flattened;
}

function valueText(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function branchLabel(branches: ProjectSummary["branches"], branchId: string): string {
  if (!branchId) {
    return "Default branch context";
  }
  return branches.find((branch) => branch.id === branchId)?.name ?? "Selected branch";
}

function normalizeLookupKey(value: string): string {
  return value.trim().toLowerCase();
}

function isRevisionValue(value: string): boolean {
  return /^\d+$/.test(value.trim());
}

function isOpaqueIdentifier(value: string): boolean {
  const cleaned = value.trim();
  if (!cleaned) {
    return false;
  }
  return (
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(cleaned) ||
    /^[0-9a-f]{24,32}$/i.test(cleaned)
  );
}

function humanizeFieldLabel(value: string): string {
  return value
    .replace(/^kerml:/i, "")
    .replace(/^dcterms:/i, "")
    .replace(/^models:/i, "")
    .replace(/^esi\./i, "ESI ")
    .replace(/[_:.-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function projectSummaryText(project: ProjectSummary): string {
  return project.description || "Project available for model exploration.";
}

function compareDisplayValues(left: string, right: string): number {
  return left.localeCompare(right, undefined, { sensitivity: "base", numeric: true });
}

function resolvedNameForId(value: string, lookup: Record<string, string>): string | null {
  const normalized = normalizeLookupKey(value);
  const resolved = lookup[normalized]?.trim();
  if (!resolved) {
    return null;
  }
  return normalizeLookupKey(resolved) === normalized ? null : resolved;
}

function friendlyPath(path: string, lookup: Record<string, string>): string {
  const cleaned = path.trim();
  if (!cleaned) {
    return "";
  }
  return cleaned
    .split("/")
    .map((segment) => {
      const trimmed = segment.trim();
      return resolvedNameForId(trimmed, lookup) ?? (isOpaqueIdentifier(trimmed) ? "Unnamed item" : trimmed);
    })
    .join(" / ");
}

function humanReadableReference(value: string, lookup: Record<string, string>): string {
  const cleaned = value.trim();
  if (!cleaned) {
    return "";
  }
  const resolved = resolvedNameForId(cleaned, lookup);
  if (resolved) {
    return resolved;
  }
  if (isRevisionValue(cleaned)) {
    return `Revision ${cleaned}`;
  }
  const resolvedPath = cleaned.includes("/") ? friendlyPath(cleaned, lookup) : "";
  if (resolvedPath && resolvedPath !== cleaned) {
    return resolvedPath;
  }
  return isOpaqueIdentifier(cleaned) ? "Referenced item" : cleaned;
}

function displayEntityName(name: string, id: string, itemType: string, lookup: Record<string, string>): string {
  const cleanedName = name.trim();
  if (cleanedName && normalizeLookupKey(cleanedName) !== normalizeLookupKey(id)) {
    return cleanedName;
  }
  return resolvedNameForId(id, lookup) ?? `Unnamed ${humanizeFieldLabel(itemType || "item")}`;
}

function itemReferenceDisplayName(reference: ItemReference, lookup: Record<string, string>): string {
  return displayEntityName(reference.name, reference.id, reference.item_type, lookup);
}

function itemReferenceSecondaryText(reference: ItemReference, lookup: Record<string, string>): string {
  const path = friendlyPath(reference.path, lookup);
  if (path) {
    return path;
  }
  if (reference.relationship_type) {
    return humanizeFieldLabel(reference.relationship_type);
  }
  return humanizeFieldLabel(reference.item_type);
}

function humanizeFieldPath(path: string): string {
  return path
    .split(".")
    .map((segment) =>
      segment
        .replace(/\[(\d+)\]/g, " $1")
        .trim(),
    )
    .map((segment) => humanizeFieldLabel(segment || "Value"))
    .join(" / ");
}

function resolveDisplayValue(value: unknown, lookup: Record<string, string>): unknown {
  if (typeof value === "string") {
    return humanReadableReference(value, lookup);
  }
  if (Array.isArray(value)) {
    return value.map((item) => resolveDisplayValue(item, lookup));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, nestedValue]) => [key, resolveDisplayValue(nestedValue, lookup)]),
    );
  }
  return value;
}

function humanReadableValue(value: unknown, lookup: Record<string, string>): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return humanReadableReference(value, lookup);
  }
  const resolved = resolveDisplayValue(value, lookup);
  if (typeof resolved === "string") {
    return resolved;
  }
  return JSON.stringify(resolved, null, 2);
}

function defaultParameterValue(parameter: SwaggerParameterSpec): string {
  if (parameter.default === null || parameter.default === undefined) {
    return "";
  }
  return String(parameter.default);
}

function coerceParameterValue(parameter: SwaggerParameterSpec, value: string): unknown {
  if (value === "") {
    return "";
  }
  if (parameter.schema_type === "boolean") {
    return value === "true";
  }
  if (parameter.schema_type === "integer") {
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? value : parsed;
  }
  if (parameter.schema_type === "number") {
    const parsed = Number.parseFloat(value);
    return Number.isNaN(parsed) ? value : parsed;
  }
  if (parameter.schema_type === "array") {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return value;
}

function collectParameterValues(parameters: SwaggerParameterSpec[], values: Record<string, string>) {
  return parameters.reduce<Record<string, unknown>>((collected, parameter) => {
    const value = values[parameter.name] ?? "";
    if (value !== "") {
      collected[parameter.name] = coerceParameterValue(parameter, value);
    } else if (parameter.location === "path" && parameter.required) {
      collected[parameter.name] = "";
    }
    return collected;
  }, {});
}

function requestBodyTemplate(operation: SwaggerOperationSpec | null, manifest: SwaggerContractManifest | null): string {
  if (!operation?.request_body) {
    return "";
  }
  const contentType = operation.request_body.content_types[0] ?? "";
  if (contentType === "text/plain") {
    return "";
  }
  const schemaName = Object.values(operation.request_body.schema_refs).find(Boolean);
  if (!schemaName || !manifest) {
    return "{}";
  }
  const schema = manifest.schemas.find((candidate) => candidate.name === schemaName);
  if (!schema || !schema.properties.length) {
    return "{}";
  }
  const sample = schema.properties.reduce<Record<string, unknown>>((collected, property) => {
    if (!property.required && schema.required.length) {
      return collected;
    }
    if (property.schema_type === "boolean") {
      collected[property.name] = false;
    } else if (property.schema_type === "integer" || property.schema_type === "number") {
      collected[property.name] = 0;
    } else if (property.schema_type === "array") {
      collected[property.name] = [];
    } else if (property.schema_type === "object") {
      collected[property.name] = {};
    } else {
      collected[property.name] = "";
    }
    return collected;
  }, {});
  return JSON.stringify(sample, null, 2);
}

function responseContent(response: SwaggerExecuteResponse): string {
  if (response.body !== null && response.body !== undefined) {
    return JSON.stringify(response.body, null, 2);
  }
  if (response.text) {
    return response.text;
  }
  if (response.body_base64) {
    return `Binary response: ${response.size_bytes} bytes, ${response.content_type || "unknown content type"}.`;
  }
  return "No response body.";
}

function downloadSwaggerResponse(response: SwaggerExecuteResponse) {
  if (!response.body_base64) {
    return;
  }
  const binary = atob(response.body_base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const blob = new Blob([bytes], { type: response.content_type || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = response.filename ?? "twc-response.bin";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function downloadBinaryResponse(response: { body_base64?: string | null; content_type: string; filename?: string | null }) {
  if (!response.body_base64) {
    return;
  }
  const binary = atob(response.body_base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const blob = new Blob([bytes], { type: response.content_type || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = response.filename ?? "oslc-response.bin";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function oslcResponseContent(response: OSLCExecuteResponse): string {
  if (response.body !== null && response.body !== undefined) {
    return JSON.stringify(response.body, null, 2);
  }
  if (response.text) {
    return response.text;
  }
  if (response.body_base64) {
    return `Binary response: ${response.size_bytes} bytes, ${response.content_type || "unknown content type"}.`;
  }
  return "No response body.";
}

export default function WorkspacePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { session, refreshSession } = useSession();
  const csrfToken = session?.csrf_token ?? "";
  const capabilities = session?.capabilities?.capabilities ?? {};
  const canEdit = capabilities.edit?.state === "ready";
  const isAdmin = Boolean(session?.can_manage_server_presets);
  const cacheTimeMs = 1000 * 60 * 60 * 12;
  const sessionCacheKey = [session?.user?.preferred_username ?? "anonymous", session?.server?.id ?? "no-server"];

  const [tab, setTab] = useState<WorkspaceTab>("dashboard");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedBranchId, setSelectedBranchId] = useState("");
  const [treeFilter, setTreeFilter] = useState("");
  const [selectedItemId, setSelectedItemId] = useState("");
  const [itemDraft, setItemDraft] = useState<ItemDetails | null>(null);
  const [compareLeft, setCompareLeft] = useState("");
  const [compareRight, setCompareRight] = useState("");
  const [compareLeftDisplay, setCompareLeftDisplay] = useState("");
  const [compareRightDisplay, setCompareRightDisplay] = useState("");
  const [selectedApiTag, setSelectedApiTag] = useState("");
  const [selectedOperationKey, setSelectedOperationKey] = useState("");
  const [apiSearch, setApiSearch] = useState("");
  const [apiPathParams, setApiPathParams] = useState<Record<string, string>>({});
  const [apiQueryParams, setApiQueryParams] = useState<Record<string, string>>({});
  const [apiBodyText, setApiBodyText] = useState("");
  const [apiContentType, setApiContentType] = useState("");
  const [apiUploadFile, setApiUploadFile] = useState<File | null>(null);
  const [oslcPath, setOslcPath] = useState("/oslc/api/rootservices");
  const [oslcAccept, setOslcAccept] = useState("application/rdf+xml");
  const [oslcConsumerName, setOslcConsumerName] = useState("");
  const [oslcConsumerSecret, setOslcConsumerSecret] = useState("");
  const [oslcManualKey, setOslcManualKey] = useState("");
  const [oslcManualSecret, setOslcManualSecret] = useState("");
  const [revealedCacheIngestToken, setRevealedCacheIngestToken] = useState("");
  const [notice, setNotice] = useState<{ severity: "success" | "error"; message: string } | null>(null);
  const projectContextActive = tab === "models" || tab === "elements" || tab === "details" || tab === "compare";

  const projectsQuery = useQuery({
    queryKey: ["workspace-projects", ...sessionCacheKey],
    queryFn: () => api.getProjects(),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });

  const contractQuery = useQuery({
    queryKey: ["workspace-contract", ...sessionCacheKey],
    queryFn: api.getContractManifest,
    enabled: isAdmin,
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });

  const oslcStatusQuery = useQuery({
    queryKey: ["workspace-oslc-status", ...sessionCacheKey],
    queryFn: api.getOslcStatus,
    enabled: Boolean(session?.server?.id) && isAdmin,
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });

  const sharedOslcConsumerQuery = useQuery({
    queryKey: ["workspace-oslc-shared-consumer", ...sessionCacheKey],
    queryFn: api.getSharedOslcConsumer,
    enabled: Boolean(session?.server?.id) && isAdmin,
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });

  const cacheIngestTokenQuery = useQuery({
    queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey],
    queryFn: api.getCacheIngestTokenStatus,
    enabled: isAdmin,
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });

  const projects = useMemo(
    () =>
      [...(projectsQuery.data ?? [])].sort((left, right) => {
        const nameComparison = compareDisplayValues(left.name || left.id, right.name || right.id);
        if (nameComparison !== 0) {
          return nameComparison;
        }
        return compareDisplayValues(left.id, right.id);
      }),
    [projectsQuery.data],
  );
  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );
  const branchesQuery = useQuery({
    queryKey: ["workspace-branches", ...sessionCacheKey, selectedProjectId, selectedProject?.workspace_id],
    queryFn: () => api.getProjectBranches(selectedProjectId, selectedProject?.workspace_id || undefined),
    enabled: Boolean(selectedProjectId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const selectedProjectBranches = useMemo(
    () =>
      [...(branchesQuery.data ?? [])].sort((left, right) => {
        const nameComparison = compareDisplayValues(left.name || left.id, right.name || right.id);
        if (nameComparison !== 0) {
          return nameComparison;
        }
        return compareDisplayValues(left.id, right.id);
      }),
    [branchesQuery.data],
  );

  useEffect(() => {
    if (!selectedProjectId) {
      setSelectedBranchId("");
      return;
    }
    if (branchesQuery.isLoading) {
      return;
    }
    if (!selectedProjectBranches.length) {
      setSelectedBranchId("");
      return;
    }
    if (!selectedProjectBranches.some((branch) => branch.id === selectedBranchId)) {
      setSelectedBranchId(selectedProjectBranches[0].id);
    }
  }, [branchesQuery.isLoading, selectedBranchId, selectedProjectBranches, selectedProjectId]);

  const treeQuery = useQuery({
    queryKey: ["workspace-tree", ...sessionCacheKey, selectedProjectId, selectedBranchId],
    queryFn: () => api.getTree(selectedProjectId || undefined, selectedBranchId || undefined, selectedProject?.workspace_id || undefined),
    enabled:
      projectContextActive &&
      Boolean(selectedProjectId) &&
      !branchesQuery.isLoading &&
      (!selectedProjectBranches.length || Boolean(selectedBranchId)),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });

  const treeNodes = treeQuery.data ?? [];
  const flatNodes = useMemo(() => flattenTree(treeNodes), [treeNodes]);
  const elementDiscoveryQuery = useQuery({
    queryKey: ["workspace-elements", ...sessionCacheKey, selectedProjectId, selectedBranchId, selectedProject?.workspace_id],
    queryFn: () => api.getElementDiscovery(selectedProjectId, selectedBranchId, selectedProject?.workspace_id || undefined),
    enabled: tab === "elements" && Boolean(selectedProjectId) && Boolean(selectedBranchId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const elementDiscovery: ElementDiscoveryResult | null = elementDiscoveryQuery.data ?? null;
  const contractManifest = contractQuery.data ?? null;
  const apiTags = useMemo(
    () => Object.keys(contractManifest?.tag_counts ?? {}).sort((left, right) => left.localeCompare(right)),
    [contractManifest],
  );
  const apiOperations = useMemo(() => contractManifest?.operations ?? [], [contractManifest]);
  const filteredApiOperations = useMemo(() => {
    const search = apiSearch.trim().toLowerCase();
    return apiOperations
      .filter((operation) => operation.tag === selectedApiTag)
      .filter((operation) => {
        if (!search) {
          return true;
        }
        return `${operation.method} ${operation.path} ${operation.summary} ${operation.description}`.toLowerCase().includes(search);
      });
  }, [apiOperations, apiSearch, selectedApiTag]);
  const selectedOperation = useMemo(
    () => apiOperations.find((operation) => operation.key === selectedOperationKey) ?? filteredApiOperations[0] ?? null,
    [apiOperations, filteredApiOperations, selectedOperationKey],
  );
  const apiOperationStats = useMemo(
    () =>
      Object.entries(contractManifest?.operation_counts ?? {})
        .map(([method, count]) => `${method} ${count}`)
        .join(" / "),
    [contractManifest],
  );

  const oslcStatus = oslcStatusQuery.data ?? null;
  const sharedOslcConsumer = sharedOslcConsumerQuery.data ?? null;
  const cacheIngestTokenStatus = cacheIngestTokenQuery.data ?? null;

  useEffect(() => {
    if (oslcConsumerName) {
      return;
    }
    const serverId = session?.server?.id ?? "server";
    setOslcConsumerName(`twcworkbench-${serverId}`);
  }, [oslcConsumerName, session?.server?.id]);

  useEffect(() => {
    if (sharedOslcConsumer?.consumer_key && !oslcManualKey) {
      setOslcManualKey(sharedOslcConsumer.consumer_key);
    }
  }, [oslcManualKey, sharedOslcConsumer?.consumer_key]);

  const contextParameterValue = (parameter: SwaggerParameterSpec): string => {
    const normalized = parameter.name.toLowerCase();
    if (normalized === "workspaceid") {
      return selectedProject?.workspace_id ?? "";
    }
    if (normalized === "resourceid") {
      return selectedProject?.resource_id ?? selectedProjectId;
    }
    if (normalized === "branchid") {
      return selectedBranchId;
    }
    if (normalized === "elementid" || normalized === "modelid") {
      return selectedItemId;
    }
    if (normalized === "source") {
      return compareLeft;
    }
    if (normalized === "target") {
      return compareRight;
    }
    return defaultParameterValue(parameter);
  };

  useEffect(() => {
    if (!selectedApiTag && apiTags.length) {
      setSelectedApiTag(apiTags[0]);
    }
  }, [apiTags, selectedApiTag]);

  useEffect(() => {
    if (!filteredApiOperations.length) {
      setSelectedOperationKey("");
      return;
    }
    if (!filteredApiOperations.some((operation) => operation.key === selectedOperationKey)) {
      setSelectedOperationKey(filteredApiOperations[0].key);
    }
  }, [filteredApiOperations, selectedOperationKey]);

  useEffect(() => {
    if (!selectedOperation) {
      return;
    }
    setApiPathParams(
      selectedOperation.path_parameters.reduce<Record<string, string>>((values, parameter) => {
        values[parameter.name] = contextParameterValue(parameter);
        return values;
      }, {}),
    );
    setApiQueryParams(
      selectedOperation.query_parameters.reduce<Record<string, string>>((values, parameter) => {
        values[parameter.name] = defaultParameterValue(parameter);
        return values;
      }, {}),
    );
    setApiContentType(selectedOperation.request_body?.content_types[0] ?? "");
    setApiBodyText(requestBodyTemplate(selectedOperation, contractManifest));
    setApiUploadFile(null);
  }, [
    selectedOperation,
    contractManifest,
    selectedProject?.workspace_id,
    selectedProject?.resource_id,
    selectedProjectId,
    selectedBranchId,
    selectedItemId,
    compareLeft,
    compareRight,
  ]);

  useEffect(() => {
    const connected = searchParams.get("oslcAuth");
    const authError = searchParams.get("oslcAuthError");
    if (!connected && !authError) {
      return;
    }

    if (connected === "connected") {
      setNotice({ severity: "success", message: "OSLC connection is ready for this Teamwork Cloud server." });
      void queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status", ...sessionCacheKey] });
    } else if (authError) {
      setNotice({ severity: "error", message: authError });
    }

    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("oslcAuth");
    nextParams.delete("oslcAuthError");
    setSearchParams(nextParams, { replace: true });
  }, [queryClient, searchParams, setSearchParams]);

  useEffect(() => {
    if (!isAdmin && tab === "api") {
      setTab("dashboard");
    }
  }, [isAdmin, tab]);

  const itemQuery = useQuery({
    queryKey: ["workspace-item", ...sessionCacheKey, selectedItemId, selectedProjectId, selectedBranchId],
    queryFn: () =>
      api.getItem(
        selectedItemId,
        selectedProjectId || undefined,
        selectedBranchId || undefined,
        selectedProject?.workspace_id || undefined,
      ),
    enabled: Boolean(selectedItemId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    setItemDraft(itemQuery.data ?? null);
  }, [itemQuery.data]);

  const selectedWorkspaceItem = itemQuery.data ?? itemDraft ?? null;
  const referenceNameById = useMemo(() => {
    const lookup: Record<string, string> = {};
    projects.forEach((project) => {
      if (project.name) {
        lookup[normalizeLookupKey(project.id)] = project.name;
      }
      if (project.resource_id) {
        lookup[normalizeLookupKey(project.resource_id)] = project.name;
      }
    });
    selectedProjectBranches.forEach((branch) => {
      if (branch.name) {
        lookup[normalizeLookupKey(branch.id)] = branch.name;
      }
    });
    flatNodes.forEach((node) => {
      if (node.label) {
        lookup[normalizeLookupKey(node.id)] = node.label;
      }
    });
    elementDiscovery?.entries.forEach((entry) => {
      if (entry.name) {
        lookup[normalizeLookupKey(entry.id)] = entry.name;
      }
    });
    if (selectedWorkspaceItem?.name) {
      lookup[normalizeLookupKey(selectedWorkspaceItem.id)] = selectedWorkspaceItem.name;
    }
    if (selectedWorkspaceItem?.owner?.name) {
      lookup[normalizeLookupKey(selectedWorkspaceItem.owner.id)] = selectedWorkspaceItem.owner.name;
    }
    selectedWorkspaceItem?.type_references.forEach((reference) => {
      if (reference.name) {
        lookup[normalizeLookupKey(reference.id)] = reference.name;
      }
    });
    selectedWorkspaceItem?.contained_elements.forEach((reference) => {
      if (reference.name) {
        lookup[normalizeLookupKey(reference.id)] = reference.name;
      }
    });
    selectedWorkspaceItem?.related_items.forEach((reference) => {
      if (reference.name) {
        lookup[normalizeLookupKey(reference.id)] = reference.name;
      }
    });
    return lookup;
  }, [elementDiscovery?.entries, flatNodes, projects, selectedProjectBranches, selectedWorkspaceItem]);

  const selectedWorkspaceItemName = selectedWorkspaceItem
    ? displayEntityName(selectedWorkspaceItem.name, selectedWorkspaceItem.id, selectedWorkspaceItem.item_type, referenceNameById)
    : "";
  const selectedWorkspaceItemPath = selectedWorkspaceItem ? friendlyPath(selectedWorkspaceItem.path, referenceNameById) : "";
  const compareLeftName = compareLeft.trim() ? humanReadableReference(compareLeft, referenceNameById) : "";
  const compareRightName = compareRight.trim() ? humanReadableReference(compareRight, referenceNameById) : "";
  const compareLeftFieldValue = compareLeftDisplay || compareLeft;
  const compareRightFieldValue = compareRightDisplay || compareRight;
  const compareLeftLabel = compareLeft.trim()
    ? compareLeftName !== compareLeft || isRevisionValue(compareLeft)
      ? compareLeftName
      : "Selected item reference"
    : "";
  const compareRightLabel = compareRight.trim()
    ? compareRightName !== compareRight || isRevisionValue(compareRight)
      ? compareRightName
      : "Selected item reference"
    : "";

  const logoutMutation = useMutation({
    mutationFn: () => api.logout(csrfToken),
    onSuccess: async () => {
      await refreshSession();
      navigate("/", { replace: true });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const capabilityMutation = useMutation({
    mutationFn: () => api.refreshCapabilities(csrfToken),
    onSuccess: async () => {
      await refreshSession();
      setNotice({ severity: "success", message: "Capabilities refreshed from Teamwork Cloud." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const settingsMutation = useMutation({
    mutationFn: (preferences: SessionPreferences) => api.updatePreferences(preferences, csrfToken),
    onSuccess: async () => {
      await refreshSession();
      setNotice({ severity: "success", message: "Workspace settings saved." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const refreshProjectsMutation = useMutation({
    mutationFn: () => api.getProjects(true),
    onSuccess: (projects) => {
      queryClient.setQueryData(["workspace-projects", ...sessionCacheKey], projects);
      setNotice({ severity: "success", message: "Project catalog refreshed." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const refreshSelectedProjectMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProjectId) {
        throw new Error("Select a project before refreshing.");
      }
      const branches = await api.getProjectBranches(selectedProjectId, selectedProject?.workspace_id || undefined, true);
      let tree: TreeNode[] | null = null;
      const currentBranchId = selectedBranchId || branches[0]?.id;
      if (currentBranchId) {
        tree = await api.getTree(selectedProjectId, currentBranchId, selectedProject?.workspace_id || undefined, true);
      }
      return { branches, tree, branchId: currentBranchId ?? "" };
    },
    onSuccess: ({ branches, tree, branchId }) => {
      queryClient.setQueryData(["workspace-branches", ...sessionCacheKey, selectedProjectId, selectedProject?.workspace_id], branches);
      if (branchId) {
        queryClient.setQueryData(["workspace-tree", ...sessionCacheKey, selectedProjectId, branchId], tree ?? []);
        setSelectedBranchId(branchId);
      }
      setNotice({ severity: "success", message: "Selected project data refreshed." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const refreshItemMutation = useMutation({
    mutationFn: () => {
      if (!selectedItemId) {
        throw new Error("Select an item before refreshing.");
      }
      return api.getItem(
        selectedItemId,
        selectedProjectId || undefined,
        selectedBranchId || undefined,
        selectedProject?.workspace_id || undefined,
        true,
      );
    },
    onSuccess: (item) => {
      queryClient.setQueryData(["workspace-item", ...sessionCacheKey, selectedItemId, selectedProjectId, selectedBranchId], item);
      setItemDraft(item);
      setNotice({ severity: "success", message: "Model item refreshed." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const refreshElementDiscoveryMutation = useMutation({
    mutationFn: () => {
      if (!selectedProjectId || !selectedBranchId) {
        throw new Error("Select a project branch before refreshing elements.");
      }
      return api.getElementDiscovery(selectedProjectId, selectedBranchId, selectedProject?.workspace_id || undefined, true);
    },
    onSuccess: (result) => {
      queryClient.setQueryData(
        ["workspace-elements", ...sessionCacheKey, selectedProjectId, selectedBranchId, selectedProject?.workspace_id],
        result,
      );
      setNotice({ severity: "success", message: "Element discovery refreshed for the selected branch." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const saveItemMutation = useMutation({
    mutationFn: () => {
      if (!selectedItemId || !itemDraft) {
        throw new Error("Select an item before saving.");
      }
      return api.updateItem(
        selectedItemId,
        {
          name: itemDraft.name,
          description: itemDraft.description,
        },
        csrfToken,
        selectedProjectId || undefined,
        selectedBranchId || undefined,
      );
    },
    onSuccess: async (savedItem) => {
      setItemDraft(savedItem);
      await queryClient.invalidateQueries({ queryKey: ["workspace-item", ...sessionCacheKey] });
      await queryClient.invalidateQueries({ queryKey: ["workspace-tree", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "Item saved to Teamwork Cloud." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const compareMutation = useMutation({
    mutationFn: () =>
      api.compare(
        compareLeft.trim(),
        compareRight.trim(),
        selectedProjectId || undefined,
        selectedBranchId || undefined,
        selectedProjectId || undefined,
        selectedBranchId || undefined,
      ),
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const apiOperationMutation = useMutation({
    mutationFn: () => {
      if (!selectedOperation) {
        throw new Error("Select a Swagger operation first.");
      }
      const pathParams = collectParameterValues(selectedOperation.path_parameters, apiPathParams);
      const queryParams = collectParameterValues(selectedOperation.query_parameters, apiQueryParams);
      if (selectedOperation.supports_file_upload) {
        if (!apiUploadFile) {
          throw new Error("Select a file before running this upload operation.");
        }
        return api.executeContractUpload(selectedOperation.key, pathParams, queryParams, apiUploadFile, csrfToken);
      }
      let body: unknown = undefined;
      const bodyText = apiBodyText.trim();
      if (selectedOperation.request_body && bodyText) {
        body = apiContentType === "text/plain" ? apiBodyText : JSON.parse(bodyText);
      }
      return api.executeContractOperation(
        {
          operation_key: selectedOperation.key,
          path_params: pathParams,
          query_params: queryParams,
          body,
          content_type: selectedOperation.request_body ? apiContentType || selectedOperation.request_body.content_types[0] : null,
          timeout_seconds: 30,
        },
        csrfToken,
      );
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const oslcRequestMutation = useMutation({
    mutationFn: () =>
      api.executeOslcRequest(
        {
          path_or_url: oslcPath.trim(),
          accept: oslcAccept || null,
          timeout_seconds: 30,
        },
        csrfToken,
      ),
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const rotateCacheIngestTokenMutation = useMutation({
    mutationFn: () => api.rotateCacheIngestToken(csrfToken),
    onSuccess: async (result) => {
      setRevealedCacheIngestToken(result.token);
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "A new plugin ingest token was generated and stored inside Workbench." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const clearCacheIngestTokenMutation = useMutation({
    mutationFn: () => api.clearCacheIngestToken(csrfToken),
    onSuccess: async () => {
      setRevealedCacheIngestToken("");
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "The app-managed plugin ingest token was cleared." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const disconnectOslcMutation = useMutation({
    mutationFn: () => api.disconnectOslc(csrfToken),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "OSLC connection was cleared for this app session." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const generateOslcConsumerMutation = useMutation({
    mutationFn: () =>
      api.generateOslcConsumer(
        {
          name: oslcConsumerName.trim(),
          secret: oslcConsumerSecret,
          remember_for_session: false,
        },
        csrfToken,
      ),
    onSuccess: async (result) => {
      setOslcManualKey(result.consumer_key);
      setOslcManualSecret(oslcConsumerSecret);
      setNotice({ severity: "success", message: `${result.message} Save the generated key as the shared consumer when you're ready.` });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const storeOslcConsumerMutation = useMutation({
    mutationFn: () =>
      api.updateSharedOslcConsumer(
        {
          consumer_key: oslcManualKey.trim(),
          consumer_secret: oslcManualSecret,
        },
        csrfToken,
      ),
    onSuccess: async () => {
      setOslcConsumerSecret("");
      setOslcManualSecret("");
      await queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status", ...sessionCacheKey] });
      await queryClient.invalidateQueries({ queryKey: ["workspace-oslc-shared-consumer", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "Shared OSLC consumer credentials were saved for this Teamwork Cloud server." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const clearOslcConsumerMutation = useMutation({
    mutationFn: () => api.clearSharedOslcConsumer(csrfToken),
    onSuccess: async () => {
      setOslcManualKey("");
      setOslcManualSecret("");
      await queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status", ...sessionCacheKey] });
      await queryClient.invalidateQueries({ queryKey: ["workspace-oslc-shared-consumer", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "Shared OSLC consumer credentials were cleared for this server." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const handleTabChange = (_event: SyntheticEvent, nextTab: WorkspaceTab) => {
    setTab(nextTab);
  };

  const selectProject = (projectId: string) => {
    setSelectedProjectId(projectId);
    setSelectedBranchId("");
    setSelectedItemId("");
    setItemDraft(null);
  };

  const openProjectInModelBrowser = (projectId: string) => {
    selectProject(projectId);
    setTab("models");
  };

  const openNode = (node: TreeNode) => {
    setSelectedItemId(node.id);
    setTab("details");
  };

  const openElementId = (itemId: string) => {
    setSelectedItemId(itemId);
    setTab("details");
  };

  const pickCompareSide = (side: "left" | "right", itemId: string) => {
    const readableLabel = humanReadableReference(itemId, referenceNameById);
    if (side === "left") {
      setCompareLeft(itemId);
      setCompareLeftDisplay(readableLabel);
    } else {
      setCompareRight(itemId);
      setCompareRightDisplay(readableLabel);
    }
    setTab("compare");
  };

  const renderParameterControls = (
    title: string,
    parameters: SwaggerParameterSpec[],
    values: Record<string, string>,
    onChange: (name: string, value: string) => void,
  ) => (
    <Stack spacing={1}>
      <Typography variant="subtitle2">{title}</Typography>
      {parameters.length ? (
        <Grid container spacing={1.5}>
          {parameters.map((parameter) => {
            const options = parameter.enum.length
              ? ["", ...parameter.enum.map((option) => String(option))]
              : parameter.schema_type === "boolean"
                ? ["", "true", "false"]
                : null;
            return (
              <Grid item xs={12} md={6} key={`${title}-${parameter.name}`}>
                <TextField
                  label={`${parameter.name}${parameter.required ? " *" : ""}`}
                  value={values[parameter.name] ?? ""}
                  onChange={(event) => onChange(parameter.name, event.target.value)}
                  helperText={parameter.description || parameter.schema_type}
                  fullWidth
                  select={Boolean(options)}
                >
                  {options?.map((option) => (
                    <MenuItem key={option || "blank"} value={option}>
                      {option || "Unset"}
                    </MenuItem>
                  ))}
                </TextField>
              </Grid>
            );
          })}
        </Grid>
      ) : (
        <Typography variant="body2" color="text.secondary">
          No {title.toLowerCase()} declared.
        </Typography>
      )}
    </Stack>
  );

  const renderDashboard = () => (
    <Stack spacing={2}>
      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: "100%", borderRadius: 2 }}>
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                Repository
              </Typography>
              <Typography variant="h3">{projects.length}</Typography>
              <Typography color="text.secondary">RealSwagger resource entries available to this TWC user.</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: "100%", borderRadius: 2 }}>
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                Active Project Branches
              </Typography>
              <Typography variant="h3">{selectedProjectId ? selectedProjectBranches.length : 0}</Typography>
              <Typography color="text.secondary">Loaded only for the currently selected project.</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: "100%", borderRadius: 2 }}>
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                Model Items
              </Typography>
              <Typography variant="h3">{flatNodes.length}</Typography>
              <Typography color="text.secondary">Loaded for the selected project and branch.</Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Typography variant="h5">Swagger Contract Boundary</Typography>
          <Typography color="text.secondary">
            This workspace exposes only Teamwork Cloud operations present in RealSwagger.json. The curated tabs cover the common repository and model flows{isAdmin ? "; API Explorer exposes the complete contract surface for advanced workflows." : "."}
          </Typography>
          <Typography color="text.secondary">
            Simulation, collaborator workspaces, global model search, publishing, export jobs, job center, saved searches, bookmarks, comments, documents, and collaborator-style attachments are not shown because this Swagger file does not define those APIs.{isAdmin ? " Swagger artifact upload and download operations are available in API Explorer." : ""}
          </Typography>
          {contractManifest ? (
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Chip label={`${contractManifest.operations.length} operations`} />
              <Chip label={`${Object.keys(contractManifest.tag_counts).length} tags`} variant="outlined" />
              <Chip label={apiOperationStats || "No operation counts"} variant="outlined" />
              <Chip label={`${contractManifest.schemas.length} schemas`} variant="outlined" />
            </Stack>
          ) : null}
          {contractManifest?.warnings.map((warning) => (
            <Alert severity="warning" key={warning}>
              {warning}
            </Alert>
          ))}
          {session?.capabilities ? <CapabilityBadges capabilities={Object.values(session.capabilities.capabilities)} /> : null}
        </Stack>
      </Paper>
    </Stack>
  );

  const renderProjects = () => (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
        <Box>
          <Typography variant="h5">Project Browser</Typography>
          <Typography variant="body2" color="text.secondary">
            Pick a project here. Branch and model context load after selection in Model Browser.
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={<RefreshRoundedIcon />}
          onClick={() => refreshProjectsMutation.mutate()}
          disabled={refreshProjectsMutation.isPending}
        >
          Refresh Catalog
        </Button>
      </Stack>
      {projectsQuery.isLoading ? <CircularProgress size={28} /> : null}
      <Grid container spacing={2}>
        {projects.map((project) => (
          <Grid item xs={12} md={6} key={project.id}>
            <Card variant={selectedProjectId === project.id ? "elevation" : "outlined"} sx={{ height: "100%", borderRadius: 2 }}>
              <CardContent>
                <Stack spacing={2}>
                  <Stack spacing={0.5}>
                    <Typography variant="h6">{project.name}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {projectSummaryText(project)}
                    </Typography>
                  </Stack>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label="Repository Resource" variant="outlined" />
                    {project.workspace_id ? <Chip label="Workspace-scoped" variant="outlined" /> : null}
                    <Chip label="Select to load branches and models" variant="outlined" />
                    {selectedProjectId === project.id ? <Chip label="Selected project" color="primary" /> : null}
                  </Stack>
                  <Button variant="contained" onClick={() => openProjectInModelBrowser(project.id)}>
                    Open in Model Browser
                  </Button>
                </Stack>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Stack>
  );

  const renderModels = () => (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
        <Box>
          <Typography variant="h5">Model Browser</Typography>
          <Typography variant="body2" color="text.secondary">
            {selectedProject ? `${selectedProject.name} / ${branchLabel(selectedProjectBranches, selectedBranchId)}` : "Select a project to load models."}
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={<RefreshRoundedIcon />}
          onClick={() => refreshSelectedProjectMutation.mutate()}
          disabled={!selectedProjectId || refreshSelectedProjectMutation.isPending}
        >
          Refresh Selected Project
        </Button>
      </Stack>
      {selectedProject ? (
        <Paper sx={{ p: 3, borderRadius: 2 }}>
          <Stack spacing={1.5}>
            <Typography variant="h6">{selectedProject.name}</Typography>
            <Typography variant="body2" color="text.secondary">
              {selectedProject.description || "Use the branch selector in the left panel to change the current model context."}
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Chip label="Repository Resource" variant="outlined" />
              {selectedProject.workspace_id ? <Chip label="Workspace-scoped" variant="outlined" /> : null}
              <Chip
                label={
                  branchesQuery.isLoading
                    ? "Loading branches"
                    : selectedBranchId
                      ? `Branch ${branchLabel(selectedProjectBranches, selectedBranchId)}`
                      : "Default branch context"
                }
                color="primary"
              />
            </Stack>
          </Stack>
        </Paper>
      ) : null}
      {branchesQuery.isLoading && selectedProjectId ? <CircularProgress size={28} /> : null}
      {branchesQuery.error ? <Alert severity="error">{errorMessage(branchesQuery.error)}</Alert> : null}
      {treeQuery.isLoading ? <CircularProgress size={28} /> : null}
      {treeQuery.error ? <Alert severity="error">{errorMessage(treeQuery.error)}</Alert> : null}
      <Grid container spacing={2}>
        {flatNodes.map((node) => (
          <Grid item xs={12} md={6} lg={4} key={node.id}>
            <Card sx={{ height: "100%", borderRadius: 2 }}>
              <CardContent>
                <Stack spacing={1.5}>
                  <Box>
                    <Typography variant="h6">{node.label}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {selectedProject ? `${selectedProject.name} / ${branchLabel(selectedProjectBranches, selectedBranchId)}` : node.node_type}
                    </Typography>
                    {node.path ? (
                      <Typography variant="caption" color="text.secondary">
                        {friendlyPath(node.path, referenceNameById)}
                      </Typography>
                    ) : null}
                  </Box>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label={humanizeFieldLabel(node.node_type)} size="small" />
                    {selectedProject ? <Chip label={`Project: ${selectedProject.name}`} size="small" variant="outlined" /> : null}
                    {selectedBranchId ? <Chip label={`Branch: ${branchLabel(selectedProjectBranches, selectedBranchId)}`} size="small" variant="outlined" /> : null}
                  </Stack>
                  <Stack direction="row" spacing={1}>
                    <Button size="small" variant="contained" onClick={() => openNode(node)}>
                      Details
                    </Button>
                    <Button size="small" onClick={() => pickCompareSide("left", node.id)}>
                      Compare Left
                    </Button>
                    <Button size="small" onClick={() => pickCompareSide("right", node.id)}>
                      Compare Right
                    </Button>
                  </Stack>
                </Stack>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
      {!treeQuery.isLoading && !flatNodes.length ? (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography color="text.secondary">No model entries were returned for the selected project and branch.</Typography>
        </Paper>
      ) : null}
    </Stack>
  );

  const renderElementTesting = () => {
    const elementDiscoveryLoading = elementDiscoveryQuery.isLoading || refreshElementDiscoveryMutation.isPending;
    const elementDiscoveryLoadingMessage = elementDiscovery
      ? "Refreshing the branch cache and applying changed elements only."
      : "Building the branch element cache for the first load.";

    if (!selectedProjectId) {
      return (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a project</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Element discovery runs against the currently selected project and branch.
          </Typography>
        </Paper>
      );
    }

    if (!selectedBranchId) {
      return (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a branch</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            This tab walks the real TWC element graph for one branch at a time.
          </Typography>
        </Paper>
      );
    }

    return (
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
          <Box>
            <Typography variant="h5">Element Testing</Typography>
            <Typography variant="body2" color="text.secondary">
              Discover reachable elements for {selectedProject?.name ?? "the selected project"} / {branchLabel(selectedProjectBranches, selectedBranchId)} by traversing Swagger-backed model roots and recursively following <code>ldp:contains</code>.
            </Typography>
          </Box>
          <Button
            variant="outlined"
            startIcon={<RefreshRoundedIcon />}
            onClick={() => refreshElementDiscoveryMutation.mutate()}
            disabled={!selectedProjectId || !selectedBranchId || refreshElementDiscoveryMutation.isPending}
          >
            Refresh Elements
          </Button>
        </Stack>
        {elementDiscoveryLoading ? (
          <Paper sx={{ p: 2.5, borderRadius: 2 }}>
            <Stack spacing={1.25}>
              <Stack direction="row" spacing={1.5} alignItems="center">
                <CircularProgress size={20} />
                <Box>
                  <Typography variant="subtitle2">Loading element cache</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {elementDiscoveryLoadingMessage}
                  </Typography>
                </Box>
              </Stack>
              <LinearProgress />
            </Stack>
          </Paper>
        ) : null}
        {elementDiscoveryQuery.error ? <Alert severity="error">{errorMessage(elementDiscoveryQuery.error)}</Alert> : null}
        {elementDiscovery ? (
          <>
            <Paper sx={{ p: 3, borderRadius: 2 }}>
              <Stack spacing={2}>
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                  <Chip label={`${elementDiscovery.total_ids} elements`} color="primary" />
                  <Chip label={`${elementDiscovery.traversed_elements} traversed`} variant="outlined" />
                  <Chip label={`${elementDiscovery.hydrated_elements} payloads cached`} variant="outlined" />
                  <Chip label={`${elementDiscovery.batch_count} gap-fill batches`} variant="outlined" />
                  <Chip label={elementDiscovery.seed_source || "model-roots"} variant="outlined" />
                  {elementDiscovery.cache_status ? <Chip label={humanizeFieldLabel(elementDiscovery.cache_status)} variant="outlined" /> : null}
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  This run stays inside the Swagger contract: seed roots come from the selected branch models, each discovered element is fetched through the branch element endpoint, and the branch-level element POST is now reserved for smaller gap-fill batches of up to {elementDiscovery.batch_size} elements when traversal payloads are missing.
                </Typography>
                {elementDiscovery.warnings.map((warning) => (
                  <Alert severity="warning" key={warning}>
                    {warning}
                  </Alert>
                ))}
              </Stack>
            </Paper>
            <Paper sx={{ p: 3, borderRadius: 2 }}>
              <Stack spacing={2}>
                <Typography variant="h6">Discovered Elements</Typography>
                {elementDiscovery.entries.length ? (
                  <List dense disablePadding sx={{ maxHeight: 640, overflow: "auto" }}>
                    {elementDiscovery.entries.map((entry) => (
                      <ListItemButton key={entry.id} alignItems="flex-start" onClick={() => openElementId(entry.id)}>
                        <ListItemText
                          primary={displayEntityName(entry.name, entry.id, entry.item_type, referenceNameById)}
                          secondary={
                            <Box component="span" sx={{ display: "block", mt: 0.75 }}>
                              <Typography component="span" variant="body2" sx={{ display: "block" }}>
                                {humanizeFieldLabel(entry.item_type)} · {entry.child_count} contained elements
                              </Typography>
                            </Box>
                          }
                        />
                      </ListItemButton>
                    ))}
                  </List>
                ) : (
                  <Typography color="text.secondary">No elements were discovered for this branch.</Typography>
                )}
              </Stack>
            </Paper>
          </>
        ) : null}
      </Stack>
    );
  };

  const renderDetails = () => {
    const selectedItem = itemQuery.data ?? null;
    const editable = Boolean(selectedItem?.editable && canEdit);

    if (!selectedItemId) {
      return (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a model item</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Use the model tree or Model Browser to open details from the Swagger-backed element/model endpoints.
          </Typography>
        </Paper>
      );
    }

    if (itemQuery.isLoading || !itemDraft) {
      return <CircularProgress size={28} />;
    }

    return (
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
            <Box>
              <Typography variant="h5">Model Viewer / Editor</Typography>
              <Typography variant="body2" color="text.secondary">
                {displayEntityName(itemDraft.name, selectedItemId, itemDraft.item_type, referenceNameById)}
              </Typography>
              {itemDraft.path ? (
                <Typography variant="caption" color="text.secondary">
                  {friendlyPath(itemDraft.path, referenceNameById)}
                </Typography>
              ) : null}
            </Box>
            <Stack direction="row" spacing={1}>
              <Button startIcon={<RefreshRoundedIcon />} onClick={() => refreshItemMutation.mutate()} disabled={refreshItemMutation.isPending}>
                Refresh
            </Button>
            <Button startIcon={<CompareArrowsRoundedIcon />} onClick={() => pickCompareSide("left", selectedItemId)}>
              Compare Left
            </Button>
            <Button startIcon={<CompareArrowsRoundedIcon />} onClick={() => pickCompareSide("right", selectedItemId)}>
              Compare Right
            </Button>
            <Button
              variant="contained"
              startIcon={<SaveRoundedIcon />}
              disabled={!editable || saveItemMutation.isPending}
              onClick={() => saveItemMutation.mutate()}
            >
              Save
            </Button>
          </Stack>
        </Stack>
        {!editable ? (
          <Alert severity="info">
            Editing is disabled for this item unless TWC marks it editable and the RealSwagger element update capability is available to the current session.
          </Alert>
        ) : null}
        <Grid container spacing={2}>
          <Grid item xs={12} md={7}>
            <Paper sx={{ p: 3, borderRadius: 2 }}>
              <Stack spacing={2}>
                <TextField
                  label="Path"
                  value={friendlyPath(itemDraft.path, referenceNameById)}
                  disabled
                  fullWidth
                />
                <TextField
                  label="Name"
                  value={itemDraft.name}
                  disabled={!editable}
                  onChange={(event) => setItemDraft((current) => (current ? { ...current, name: event.target.value } : current))}
                  fullWidth
                />
                <TextField
                  label="Description"
                  value={itemDraft.description}
                  disabled={!editable}
                  onChange={(event) => setItemDraft((current) => (current ? { ...current, description: event.target.value } : current))}
                  fullWidth
                  multiline
                  minRows={3}
                />
                <TextField
                  label="Documentation"
                  value={itemDraft.documentation_markdown}
                  disabled
                  helperText="Generated from the RealSwagger element/model payload."
                  fullWidth
                  multiline
                  minRows={8}
                />
                <TextField
                  label="Source Payload"
                  value={humanReadableValue(itemDraft.source_payload ?? {}, referenceNameById)}
                  disabled
                  helperText="Read-only viewer for the cached Teamwork Cloud payload behind this model item."
                  fullWidth
                  multiline
                  minRows={12}
                />
              </Stack>
            </Paper>
          </Grid>
          <Grid item xs={12} md={5}>
            <Paper sx={{ p: 3, borderRadius: 2 }}>
              <Stack spacing={2}>
                <Typography variant="h6">Element Overview</Typography>
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                  <Chip label={humanizeFieldLabel(itemDraft.item_type)} />
                  <Chip label={`Version ${itemDraft.version}`} variant="outlined" />
                  {selectedProject ? <Chip label={`Project ${selectedProject.name}`} variant="outlined" /> : null}
                  <Chip label={`Branch ${branchLabel(selectedProjectBranches, selectedBranchId)}`} variant="outlined" />
                  {itemDraft.raw_types.map((rawType) => (
                    <Chip key={rawType} label={humanizeFieldLabel(rawType)} size="small" variant="outlined" />
                  ))}
                </Stack>
                {itemDraft.stereotypes.length ? (
                  <Stack spacing={1}>
                    <Typography variant="subtitle2">Applied Stereotypes</Typography>
                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                      {itemDraft.stereotypes.map((stereotype) => (
                        <Chip key={stereotype} label={stereotype} size="small" />
                      ))}
                    </Stack>
                  </Stack>
                ) : null}
                {itemDraft.owner ? (
                  <Stack spacing={1}>
                    <Typography variant="subtitle2">Owner</Typography>
                    <List dense disablePadding>
                      <ListItemButton dense onClick={() => openElementId(itemDraft.owner!.id)}>
                        <ListItemText
                          primary={itemReferenceDisplayName(itemDraft.owner, referenceNameById)}
                          secondary={itemReferenceSecondaryText(itemDraft.owner, referenceNameById)}
                        />
                      </ListItemButton>
                    </List>
                  </Stack>
                ) : null}
                {itemDraft.type_references.length ? (
                  <Stack spacing={1}>
                    <Typography variant="subtitle2">Type and Classifier</Typography>
                    <List dense disablePadding>
                      {itemDraft.type_references.map((reference) => (
                        <ListItemButton key={`${reference.relationship_type}-${reference.id}`} dense onClick={() => openElementId(reference.id)}>
                          <ListItemText
                            primary={itemReferenceDisplayName(reference, referenceNameById)}
                            secondary={`${humanizeFieldLabel(reference.relationship_type)}${itemReferenceSecondaryText(reference, referenceNameById) ? ` · ${itemReferenceSecondaryText(reference, referenceNameById)}` : ""}`}
                          />
                        </ListItemButton>
                      ))}
                    </List>
                  </Stack>
                ) : null}
                <Divider />
                <Typography variant="h6">Properties</Typography>
                {Object.entries(itemDraft.metadata).length ? (
                  <List dense disablePadding>
                    {Object.entries(itemDraft.metadata).map(([key, value]) => (
                      <ListItemButton key={key} dense>
                        <ListItemText primary={humanizeFieldLabel(key)} secondary={humanReadableValue(value, referenceNameById)} />
                      </ListItemButton>
                    ))}
                  </List>
                ) : (
                  <Typography color="text.secondary">No metadata returned for this item.</Typography>
                )}
                <Divider />
                <Divider />
                <Typography variant="h6">Contained Elements</Typography>
                {itemDraft.contained_elements.length ? (
                  <List dense disablePadding sx={{ maxHeight: 280, overflow: "auto" }}>
                    {itemDraft.contained_elements.map((reference) => (
                      <ListItemButton key={`${reference.relationship_type}-${reference.id}`} dense onClick={() => openElementId(reference.id)}>
                        <ListItemText
                          primary={itemReferenceDisplayName(reference, referenceNameById)}
                          secondary={`${humanizeFieldLabel(reference.relationship_type)}${itemReferenceSecondaryText(reference, referenceNameById) ? ` · ${itemReferenceSecondaryText(reference, referenceNameById)}` : ""}`}
                        />
                      </ListItemButton>
                    ))}
                  </List>
                ) : (
                  <Typography color="text.secondary">No contained elements were returned for this item.</Typography>
                )}
                <Divider />
                <Typography variant="h6">Related Elements</Typography>
                {itemDraft.related_items.length ? (
                  <List dense disablePadding sx={{ maxHeight: 280, overflow: "auto" }}>
                    {itemDraft.related_items.map((reference) => (
                      <ListItemButton key={`${reference.relationship_type}-${reference.id}`} dense onClick={() => openElementId(reference.id)}>
                        <ListItemText
                          primary={itemReferenceDisplayName(reference, referenceNameById)}
                          secondary={`${humanizeFieldLabel(reference.relationship_type)}${itemReferenceSecondaryText(reference, referenceNameById) ? ` · ${itemReferenceSecondaryText(reference, referenceNameById)}` : ""}`}
                        />
                      </ListItemButton>
                    ))}
                  </List>
                ) : itemDraft.relationships.length ? (
                  <List dense disablePadding>
                    {itemDraft.relationships.map((relationship, index) => (
                      <ListItemButton key={`${relationship.type ?? "relationship"}-${index}`} dense>
                        <ListItemText
                          primary={humanizeFieldLabel(String(relationship.type ?? `Relationship ${index + 1}`))}
                          secondary={
                            typeof relationship.target_name === "string" && relationship.target_name
                              ? relationship.target_name
                              : typeof relationship.target === "string"
                                ? (humanReadableReference(relationship.target, referenceNameById) !== relationship.target
                                    ? humanReadableReference(relationship.target, referenceNameById)
                                    : "Related item")
                              : humanReadableValue(relationship.target ?? relationship, referenceNameById)
                          }
                        />
                      </ListItemButton>
                    ))}
                  </List>
                ) : (
                  <Typography color="text.secondary">No related elements were returned for this item.</Typography>
                )}
              </Stack>
            </Paper>
          </Grid>
        </Grid>
      </Stack>
    );
  };

  const renderCompare = () => (
    <Stack spacing={2}>
      <Typography variant="h5">Compare</Typography>
              <Typography variant="body2" color="text.secondary">
                Compare model items or revisions in the current project context. Numeric left and right revisions on the same project use the RealSwagger revision diff endpoint.
              </Typography>
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Grid container spacing={2}>
          <Grid item xs={12} md={5}>
            <TextField
              label="Left item or revision"
              value={compareLeftFieldValue}
              onChange={(event) => {
                const nextValue = event.target.value;
                setCompareLeft(nextValue);
                setCompareLeftDisplay(nextValue);
              }}
              helperText={compareLeft.trim() ? compareLeftLabel : "Use a discovered item or a revision number."}
              fullWidth
            />
          </Grid>
          <Grid item xs={12} md={5}>
            <TextField
              label="Right item or revision"
              value={compareRightFieldValue}
              onChange={(event) => {
                const nextValue = event.target.value;
                setCompareRight(nextValue);
                setCompareRightDisplay(nextValue);
              }}
              helperText={compareRight.trim() ? compareRightLabel : "Use a discovered item or a revision number."}
              fullWidth
            />
          </Grid>
          <Grid item xs={12} md={2}>
            <Button
              fullWidth
              sx={{ height: "100%" }}
              variant="contained"
              startIcon={<CompareArrowsRoundedIcon />}
              disabled={!compareLeft.trim() || !compareRight.trim() || compareMutation.isPending}
              onClick={() => compareMutation.mutate()}
            >
              Compare
            </Button>
          </Grid>
        </Grid>
      </Paper>
      {(compareLeft.trim() || compareRight.trim()) && (
        <Paper sx={{ p: 3, borderRadius: 2 }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
            {compareLeft.trim() ? (
              <Box sx={{ flex: 1 }}>
                <Typography variant="overline" color="text.secondary">
                  Left Selection
                </Typography>
                <Typography variant="subtitle2">{compareLeftLabel}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {isRevisionValue(compareLeft) ? "Current project revision context" : selectedProject ? `${selectedProject.name} / ${branchLabel(selectedProjectBranches, selectedBranchId)}` : "Selected workbench context"}
                </Typography>
              </Box>
            ) : null}
            {compareRight.trim() ? (
              <Box sx={{ flex: 1 }}>
                <Typography variant="overline" color="text.secondary">
                  Right Selection
                </Typography>
                <Typography variant="subtitle2">{compareRightLabel}</Typography>
                <Typography variant="caption" color="text.secondary">
                  {isRevisionValue(compareRight) ? "Current project revision context" : selectedProject ? `${selectedProject.name} / ${branchLabel(selectedProjectBranches, selectedBranchId)}` : "Selected workbench context"}
                </Typography>
              </Box>
            ) : null}
          </Stack>
        </Paper>
      )}
      {compareMutation.isPending ? <CircularProgress size={28} /> : null}
      {compareMutation.data ? (
        <Paper sx={{ p: 3, borderRadius: 2 }}>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
              <Typography variant="h6">{compareLeftLabel && compareRightLabel ? `${compareLeftLabel} vs ${compareRightLabel}` : compareMutation.data.summary}</Typography>
                <Chip label={compareMutation.data.compare_type} />
                <Chip label={`${compareMutation.data.differences.length} differences`} variant="outlined" />
              </Stack>
            <List disablePadding>
              {compareMutation.data.differences.map((difference) => (
                <ListItemButton key={difference.field_path} alignItems="flex-start">
                  <ListItemText
                    primary={humanizeFieldPath(difference.field_path)}
                    secondary={
                      <Box component="span" sx={{ display: "block", mt: 1 }}>
                        <Typography component="span" variant="body2" sx={{ display: "block" }}>
                          {difference.summary}
                        </Typography>
                        <Typography component="pre" variant="caption" sx={{ display: "block", whiteSpace: "pre-wrap", mt: 1, mb: 0 }}>
                          {`Left: ${humanReadableValue(difference.left_value, referenceNameById)}\nRight: ${humanReadableValue(difference.right_value, referenceNameById)}`}
                        </Typography>
                      </Box>
                    }
                  />
                </ListItemButton>
              ))}
            </List>
          </Stack>
        </Paper>
      ) : null}
    </Stack>
  );

  const renderCacheIngestToken = () => {
    const sourceLabel =
      cacheIngestTokenStatus?.source === "shared"
        ? "Encrypted app storage"
        : cacheIngestTokenStatus?.source === "config"
          ? "Legacy environment fallback"
          : "Not configured";

    return (
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
            <Box>
              <Typography variant="h5">Plugin Ingest Token</Typography>
              <Typography variant="body2" color="text.secondary">
                Generate the Cameo plugin write token here. Workbench stores the app-managed token encrypted, and the plugin uses it to send model snapshots and deltas into the cache ingest API.
              </Typography>
            </Box>
            <Stack direction="row" spacing={1}>
              <Button
                variant="outlined"
                startIcon={<RefreshRoundedIcon />}
                onClick={() => queryClient.invalidateQueries({ queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey] })}
              >
                Refresh Token Status
              </Button>
            </Stack>
          </Stack>
          {cacheIngestTokenQuery.isLoading ? <CircularProgress size={28} /> : null}
          {cacheIngestTokenQuery.error ? <Alert severity="error">{errorMessage(cacheIngestTokenQuery.error)}</Alert> : null}
          {cacheIngestTokenStatus ? (
            <>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                <Chip
                  label={cacheIngestTokenStatus.configured ? "Token configured" : "Token not configured"}
                  color={cacheIngestTokenStatus.configured ? "success" : "warning"}
                />
                <Chip label={sourceLabel} variant="outlined" />
                {cacheIngestTokenStatus.token_hint ? <Chip label={cacheIngestTokenStatus.token_hint} variant="outlined" /> : null}
              </Stack>
              {cacheIngestTokenStatus.message ? <Alert severity={cacheIngestTokenStatus.source === "config" ? "warning" : "info"}>{cacheIngestTokenStatus.message}</Alert> : null}
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
                <Button
                  variant="contained"
                  disabled={!csrfToken || rotateCacheIngestTokenMutation.isPending}
                  onClick={() => rotateCacheIngestTokenMutation.mutate()}
                >
                  {cacheIngestTokenStatus.configured ? "Rotate Token" : "Generate Token"}
                </Button>
                <Button
                  variant="text"
                  color="warning"
                  disabled={!csrfToken || cacheIngestTokenStatus.source !== "shared" || clearCacheIngestTokenMutation.isPending}
                  onClick={() => clearCacheIngestTokenMutation.mutate()}
                >
                  Clear App-Managed Token
                </Button>
                {rotateCacheIngestTokenMutation.isPending || clearCacheIngestTokenMutation.isPending ? <CircularProgress size={24} /> : null}
              </Stack>
              {cacheIngestTokenStatus.updated_at ? (
                <Typography variant="caption" color="text.secondary">
                  Last updated {new Date(cacheIngestTokenStatus.updated_at).toLocaleString()}.
                </Typography>
              ) : null}
              {revealedCacheIngestToken ? (
                <>
                  <Alert severity="success">
                    Copy this token into the Cameo plugin now. Workbench stores it encrypted and will not show the full value again after you leave this screen.
                  </Alert>
                  <TextField
                    label="New plugin ingest token"
                    value={revealedCacheIngestToken}
                    fullWidth
                    InputProps={{ readOnly: true }}
                  />
                </>
              ) : null}
            </>
          ) : null}
        </Stack>
      </Paper>
    );
  };

  const renderOslc = () => {
    const response = oslcRequestMutation.data ?? null;
    const rootservices = oslcStatus?.rootservices ?? null;
    const suggestedProjectServicePath = selectedProject
      ? `/oslc/api/oslc/am/${selectedProject.resource_id ?? selectedProject.id}/services`
      : "";
    const suggestedItemPath =
      selectedProject && selectedItemId
        ? `/oslc/api/oslc/am/${selectedProject.resource_id ?? selectedProject.id}/${selectedItemId}`
        : "";
    const consumerSourceLabel =
      oslcStatus?.consumer_key_source === "config"
        ? "Config consumer"
        : oslcStatus?.consumer_key_source === "shared"
          ? "Shared consumer"
        : oslcStatus?.consumer_key_source === "session"
          ? "Session consumer"
          : "No consumer";

    return (
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
          <Box>
            <Typography variant="h5">OSLC Settings</Typography>
            <Typography variant="body2" color="text.secondary">
              OSLC is a separate connector from the RealSwagger `/osmc` API. Admins configure the shared consumer here, then authorize OSLC access for this server when needed.
            </Typography>
          </Box>
          <Stack direction="row" spacing={1}>
            <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status", ...sessionCacheKey] })}>
              Refresh OSLC
            </Button>
            {oslcStatus?.authorized ? (
              <Button variant="outlined" color="warning" disabled={!csrfToken || disconnectOslcMutation.isPending} onClick={() => disconnectOslcMutation.mutate()}>
                Disconnect
              </Button>
            ) : (
              <Button variant="contained" onClick={() => window.location.assign(api.oslcSignInUrl())} disabled={!oslcStatus?.configured}>
                Connect OSLC
              </Button>
            )}
          </Stack>
        </Stack>
        {oslcStatusQuery.isLoading ? <CircularProgress size={28} /> : null}
        {oslcStatusQuery.error ? <Alert severity="error">{errorMessage(oslcStatusQuery.error)}</Alert> : null}
        {oslcStatus ? (
          <Paper sx={{ p: 3, borderRadius: 2 }}>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                <Chip label={oslcStatus.configured ? "Consumer configured" : "Consumer not configured"} color={oslcStatus.configured ? "success" : "warning"} />
                <Chip label={oslcStatus.authorized ? "Authorized" : "Not authorized"} color={oslcStatus.authorized ? "success" : "default"} variant={oslcStatus.authorized ? "filled" : "outlined"} />
                <Chip label={consumerSourceLabel} variant="outlined" />
                <Chip label="Read-only OSLC" variant="outlined" />
                {rootservices?.raw_content_type ? <Chip label={rootservices.raw_content_type} variant="outlined" /> : null}
              </Stack>
              <Alert severity="info">
                The No Magic OSLC docs describe this API as read-only. Query services and editing are not supported; use it for resource discovery, linked-data reads, service provider browsing, and delegated-linking entry points.
              </Alert>
              {oslcStatus.message ? <Alert severity="warning">{oslcStatus.message}</Alert> : null}
              {!oslcStatus.configured && rootservices?.request_consumer_key_url ? (
                <Alert severity="info">
                  This server publishes an OSLC consumer registration endpoint. Generate a consumer below or save an approved shared consumer key and secret for this Teamwork Cloud server.
                </Alert>
              ) : null}
              {rootservices ? (
                <Stack spacing={1}>
                  <Typography variant="subtitle2">Discovered Endpoints</Typography>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label="Root Services" variant="outlined" />
                    {rootservices.request_token_url ? <Chip label="Request Token URL" variant="outlined" /> : null}
                    {rootservices.authorize_url ? <Chip label="Authorize URL" variant="outlined" /> : null}
                    {rootservices.access_token_url ? <Chip label="Access Token URL" variant="outlined" /> : null}
                    {rootservices.service_provider_catalog_url ? <Chip label="Service Provider Catalog" variant="outlined" /> : null}
                    {rootservices.configuration_management_service_providers_url ? <Chip label="CM Service Providers" variant="outlined" /> : null}
                    {rootservices.request_consumer_key_url ? <Chip label="Consumer Key Registration" variant="outlined" /> : null}
                  </Stack>
                  <TextField label="Root Services URL" value={rootservices.rootservices_url} fullWidth InputProps={{ readOnly: true }} />
                  {rootservices.request_consumer_key_url ? (
                    <TextField label="Consumer Key Registration URL" value={rootservices.request_consumer_key_url} fullWidth InputProps={{ readOnly: true }} />
                  ) : null}
                  {rootservices.service_provider_catalog_url ? (
                    <TextField label="Service Provider Catalog URL" value={rootservices.service_provider_catalog_url} fullWidth InputProps={{ readOnly: true }} />
                  ) : null}
                  {rootservices.configuration_management_service_providers_url ? (
                    <TextField
                      label="Configuration Management Service Providers URL"
                      value={rootservices.configuration_management_service_providers_url}
                      fullWidth
                      InputProps={{ readOnly: true }}
                    />
                  ) : null}
                </Stack>
              ) : null}
            </Stack>
          </Paper>
        ) : null}
        <Paper sx={{ p: 3, borderRadius: 2 }}>
          <Stack spacing={2}>
            <Typography variant="subtitle2">OSLC Consumer Setup</Typography>
            <Typography variant="body2" color="text.secondary">
              Teamwork Cloud OSLC uses OAuth 1.0a. Save one approved consumer key and secret here, then every admin session on this server can reuse that shared configuration.
            </Typography>
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <Stack spacing={1.5}>
                  <Typography variant="body2" fontWeight={600}>
                    Generate Consumer Key
                  </Typography>
                  <TextField
                    label="Consumer Name"
                    value={oslcConsumerName}
                    onChange={(event) => setOslcConsumerName(event.target.value)}
                    fullWidth
                  />
                  <TextField
                    label="Consumer Secret"
                    type="password"
                    value={oslcConsumerSecret}
                    onChange={(event) => setOslcConsumerSecret(event.target.value)}
                    helperText={
                      rootservices?.request_consumer_key_url
                        ? "The returned key still needs approval in Magic Collaboration Studio Settings before OSLC sign-in will succeed."
                        : "This server did not publish a consumer-key registration endpoint in root services."
                    }
                    fullWidth
                  />
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
                    <Button
                      variant="outlined"
                      disabled={
                        !csrfToken ||
                        !rootservices?.request_consumer_key_url ||
                        !oslcConsumerName.trim() ||
                        !oslcConsumerSecret ||
                        generateOslcConsumerMutation.isPending
                      }
                      onClick={() => generateOslcConsumerMutation.mutate()}
                    >
                      Generate Consumer Key
                    </Button>
                    {generateOslcConsumerMutation.isPending ? <CircularProgress size={24} /> : null}
                  </Stack>
                </Stack>
              </Grid>
              <Grid item xs={12} md={6}>
                <Stack spacing={1.5}>
                  <Typography variant="body2" fontWeight={600}>
                    Shared Consumer for This Server
                  </Typography>
                  <TextField
                    label="Consumer Key"
                    value={oslcManualKey}
                    onChange={(event) => setOslcManualKey(event.target.value)}
                    fullWidth
                  />
                  <TextField
                    label="Consumer Secret"
                    type="password"
                    value={oslcManualSecret}
                    onChange={(event) => setOslcManualSecret(event.target.value)}
                    helperText={
                      sharedOslcConsumer?.configured
                        ? "Enter a new secret only when rotating the shared OSLC consumer for this server."
                        : "Use the key and secret created or approved in Teamwork Cloud Settings."
                    }
                    fullWidth
                  />
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
                    <Button
                      variant="outlined"
                      disabled={!csrfToken || !oslcManualKey.trim() || !oslcManualSecret || storeOslcConsumerMutation.isPending}
                      onClick={() => storeOslcConsumerMutation.mutate()}
                    >
                      Save Shared Consumer
                    </Button>
                    <Button
                      variant="text"
                      color="warning"
                      disabled={!csrfToken || sharedOslcConsumer?.source !== "shared" || clearOslcConsumerMutation.isPending}
                      onClick={() => clearOslcConsumerMutation.mutate()}
                    >
                      Clear Shared Consumer
                    </Button>
                    {storeOslcConsumerMutation.isPending || clearOslcConsumerMutation.isPending ? <CircularProgress size={24} /> : null}
                  </Stack>
                </Stack>
              </Grid>
            </Grid>
          </Stack>
        </Paper>
        <Paper sx={{ p: 3, borderRadius: 2 }}>
          <Stack spacing={2}>
            <Typography variant="subtitle2">OSLC Request</Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Button size="small" variant="outlined" onClick={() => setOslcPath("/oslc/api/rootservices")}>
                Root Services
              </Button>
              {rootservices?.service_provider_catalog_url ? (
                <Button size="small" variant="outlined" onClick={() => setOslcPath(rootservices.service_provider_catalog_url ?? "")}>
                  Service Providers
                </Button>
              ) : null}
              {rootservices?.configuration_management_service_providers_url ? (
                <Button
                  size="small"
                  variant="outlined"
                  onClick={() => setOslcPath(rootservices.configuration_management_service_providers_url ?? "")}
                >
                  CM Providers
                </Button>
              ) : null}
              {suggestedProjectServicePath ? (
                <Button size="small" variant="outlined" onClick={() => setOslcPath(suggestedProjectServicePath)}>
                  Current Project Services
                </Button>
              ) : null}
              {suggestedItemPath ? (
                <Button size="small" variant="outlined" onClick={() => setOslcPath(suggestedItemPath)}>
                  Current Item Resource
                </Button>
              ) : null}
            </Stack>
            <TextField
              label="Path or URL"
              value={oslcPath}
              onChange={(event) => setOslcPath(event.target.value)}
              helperText="Use a full URL or a relative OSLC path such as /oslc/api/rootservices."
              fullWidth
            />
            <TextField select label="Accept" value={oslcAccept} onChange={(event) => setOslcAccept(event.target.value)} fullWidth>
              {["application/rdf+xml", "application/ld+json", "application/xml", "text/turtle", "application/json", "text/plain"].map((contentType) => (
                <MenuItem key={contentType} value={contentType}>
                  {contentType}
                </MenuItem>
              ))}
            </TextField>
            {!oslcStatus?.authorized && oslcStatus?.configured ? (
              <Alert severity="info">
                Connect OSLC first. REST and CLI-style `/osmc` commands already use the Teamwork Cloud token session; OSLC remains its own OAuth 1.0a lane.
              </Alert>
            ) : null}
            {!oslcStatus?.configured ? (
              <Alert severity="warning">
                OSLC needs an approved shared consumer key and secret before authorization can start. Generate one from root services or save an approved pair for this server.
              </Alert>
            ) : null}
            <Stack direction="row" spacing={1.5} alignItems="center">
              <Button
                variant="contained"
                disabled={!csrfToken || !oslcStatus?.authorized || !oslcPath.trim() || oslcRequestMutation.isPending}
                onClick={() => oslcRequestMutation.mutate()}
              >
                Execute GET
              </Button>
              {oslcRequestMutation.isPending ? <CircularProgress size={24} /> : null}
            </Stack>
          </Stack>
        </Paper>
        {response ? (
          <Paper sx={{ p: 3, borderRadius: 2 }}>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
                <Typography variant="h6">OSLC Response</Typography>
                <Chip label={`${response.status_code}`} color={response.ok ? "success" : "error"} />
                <Chip label={response.content_type || "no content type"} variant="outlined" />
                <Chip label={`${response.size_bytes} bytes`} variant="outlined" />
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ wordBreak: "break-all" }}>
                {response.requested_url}
              </Typography>
              {response.body_base64 ? (
                <Button variant="outlined" onClick={() => downloadBinaryResponse(response)}>
                  Download Response Body
                </Button>
              ) : null}
              <TextField
                label="Response body"
                value={oslcResponseContent(response)}
                fullWidth
                multiline
                minRows={10}
                InputProps={{ readOnly: true }}
              />
              <TextField
                label="Response headers"
                value={JSON.stringify(response.headers, null, 2)}
                fullWidth
                multiline
                minRows={4}
                InputProps={{ readOnly: true }}
              />
            </Stack>
          </Paper>
        ) : null}
      </Stack>
    );
  };

  const renderAdminSettings = () => (
    <Stack spacing={2}>
      {renderCacheIngestToken()}
      {renderOslc()}
    </Stack>
  );

  const renderApiExplorer = () => {
    const response = apiOperationMutation.data ?? null;
    if (!isAdmin) {
      return <Alert severity="warning">Administrator access is required for API Explorer.</Alert>;
    }
    return (
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
          <Box>
            <Typography variant="h5">API Explorer</Typography>
            <Typography variant="body2" color="text.secondary">
              Every action here is generated from RealSwagger.json and executed only through declared method/path/parameter combinations.
            </Typography>
          </Box>
          <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => queryClient.invalidateQueries({ queryKey: ["workspace-contract", ...sessionCacheKey] })}>
            Refresh Contract
          </Button>
        </Stack>
        {contractQuery.isLoading ? <CircularProgress size={28} /> : null}
        {contractQuery.error ? <Alert severity="error">{errorMessage(contractQuery.error)}</Alert> : null}
        {contractManifest ? (
          <Grid container spacing={2}>
            <Grid item xs={12} md={4}>
              <Paper sx={{ p: 2, borderRadius: 2 }}>
                <Stack spacing={2}>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label={contractManifest.version || contractManifest.title} />
                    <Chip label={`${contractManifest.operations.length} operations`} variant="outlined" />
                    <Chip label={`${contractManifest.schemas.length} schemas`} variant="outlined" />
                  </Stack>
                  <TextField select label="Functional Area" value={selectedApiTag} onChange={(event) => setSelectedApiTag(event.target.value)} fullWidth>
                    {apiTags.map((tag) => (
                      <MenuItem key={tag} value={tag}>
                        {tag} ({contractManifest.tag_counts[tag]})
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField label="Filter operations" value={apiSearch} onChange={(event) => setApiSearch(event.target.value)} fullWidth />
                  <List dense disablePadding sx={{ maxHeight: 560, overflow: "auto" }}>
                    {filteredApiOperations.map((operation) => (
                      <ListItemButton
                        key={operation.key}
                        selected={selectedOperation?.key === operation.key}
                        onClick={() => setSelectedOperationKey(operation.key)}
                      >
                        <ListItemText
                          primary={
                            <Stack direction="row" spacing={1} alignItems="center">
                              <Chip label={operation.method} size="small" color={operation.destructive ? "warning" : "default"} />
                              <Typography variant="body2" sx={{ wordBreak: "break-all" }}>
                                {operation.path}
                              </Typography>
                            </Stack>
                          }
                          secondary={operation.summary || operation.description || operation.key}
                        />
                      </ListItemButton>
                    ))}
                  </List>
                  {!filteredApiOperations.length ? <Typography color="text.secondary">No operations match this filter.</Typography> : null}
                </Stack>
              </Paper>
            </Grid>
            <Grid item xs={12} md={8}>
              {selectedOperation ? (
                <Stack spacing={2}>
                  <Paper sx={{ p: 3, borderRadius: 2 }}>
                    <Stack spacing={2}>
                      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
                        <Chip label={selectedOperation.method} color={selectedOperation.destructive ? "warning" : "default"} />
                        <Typography variant="h6" sx={{ wordBreak: "break-all" }}>
                          {selectedOperation.path}
                        </Typography>
                      </Stack>
                      {selectedOperation.summary || selectedOperation.description ? (
                        <Typography color="text.secondary">{selectedOperation.summary || selectedOperation.description}</Typography>
                      ) : null}
                      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                        {selectedOperation.request_body?.content_types.map((contentType) => (
                          <Chip key={contentType} label={contentType} variant="outlined" />
                        ))}
                        {selectedOperation.supports_file_upload ? <Chip label="File upload" color="info" variant="outlined" /> : null}
                        {selectedOperation.supports_download ? <Chip label="Download-capable" color="info" variant="outlined" /> : null}
                        {selectedOperation.responses.map((apiResponse) => (
                          <Chip
                            key={`${apiResponse.status_code}-${apiResponse.schema_ref ?? "response"}`}
                            label={`${apiResponse.status_code}${apiResponse.schema_ref ? ` ${apiResponse.schema_ref}` : ""}`}
                            size="small"
                            variant="outlined"
                          />
                        ))}
                      </Stack>
                      {selectedOperation.destructive ? (
                        <Alert severity="warning">
                          This operation can change or delete data. It is still executed only against the Swagger-declared TWC endpoint and will use the current authenticated TWC session.
                        </Alert>
                      ) : null}
                    </Stack>
                  </Paper>
                  <Paper sx={{ p: 3, borderRadius: 2 }}>
                    <Stack spacing={2}>
                      {renderParameterControls("Path Parameters", selectedOperation.path_parameters, apiPathParams, (name, value) =>
                        setApiPathParams((current) => ({ ...current, [name]: value })),
                      )}
                      <Divider />
                      {renderParameterControls("Query Parameters", selectedOperation.query_parameters, apiQueryParams, (name, value) =>
                        setApiQueryParams((current) => ({ ...current, [name]: value })),
                      )}
                      {selectedOperation.request_body && !selectedOperation.supports_file_upload ? (
                        <>
                          <Divider />
                          <Stack spacing={1.5}>
                            <Typography variant="subtitle2">Request Body</Typography>
                            <TextField
                              select
                              label="Content-Type"
                              value={apiContentType}
                              onChange={(event) => {
                                setApiContentType(event.target.value);
                                setApiBodyText(event.target.value === "text/plain" ? "" : requestBodyTemplate(selectedOperation, contractManifest));
                              }}
                              fullWidth
                            >
                              {selectedOperation.request_body.content_types.map((contentType) => (
                                <MenuItem key={contentType} value={contentType}>
                                  {contentType}
                                </MenuItem>
                              ))}
                            </TextField>
                            <TextField
                              label={apiContentType === "text/plain" ? "Text payload" : "JSON payload"}
                              value={apiBodyText}
                              onChange={(event) => setApiBodyText(event.target.value)}
                              fullWidth
                              multiline
                              minRows={8}
                              helperText={selectedOperation.request_body.description || "Payload shape is derived from the Swagger requestBody schema."}
                            />
                          </Stack>
                        </>
                      ) : null}
                      {selectedOperation.supports_file_upload ? (
                        <>
                          <Divider />
                          <Stack spacing={1.5}>
                            <Typography variant="subtitle2">File Upload</Typography>
                            <Button variant="outlined" component="label">
                              Choose File
                              <input
                                hidden
                                type="file"
                                onChange={(event) => setApiUploadFile(event.target.files?.[0] ?? null)}
                              />
                            </Button>
                            <Typography variant="body2" color="text.secondary">
                              {apiUploadFile ? `${apiUploadFile.name} (${apiUploadFile.size} bytes)` : "No file selected."}
                            </Typography>
                          </Stack>
                        </>
                      ) : null}
                      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
                        <Button
                          variant="contained"
                          disabled={!selectedOperation || !csrfToken || apiOperationMutation.isPending}
                          onClick={() => apiOperationMutation.mutate()}
                        >
                          Execute Operation
                        </Button>
                        {apiOperationMutation.isPending ? <CircularProgress size={24} /> : null}
                      </Stack>
                    </Stack>
                  </Paper>
                  {response ? (
                    <Paper sx={{ p: 3, borderRadius: 2 }}>
                      <Stack spacing={2}>
                        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
                          <Typography variant="h6">Response</Typography>
                          <Chip label={`${response.status_code}`} color={response.ok ? "success" : "error"} />
                          <Chip label={response.content_type || "no content type"} variant="outlined" />
                          <Chip label={`${response.size_bytes} bytes`} variant="outlined" />
                        </Stack>
                        <Typography variant="body2" color="text.secondary" sx={{ wordBreak: "break-all" }}>
                          {response.method} {response.requested_path}
                        </Typography>
                        {response.body_base64 ? (
                          <Button variant="outlined" onClick={() => downloadSwaggerResponse(response)}>
                            Download Response Body
                          </Button>
                        ) : null}
                        <TextField
                          label="Response body"
                          value={responseContent(response)}
                          fullWidth
                          multiline
                          minRows={10}
                          InputProps={{ readOnly: true }}
                        />
                        <TextField
                          label="Response headers"
                          value={JSON.stringify(response.headers, null, 2)}
                          fullWidth
                          multiline
                          minRows={4}
                          InputProps={{ readOnly: true }}
                        />
                      </Stack>
                    </Paper>
                  ) : null}
                </Stack>
              ) : (
                <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
                  <Typography color="text.secondary">Select an operation to build a Swagger-backed request.</Typography>
                </Paper>
              )}
            </Grid>
          </Grid>
        ) : null}
      </Stack>
    );
  };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="sticky" color="default" elevation={1}>
        <Toolbar sx={{ gap: 2 }}>
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <Typography variant="h6" noWrap>
              TWC Workbench
            </Typography>
            <Typography variant="caption" color="text.secondary" noWrap>
              {session?.server?.name ?? "Teamwork Cloud"} / {session?.user?.preferred_username ?? "authenticated user"}
            </Typography>
          </Box>
          {session?.capabilities ? <CapabilityBadges capabilities={session.capabilities.capabilities} /> : null}
          <Tooltip title="Refresh capabilities">
            <span>
              <IconButton onClick={() => capabilityMutation.mutate()} disabled={!csrfToken || capabilityMutation.isPending}>
                <RefreshRoundedIcon />
              </IconButton>
            </span>
          </Tooltip>
          <Tooltip title="Workspace settings">
            <IconButton onClick={() => setSettingsOpen(true)}>
              <SettingsRoundedIcon />
            </IconButton>
          </Tooltip>
          <Tooltip title="Sign out">
            <span>
              <IconButton onClick={() => logoutMutation.mutate()} disabled={!csrfToken || logoutMutation.isPending}>
                <LogoutRoundedIcon />
              </IconButton>
            </span>
          </Tooltip>
        </Toolbar>
      </AppBar>
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", lg: "360px 1fr" }, gap: 2, p: { xs: 2, md: 3 } }}>
        <Paper component="aside" sx={{ p: 2, borderRadius: 2, height: "fit-content" }}>
          <Stack spacing={2}>
            <TextField
              select
              label="Project"
              value={selectedProjectId}
              onChange={(event) => selectProject(event.target.value)}
              fullWidth
              disabled={!projects.length}
            >
              <MenuItem value="">
                <em>Select a project</em>
              </MenuItem>
              {projects.map((project) => (
                <MenuItem key={project.id} value={project.id}>
                  {project.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Branch"
              value={selectedBranchId}
              onChange={(event) => setSelectedBranchId(event.target.value)}
              fullWidth
              disabled={!selectedProjectId || branchesQuery.isLoading || !selectedProjectBranches.length}
            >
              {!selectedProjectId ? (
                <MenuItem value="" disabled>
                  Select a project first
                </MenuItem>
              ) : selectedProjectBranches.length ? (
                selectedProjectBranches.map((branch) => (
                  <MenuItem key={branch.id} value={branch.id}>
                    {branch.name}
                  </MenuItem>
                ))
              ) : branchesQuery.isLoading ? (
                <MenuItem value="" disabled>
                  Loading branches...
                </MenuItem>
              ) : (
                <MenuItem value="">Default</MenuItem>
              )}
            </TextField>
            <TextField label="Filter model tree" value={treeFilter} onChange={(event) => setTreeFilter(event.target.value)} fullWidth />
            {selectedWorkspaceItem ? (
              <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                <Stack spacing={0.75}>
                  <Typography variant="overline" color="text.secondary">
                    Current Selection
                  </Typography>
                  <Typography variant="subtitle2">{selectedWorkspaceItemName}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {selectedWorkspaceItemPath || (selectedProject ? `${selectedProject.name} / ${branchLabel(selectedProjectBranches, selectedBranchId)}` : humanizeFieldLabel(selectedWorkspaceItem.item_type))}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {humanizeFieldLabel(selectedWorkspaceItem.item_type)}
                  </Typography>
                </Stack>
              </Paper>
            ) : null}
            <Divider />
            <ProjectTree nodes={treeNodes} selectedId={selectedItemId} filter={treeFilter} onSelect={openNode} />
          </Stack>
        </Paper>
        <Stack spacing={2} component="main">
          {notice ? <Alert severity={notice.severity} onClose={() => setNotice(null)}>{notice.message}</Alert> : null}
          {projectsQuery.error ? <Alert severity="error">{errorMessage(projectsQuery.error)}</Alert> : null}
          <Paper sx={{ borderRadius: 2 }}>
            <Tabs value={tab} onChange={handleTabChange} variant="scrollable" scrollButtons="auto">
              <Tab label="Dashboard" value="dashboard" />
              <Tab label="Project Browser" value="projects" />
              <Tab label="Model Browser" value="models" />
              <Tab label="Element testing" value="elements" />
              <Tab label="Item Details" value="details" />
              <Tab label="Compare" value="compare" />
              {isAdmin ? <Tab label="API Explorer" value="api" /> : null}
            </Tabs>
          </Paper>
          <Box>
            {tab === "dashboard" ? renderDashboard() : null}
            {tab === "projects" ? renderProjects() : null}
            {tab === "models" ? renderModels() : null}
            {tab === "elements" ? renderElementTesting() : null}
            {tab === "details" ? renderDetails() : null}
            {tab === "compare" ? renderCompare() : null}
            {tab === "api" ? renderApiExplorer() : null}
          </Box>
        </Stack>
      </Box>
      <SettingsDialog
        open={settingsOpen}
        preferences={session?.preferences ?? { theme_mode: "system", font_scale: 1, request_timeout_seconds: 30, live_log_poll_interval_ms: 2500, presentation_font_scale: 1.2 }}
        saving={settingsMutation.isPending}
        extraContent={isAdmin ? renderAdminSettings() : null}
        onClose={() => {
          setSettingsOpen(false);
          setRevealedCacheIngestToken("");
        }}
        onSave={async (preferences) => {
          await settingsMutation.mutateAsync(preferences);
        }}
      />
    </Box>
  );
}
