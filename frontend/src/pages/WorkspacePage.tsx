import { type SyntheticEvent, useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  AppBar,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  FormControlLabel,
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
import ExpandMoreRoundedIcon from "@mui/icons-material/ExpandMoreRounded";
import LogoutRoundedIcon from "@mui/icons-material/LogoutRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import SaveRoundedIcon from "@mui/icons-material/SaveRounded";
import SettingsRoundedIcon from "@mui/icons-material/SettingsRounded";

import CapabilityBadges from "../components/CapabilityBadges";
import ProjectTree from "../components/ProjectTree";
import SettingsDialog from "../components/SettingsDialog";
import {
  BranchAccessManifestStatus,
  CacheApiKeyScope,
  CacheApiKeySummary,
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

type WorkspaceTab = "dashboard" | "projects" | "models" | "elements" | "details" | "compare" | "developer" | "api";

function errorMessage(caught: unknown): string {
  return caught instanceof Error ? caught.message : "The request failed.";
}

function flattenTree(nodes: TreeNode[]): TreeNode[] {
  const flattened: TreeNode[] = [];
  const stack = [...nodes].reverse();
  while (stack.length) {
    const node = stack.pop();
    if (!node) {
      continue;
    }
    flattened.push(node);
    for (let index = node.children.length - 1; index >= 0; index -= 1) {
      stack.push(node.children[index]);
    }
  }
  return flattened;
}

function replaceNodeChildren(nodes: TreeNode[], targetId: string, children: TreeNode[]): TreeNode[] {
  let changed = false;
  const nextNodes = nodes.map((node) => {
    if (node.id === targetId) {
      changed = true;
      return {
        ...node,
        children,
        metadata: {
          ...node.metadata,
          children_loaded: true,
        },
      };
    }
    if (!node.children.length) {
      return node;
    }
    const nextChildren = replaceNodeChildren(node.children, targetId, children);
    if (nextChildren !== node.children) {
      changed = true;
      return { ...node, children: nextChildren };
    }
    return node;
  });
  return changed ? nextNodes : nodes;
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

function hasMeaningfulValue(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value as Record<string, unknown>).length > 0;
  }
  return true;
}

interface InspectorRow {
  key: string;
  label: string;
  value: string;
}

function mapToInspectorRows(source: Record<string, unknown>, lookup: Record<string, string>): InspectorRow[] {
  return Object.entries(source)
    .filter(([, value]) => hasMeaningfulValue(value))
    .sort(([leftKey], [rightKey]) => compareDisplayValues(humanizeFieldLabel(leftKey), humanizeFieldLabel(rightKey)))
    .map(([key, value]) => ({
      key,
      label: humanizeFieldLabel(key),
      value: humanReadableValue(value, lookup),
    }));
}

function payloadAttributes(item: ItemDetails): Record<string, unknown> {
  const sourcePayload = item.source_payload ?? {};
  return sourcePayload.attributes && typeof sourcePayload.attributes === "object" && !Array.isArray(sourcePayload.attributes)
    ? (sourcePayload.attributes as Record<string, unknown>)
    : {};
}

function payloadReferences(item: ItemDetails): Record<string, unknown> {
  const sourcePayload = item.source_payload ?? {};
  return sourcePayload.references && typeof sourcePayload.references === "object" && !Array.isArray(sourcePayload.references)
    ? (sourcePayload.references as Record<string, unknown>)
    : {};
}

function payloadExtraSections(item: ItemDetails): Array<[string, unknown]> {
  const sourcePayload = item.source_payload ?? {};
  return Object.entries(sourcePayload).filter(([key, value]) => {
    if (
      [
        "element_id",
        "model_id",
        "local_id",
        "owner_id",
        "name",
        "human_name",
        "qualified_name",
        "human_type",
        "metaclass",
        "documentation",
        "owned_element_ids",
        "applied_stereotype_ids",
        "attributes",
        "references",
      ].includes(key)
    ) {
      return false;
    }
    return hasMeaningfulValue(value);
  });
}

function identityRows(item: ItemDetails, lookup: Record<string, string>): InspectorRow[] {
  const sourcePayload = item.source_payload ?? {};
  const fields: Record<string, unknown> = {
    id: item.id,
    type: item.item_type,
    path: friendlyPath(item.path, lookup),
    qualified_name: sourcePayload.qualified_name,
    metaclass: sourcePayload.metaclass,
    model_id: sourcePayload.model_id,
    local_id: sourcePayload.local_id,
    owner_id: sourcePayload.owner_id,
    version: item.version,
  };
  return mapToInspectorRows(fields, lookup);
}

function overviewRows(item: ItemDetails, lookup: Record<string, string>): InspectorRow[] {
  const fields: Record<string, unknown> = {
    name: item.name,
    description: item.description,
    stereotypes: item.stereotypes,
    raw_types: item.raw_types,
  };
  return mapToInspectorRows(fields, lookup);
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

  const toggleNewCacheApiKeyScope = (scope: CacheApiKeyScope, checked: boolean) => {
    setNewCacheApiKeyScopes((current) => {
      if (checked) {
        return current.includes(scope) ? current : [...current, scope];
      }
      return current.filter((value) => value !== scope);
    });
  };

  const [tab, setTab] = useState<WorkspaceTab>("dashboard");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedBranchId, setSelectedBranchId] = useState("");
  const [treeFilter, setTreeFilter] = useState("");
  const [selectedItemId, setSelectedItemId] = useState("");
  const [treeNodes, setTreeNodes] = useState<TreeNode[]>([]);
  const [loadingTreeNodeIds, setLoadingTreeNodeIds] = useState<string[]>([]);
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
  const [manualCacheIngestToken, setManualCacheIngestToken] = useState("");
  const [revealedCacheIngestToken, setRevealedCacheIngestToken] = useState("");
  const [newCacheApiKeyLabel, setNewCacheApiKeyLabel] = useState("");
  const [revealedCacheApiKey, setRevealedCacheApiKey] = useState("");
  const [newCacheApiKeyScopes, setNewCacheApiKeyScopes] = useState<CacheApiKeyScope[]>(["read"]);
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
  const cacheApiKeysQuery = useQuery({
    queryKey: ["workspace-cache-api-keys", ...sessionCacheKey],
    queryFn: api.listCacheApiKeys,
    enabled: Boolean(session?.user?.preferred_username),
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
    queryFn: () => api.getTree(selectedProjectId || undefined, selectedBranchId || undefined, selectedProject?.workspace_id || undefined, false, 1),
    enabled:
      projectContextActive &&
      Boolean(selectedProjectId) &&
      !branchesQuery.isLoading &&
      (!selectedProjectBranches.length || Boolean(selectedBranchId)),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    setTreeNodes(treeQuery.data ?? []);
    setLoadingTreeNodeIds([]);
  }, [treeQuery.data]);

  const flatNodes = useMemo(() => flattenTree(treeNodes), [treeNodes]);
  const elementDiscoveryQuery = useQuery({
    queryKey: ["workspace-elements", ...sessionCacheKey, selectedProjectId, selectedBranchId, selectedProject?.workspace_id],
    queryFn: () => api.getElementDiscovery(selectedProjectId, selectedBranchId, selectedProject?.workspace_id || undefined),
    enabled: tab === "elements" && Boolean(selectedProjectId) && Boolean(selectedBranchId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const branchAccessManifestQuery = useQuery({
    queryKey: ["workspace-access-map", ...sessionCacheKey, selectedProjectId, selectedBranchId],
    queryFn: () => api.getBranchAccessManifestStatus(selectedProjectId, selectedBranchId),
    enabled: Boolean(selectedProjectId) && Boolean(selectedBranchId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const elementDiscovery: ElementDiscoveryResult | null = elementDiscoveryQuery.data ?? null;
  const branchAccessManifestStatus: BranchAccessManifestStatus | null = branchAccessManifestQuery.data ?? null;
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
  const cacheApiKeys = cacheApiKeysQuery.data ?? [];

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
  const selectedTreeNode = useMemo(
    () => (selectedItemId ? flatNodes.find((node) => node.id === selectedItemId) ?? null : null),
    [flatNodes, selectedItemId],
  );
  const selectedContainmentPath = selectedWorkspaceItemPath || (selectedTreeNode ? friendlyPath(selectedTreeNode.path, referenceNameById) : "");
  const selectedContainmentSegments = selectedContainmentPath
    .split(" / ")
    .map((segment) => segment.trim())
    .filter(Boolean);
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
      setNotice({ severity: "success", message: "Cached project catalog reloaded." });
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
        tree = await api.getTree(selectedProjectId, currentBranchId, selectedProject?.workspace_id || undefined, true, 1);
      }
      return { branches, tree, branchId: currentBranchId ?? "" };
    },
    onSuccess: ({ branches, tree, branchId }) => {
      queryClient.setQueryData(["workspace-branches", ...sessionCacheKey, selectedProjectId, selectedProject?.workspace_id], branches);
      if (branchId) {
        queryClient.setQueryData(["workspace-tree", ...sessionCacheKey, selectedProjectId, branchId], tree ?? []);
        setSelectedBranchId(branchId);
      }
      setNotice({ severity: "success", message: "Cached project data reloaded and permissions rechecked." });
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
      setNotice({ severity: "success", message: "Cached model item reloaded and permissions rechecked." });
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
      setNotice({ severity: "success", message: "Cached branch elements reloaded and permissions rechecked." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const refreshBranchAccessManifestMutation = useMutation({
    mutationFn: () => {
      if (!selectedProjectId || !selectedBranchId) {
        throw new Error("Select a project branch before refreshing access.");
      }
      return api.refreshBranchAccessManifest(selectedProjectId, selectedBranchId, csrfToken);
    },
    onSuccess: async (status) => {
      queryClient.setQueryData(["workspace-access-map", ...sessionCacheKey, selectedProjectId, selectedBranchId], status);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workspace-projects", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-branches", ...sessionCacheKey, selectedProjectId, selectedProject?.workspace_id] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-tree", ...sessionCacheKey, selectedProjectId, selectedBranchId] }),
        queryClient.invalidateQueries({
          queryKey: ["workspace-elements", ...sessionCacheKey, selectedProjectId, selectedBranchId, selectedProject?.workspace_id],
        }),
        selectedItemId
          ? queryClient.invalidateQueries({
              queryKey: ["workspace-item", ...sessionCacheKey, selectedItemId, selectedProjectId, selectedBranchId],
            })
          : Promise.resolve(),
      ]);
      setNotice({ severity: "success", message: "Shared access map refreshed from Teamwork Cloud." });
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
      setManualCacheIngestToken(result.token);
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "A new plugin ingest token was generated and stored inside Workbench." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const storeCacheIngestTokenMutation = useMutation({
    mutationFn: () =>
      api.updateCacheIngestToken(
        {
          token: manualCacheIngestToken.trim(),
        },
        csrfToken,
      ),
    onSuccess: async () => {
      setRevealedCacheIngestToken("");
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "The exact plugin ingest token was saved in encrypted Workbench app storage." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const clearCacheIngestTokenMutation = useMutation({
    mutationFn: () => api.clearCacheIngestToken(csrfToken),
    onSuccess: async () => {
      setRevealedCacheIngestToken("");
      setManualCacheIngestToken("");
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "The app-managed plugin ingest token was cleared." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const createCacheApiKeyMutation = useMutation({
    mutationFn: () =>
      api.createCacheApiKey(
        {
          label: newCacheApiKeyLabel.trim(),
          scopes: newCacheApiKeyScopes,
        },
        csrfToken,
      ),
    onSuccess: async (result) => {
      setRevealedCacheApiKey(result.token);
      setNewCacheApiKeyLabel("");
      setNewCacheApiKeyScopes(["read"]);
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-api-keys", ...sessionCacheKey] });
      setNotice({
        severity: "success",
        message: "API key created. Copy it now; Workbench will not show the full value again after you leave this screen.",
      });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const deleteCacheApiKeyMutation = useMutation({
    mutationFn: (keyId: string) => api.deleteCacheApiKey(keyId, csrfToken),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-api-keys", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "API key deleted." });
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

  const selectContainmentNode = (node: TreeNode, preferredTab: WorkspaceTab = "models") => {
    setSelectedItemId(node.id);
    if (!["models", "elements", "details"].includes(tab)) {
      setTab(preferredTab);
    }
  };

  const openNode = (node: TreeNode) => {
    setSelectedItemId(node.id);
    setTab("details");
  };

  const openElementId = (itemId: string) => {
    setSelectedItemId(itemId);
    setTab("details");
  };

  const loadTreeChildren = async (node: TreeNode) => {
    if (!selectedProjectId || !selectedBranchId) {
      return;
    }
    if (loadingTreeNodeIds.includes(node.id)) {
      return;
    }
    const modelId = typeof node.metadata.model_id === "string" ? node.metadata.model_id : undefined;
    setLoadingTreeNodeIds((current) => [...current, node.id]);
    try {
      const children = await api.getTreeChildren(
        selectedProjectId,
        selectedBranchId,
        node.id,
        modelId,
        selectedProject?.workspace_id || undefined,
      );
      setTreeNodes((current) => replaceNodeChildren(current, node.id, children));
    } catch (caught) {
      setNotice({ severity: "error", message: errorMessage(caught) });
    } finally {
      setLoadingTreeNodeIds((current) => current.filter((value) => value !== node.id));
    }
  };

  const renderInspectorRows = (rows: InspectorRow[], emptyText: string) =>
    rows.length ? (
      <List dense disablePadding>
        {rows.map((row) => (
          <ListItemButton key={row.key} dense disableRipple sx={{ alignItems: "flex-start", cursor: "default" }}>
            <ListItemText
              primary={row.label}
              secondary={
                <Typography component="span" variant="body2" sx={{ whiteSpace: "pre-wrap", display: "block", mt: 0.25 }}>
                  {row.value || "Not provided"}
                </Typography>
              }
            />
          </ListItemButton>
        ))}
      </List>
    ) : (
      <Typography color="text.secondary">{emptyText}</Typography>
    );

  const renderReferenceList = (references: ItemReference[], emptyText: string) =>
    references.length ? (
      <List dense disablePadding sx={{ maxHeight: 320, overflow: "auto" }}>
        {references.map((reference) => (
          <ListItemButton key={`${reference.relationship_type}-${reference.id}`} dense onClick={() => openElementId(reference.id)}>
            <ListItemText
              primary={itemReferenceDisplayName(reference, referenceNameById)}
              secondary={`${humanizeFieldLabel(reference.relationship_type)}${itemReferenceSecondaryText(reference, referenceNameById) ? ` · ${itemReferenceSecondaryText(reference, referenceNameById)}` : ""}`}
            />
          </ListItemButton>
        ))}
      </List>
    ) : (
      <Typography color="text.secondary">{emptyText}</Typography>
    );

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
            Browse the published content for the selected project and branch from the Workbench snapshot cache.
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={<RefreshRoundedIcon />}
          onClick={() => refreshSelectedProjectMutation.mutate()}
          disabled={!selectedProjectId || refreshSelectedProjectMutation.isPending}
        >
          Reload Cached Project
        </Button>
      </Stack>
      {!selectedProject ? (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a project</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Use the selector on the left to choose which published project snapshot you want to browse.
          </Typography>
        </Paper>
      ) : null}
      {selectedProject ? (
        <Paper sx={{ p: 3, borderRadius: 2 }}>
          <Stack spacing={1.5}>
            <Typography variant="h6">{selectedProject.name}</Typography>
            <Typography variant="body2" color="text.secondary">
              {selectedProject.description || "Browse the current branch snapshot as cards for quick scanning and jumping into details."}
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Chip label="Workbench cached project" variant="outlined" />
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
      {!treeQuery.isLoading && selectedProjectId && !flatNodes.length ? (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography color="text.secondary">No model entries were returned for the selected project and branch.</Typography>
        </Paper>
      ) : null}
    </Stack>
  );

  const renderModels = () => (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
        <Box>
          <Typography variant="h5">Model Browser</Typography>
          <Typography variant="body2" color="text.secondary">
            {selectedProject
              ? `${selectedProject.name} / ${branchLabel(selectedProjectBranches, selectedBranchId)}`
              : "Select a project to inspect its published branch tree and properties."}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          <Button
            variant="outlined"
            startIcon={<RefreshRoundedIcon />}
            onClick={() => refreshSelectedProjectMutation.mutate()}
            disabled={!selectedProjectId || refreshSelectedProjectMutation.isPending}
          >
            Reload Cached Project
          </Button>
          <Button
            variant="contained"
            disabled={!selectedItemId}
            onClick={() => setTab("details")}
          >
            Open Full Details
          </Button>
        </Stack>
      </Stack>
      {!selectedProject ? (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a project</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Choose a published project snapshot from the selector on the left to inspect the full branch model tree.
          </Typography>
        </Paper>
      ) : null}
      {selectedProject && !selectedBranchId && !branchesQuery.isLoading ? (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a branch</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Model Browser follows one published branch snapshot at a time so we can keep the full tree and properties coherent.
          </Typography>
        </Paper>
      ) : null}
      {branchesQuery.isLoading && selectedProjectId ? <CircularProgress size={28} /> : null}
      {branchesQuery.error ? <Alert severity="error">{errorMessage(branchesQuery.error)}</Alert> : null}
      {treeQuery.isLoading ? <CircularProgress size={28} /> : null}
      {treeQuery.error ? <Alert severity="error">{errorMessage(treeQuery.error)}</Alert> : null}
      {selectedProject && selectedBranchId ? (
        <Grid container spacing={2}>
          <Grid item xs={12} lg={5}>
            <Paper sx={{ p: 3, borderRadius: 2, height: "100%" }}>
              <Stack spacing={2}>
                <Typography variant="h6">Containment Tree</Typography>
                <Typography variant="body2" color="text.secondary">
                  Walk the published branch snapshot the same way you would browse the containment tree in Cameo. Expand packages and elements on the left, then inspect the selected node on the right.
                </Typography>
                {selectedContainmentSegments.length ? (
                  <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                    <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
                      {selectedContainmentSegments.map((segment, index) => (
                        <Chip
                          key={`${segment}-${index}`}
                          label={segment}
                          size="small"
                          variant={index === selectedContainmentSegments.length - 1 ? "filled" : "outlined"}
                        />
                      ))}
                    </Stack>
                  </Paper>
                ) : null}
                {treeNodes.length ? (
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, maxHeight: 860, overflow: "auto" }}>
                    <ProjectTree
                      nodes={treeNodes}
                      selectedId={selectedItemId}
                      filter={treeFilter}
                      onSelect={(node) => selectContainmentNode(node, "models")}
                      onExpand={loadTreeChildren}
                      loadingIds={loadingTreeNodeIds}
                    />
                  </Paper>
                ) : (
                  <Typography color="text.secondary">No model tree is available for the selected branch snapshot yet.</Typography>
                )}
              </Stack>
            </Paper>
          </Grid>
          <Grid item xs={12} lg={7}>
            {selectedWorkspaceItem ? (
              <Paper sx={{ p: 3, borderRadius: 2 }}>
                <Stack spacing={2}>
                  {(() => {
                    const quickIdentity = identityRows(selectedWorkspaceItem, referenceNameById);
                    const quickOverview = overviewRows(selectedWorkspaceItem, referenceNameById);
                    const quickAttributes = mapToInspectorRows(payloadAttributes(selectedWorkspaceItem), referenceNameById);
                    const quickMetadata = mapToInspectorRows(selectedWorkspaceItem.metadata, referenceNameById);
                    const quickReferences = mapToInspectorRows(payloadReferences(selectedWorkspaceItem), referenceNameById);
                    return (
                      <>
                  <Stack spacing={0.75}>
                    <Typography variant="h6">{selectedWorkspaceItemName}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {selectedWorkspaceItemPath || `${selectedProject.name} / ${branchLabel(selectedProjectBranches, selectedBranchId)}`}
                    </Typography>
                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                      <Chip label={humanizeFieldLabel(selectedWorkspaceItem.item_type)} />
                      <Chip label={`Branch ${branchLabel(selectedProjectBranches, selectedBranchId)}`} variant="outlined" />
                      {selectedWorkspaceItem.editable && canEdit ? <Chip label="Editable" color="success" variant="outlined" /> : null}
                    </Stack>
                  </Stack>
                  <Grid container spacing={2}>
                    <Grid item xs={12} md={6}>
                      <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, height: "100%" }}>
                        <Stack spacing={1}>
                          <Typography variant="subtitle2">Identity</Typography>
                          {renderInspectorRows(quickIdentity, "No identifying fields were published for this item.")}
                        </Stack>
                      </Paper>
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, height: "100%" }}>
                        <Stack spacing={1}>
                          <Typography variant="subtitle2">Overview</Typography>
                          {renderInspectorRows(quickOverview, "No overview fields were published for this item.")}
                        </Stack>
                      </Paper>
                    </Grid>
                    <Grid item xs={12}>
                      <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                        <Stack spacing={1}>
                          <Typography variant="subtitle2">Properties</Typography>
                          {renderInspectorRows(
                            quickAttributes.length ? quickAttributes : quickMetadata,
                            "No presentable properties were published for this item.",
                          )}
                        </Stack>
                      </Paper>
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, height: "100%" }}>
                        <Stack spacing={1}>
                          <Typography variant="subtitle2">Containment</Typography>
                          {renderReferenceList(
                            selectedWorkspaceItem.contained_elements,
                            "No contained elements were published for this item.",
                          )}
                        </Stack>
                      </Paper>
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, height: "100%" }}>
                        <Stack spacing={1}>
                          <Typography variant="subtitle2">Relationships</Typography>
                          {renderReferenceList(
                            [...selectedWorkspaceItem.type_references, ...selectedWorkspaceItem.related_items],
                            "No related model references were published for this item.",
                          )}
                        </Stack>
                      </Paper>
                    </Grid>
                    {quickReferences.length ? (
                      <Grid item xs={12}>
                        <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                          <Stack spacing={1}>
                            <Typography variant="subtitle2">Reference Buckets</Typography>
                            {renderInspectorRows(quickReferences, "No reference buckets were published for this item.")}
                          </Stack>
                        </Paper>
                      </Grid>
                    ) : null}
                  </Grid>
                  <Stack direction="row" spacing={1}>
                    <Button size="small" variant="contained" onClick={() => setTab("details")}>
                      Open Full Details
                    </Button>
                    <Button size="small" onClick={() => pickCompareSide("left", selectedWorkspaceItem.id)}>
                      Compare Left
                    </Button>
                    <Button size="small" onClick={() => pickCompareSide("right", selectedWorkspaceItem.id)}>
                      Compare Right
                    </Button>
                  </Stack>
                      </>
                    );
                  })()}
                </Stack>
              </Paper>
            ) : (
              <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
                <Typography variant="h6">Select a model item</Typography>
                <Typography color="text.secondary" sx={{ mt: 1 }}>
                  Pick any node from the published branch tree to inspect its properties here without leaving Model Browser.
                </Typography>
              </Paper>
            )}
          </Grid>
        </Grid>
      ) : null}
    </Stack>
  );

  const renderElementTesting = () => {
    const elementDiscoveryLoading = elementDiscoveryQuery.isLoading || refreshElementDiscoveryMutation.isPending;
    const elementDiscoveryLoadingMessage = elementDiscovery
      ? "Reloading the cached branch snapshot and rechecking your permissions."
      : "Loading the first published branch snapshot from Workbench.";

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
            This tab works against the cached branch model published into Workbench for one branch at a time.
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
              Discover reachable elements for {selectedProject?.name ?? "the selected project"} / {branchLabel(selectedProjectBranches, selectedBranchId)} from the cached plugin-backed branch model already published into Workbench.
            </Typography>
          </Box>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              onClick={() => refreshBranchAccessManifestMutation.mutate()}
              disabled={!csrfToken || !selectedProjectId || !selectedBranchId || refreshBranchAccessManifestMutation.isPending}
            >
              Refresh Shared Access Map
            </Button>
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              onClick={() => refreshElementDiscoveryMutation.mutate()}
              disabled={!selectedProjectId || !selectedBranchId || refreshElementDiscoveryMutation.isPending}
            >
              Reload Cached Elements
            </Button>
          </Stack>
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
                  {branchAccessManifestStatus ? (
                    <>
                      <Chip label={`${branchAccessManifestStatus.accessible_user_count} viewers`} variant="outlined" />
                      <Chip label={`${branchAccessManifestStatus.editable_user_count} editors`} variant="outlined" />
                      <Chip label={`${branchAccessManifestStatus.admin_user_count} admins`} variant="outlined" />
                    </>
                  ) : null}
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  This run stays inside the Swagger contract: seed roots come from the selected branch models, each discovered element is fetched through the branch element endpoint, and the branch-level element POST is now reserved for smaller gap-fill batches of up to {elementDiscovery.batch_size} elements when traversal payloads are missing.
                </Typography>
                {branchAccessManifestQuery.error ? <Alert severity="error">{errorMessage(branchAccessManifestQuery.error)}</Alert> : null}
                {branchAccessManifestStatus?.message ? (
                  <Alert severity={branchAccessManifestStatus.accessible_user_count ? "info" : "warning"}>
                    {branchAccessManifestStatus.message}
                    {branchAccessManifestStatus.updated_at
                      ? ` Last refreshed ${new Date(branchAccessManifestStatus.updated_at).toLocaleString()}.`
                      : ""}
                  </Alert>
                ) : null}
                {refreshBranchAccessManifestMutation.isPending ? (
                  <Alert severity="info">Refreshing the shared access map from Teamwork Cloud permissions.</Alert>
                ) : null}
                {elementDiscovery.warnings.map((warning) => (
                  <Alert severity="warning" key={warning}>
                    {warning}
                  </Alert>
                ))}
              </Stack>
            </Paper>
            <Paper sx={{ p: 3, borderRadius: 2 }}>
              <Stack spacing={2}>
                <Typography variant="h6">Published Model Tree</Typography>
                <Typography variant="body2" color="text.secondary">
                  Browse the cached snapshot as a real model tree. Selecting any node opens its cached item details in Workbench.
                </Typography>
                {treeNodes.length ? (
                  <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, maxHeight: 720, overflow: "auto" }}>
                    <ProjectTree
                      nodes={treeNodes}
                      selectedId={selectedItemId}
                      filter=""
                      onSelect={(node) => selectContainmentNode(node, "elements")}
                      onExpand={loadTreeChildren}
                      loadingIds={loadingTreeNodeIds}
                    />
                  </Paper>
                ) : (
                  <Typography color="text.secondary">No published model tree is available for this branch yet.</Typography>
                )}
                <Divider />
                <Typography variant="h6">Element Index</Typography>
                {elementDiscovery.entries.length ? (
                  <List dense disablePadding sx={{ maxHeight: 420, overflow: "auto" }}>
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
                  <Typography color="text.secondary">No element index entries are available for this branch.</Typography>
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
            Use the model tree or Model Browser to open details from the cached branch model already published into Workbench.
          </Typography>
        </Paper>
      );
    }

    if (itemQuery.isLoading || !itemDraft) {
      return <CircularProgress size={28} />;
    }

    const sourcePayload = itemDraft.source_payload ?? {};
    const attributeRows = mapToInspectorRows(payloadAttributes(itemDraft), referenceNameById);
    const metadataRows = mapToInspectorRows(itemDraft.metadata, referenceNameById);
    const referenceRows = mapToInspectorRows(payloadReferences(itemDraft), referenceNameById);
    const extraSections = payloadExtraSections(itemDraft);
    const identitySectionRows = identityRows(itemDraft, referenceNameById);
    const overviewSectionRows = overviewRows(itemDraft, referenceNameById);

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
                <TextField label="Path" value={friendlyPath(itemDraft.path, referenceNameById)} disabled fullWidth />
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
                <Accordion defaultExpanded disableGutters>
                  <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                    <Typography variant="subtitle2">Overview</Typography>
                  </AccordionSummary>
                  <AccordionDetails>{renderInspectorRows(overviewSectionRows, "No overview fields were published for this item.")}</AccordionDetails>
                </Accordion>
                {hasMeaningfulValue(itemDraft.documentation_markdown) ? (
                  <Accordion defaultExpanded disableGutters>
                    <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                      <Typography variant="subtitle2">Documentation</Typography>
                    </AccordionSummary>
                    <AccordionDetails>
                      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                        {itemDraft.documentation_markdown}
                      </Typography>
                    </AccordionDetails>
                  </Accordion>
                ) : null}
                <Accordion defaultExpanded disableGutters>
                  <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                    <Typography variant="subtitle2">Identity and Placement</Typography>
                  </AccordionSummary>
                  <AccordionDetails>{renderInspectorRows(identitySectionRows, "No identifying fields were published for this item.")}</AccordionDetails>
                </Accordion>
                <Accordion defaultExpanded disableGutters>
                  <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                    <Typography variant="subtitle2">Element Properties</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    {renderInspectorRows(
                      attributeRows.length ? attributeRows : metadataRows,
                      "No structured properties were published for this item.",
                    )}
                  </AccordionDetails>
                </Accordion>
                {referenceRows.length ? (
                  <Accordion disableGutters>
                    <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                      <Typography variant="subtitle2">Reference Map</Typography>
                    </AccordionSummary>
                    <AccordionDetails>{renderInspectorRows(referenceRows, "No reference map was published for this item.")}</AccordionDetails>
                  </Accordion>
                ) : null}
                {extraSections.map(([key, value]) => (
                  <Accordion key={key} disableGutters>
                    <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                      <Typography variant="subtitle2">{humanizeFieldLabel(key)}</Typography>
                    </AccordionSummary>
                    <AccordionDetails>
                      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                        {humanReadableValue(value, referenceNameById)}
                      </Typography>
                    </AccordionDetails>
                  </Accordion>
                ))}
                <Accordion disableGutters>
                  <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                    <Typography variant="subtitle2">Full Source Payload</Typography>
                  </AccordionSummary>
                  <AccordionDetails>
                    <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", fontFamily: "monospace" }}>
                      {humanReadableValue(sourcePayload, referenceNameById)}
                    </Typography>
                  </AccordionDetails>
                </Accordion>
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
                {renderInspectorRows(
                  attributeRows.length ? attributeRows : metadataRows,
                  "No presentable properties were published for this item.",
                )}
                <Divider />
                <Typography variant="h6">Contained Elements</Typography>
                {renderReferenceList(itemDraft.contained_elements, "No contained elements were returned for this item.")}
                <Divider />
                <Typography variant="h6">Related Elements</Typography>
                {itemDraft.related_items.length ? (
                  renderReferenceList(itemDraft.related_items, "No related elements were returned for this item.")
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

  const renderCacheApiKeys = () => (
    <Paper sx={{ p: 3, borderRadius: 2 }}>
      <Stack spacing={2}>
        <Box>
          <Typography variant="h5">API Access Keys</Typography>
          <Typography variant="body2" color="text.secondary">
            Create bearer keys for scripts, AI tools, and integrations that need to work with Workbench data as you. The model data stays shared in one cache copy per branch, while Workbench keeps a separate per-user permission overlay so visibility still follows your TWC access.
          </Typography>
        </Box>
        {cacheApiKeysQuery.isLoading ? <CircularProgress size={28} /> : null}
        {cacheApiKeysQuery.error ? <Alert severity="error">{errorMessage(cacheApiKeysQuery.error)}</Alert> : null}
        <Alert severity="info">
          Use these keys with <code>Authorization: Bearer &lt;key&gt;</code>. Start with <code>GET /api/cache</code> or <code>GET /api/cache/servers</code>, then drill into the project, branch, model, and element routes.
        </Alert>
        <Typography variant="caption" color="text.secondary">
          These keys read the Workbench cache, not live TWC directly. Open a project branch in Workbench first so its cached data and your per-user visibility snapshot are available for scripts and AI tools.
        </Typography>
        <TextField
          label="New API key label"
          value={newCacheApiKeyLabel}
          onChange={(event) => setNewCacheApiKeyLabel(event.target.value)}
          helperText="Example: Local Python extractor, Langflow reader, AI notebook, or nightly report."
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} useFlexGap flexWrap="wrap">
          <FormControlLabel
            control={<Checkbox checked={newCacheApiKeyScopes.includes("read")} onChange={(event) => toggleNewCacheApiKeyScope("read", event.target.checked)} />}
            label="Read"
          />
          <FormControlLabel
            control={<Checkbox checked={newCacheApiKeyScopes.includes("write")} onChange={(event) => toggleNewCacheApiKeyScope("write", event.target.checked)} />}
            label="Write"
          />
          <FormControlLabel
            control={<Checkbox checked={newCacheApiKeyScopes.includes("edit")} onChange={(event) => toggleNewCacheApiKeyScope("edit", event.target.checked)} />}
            label="Edit"
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
          <Button
            variant="contained"
            disabled={!csrfToken || !newCacheApiKeyLabel.trim() || !newCacheApiKeyScopes.length || createCacheApiKeyMutation.isPending}
            onClick={() => createCacheApiKeyMutation.mutate()}
          >
            Create API Key
          </Button>
          <Button
            variant="outlined"
            startIcon={<RefreshRoundedIcon />}
            onClick={() => queryClient.invalidateQueries({ queryKey: ["workspace-cache-api-keys", ...sessionCacheKey] })}
          >
            Refresh Keys
          </Button>
          {createCacheApiKeyMutation.isPending || deleteCacheApiKeyMutation.isPending ? <CircularProgress size={24} /> : null}
        </Stack>
        {revealedCacheApiKey ? (
          <>
            <Alert severity="success">
              Copy this API key now. Workbench stores only a secure hash and will not reveal the full value again after you leave this screen.
            </Alert>
            <TextField label="New cache API key" value={revealedCacheApiKey} fullWidth InputProps={{ readOnly: true }} />
          </>
        ) : null}
        <TextField
          label="Quick start example"
          value={'curl -H "Authorization: Bearer <your-key>" https://your-workbench-host/api/cache/servers'}
          fullWidth
          multiline
          minRows={2}
          InputProps={{ readOnly: true }}
        />
        <Stack spacing={1.5}>
          {cacheApiKeys.length ? (
            cacheApiKeys.map((key: CacheApiKeySummary) => (
              <Paper key={key.key_id} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
                  <Box>
                    <Typography variant="subtitle2">{key.label}</Typography>
                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                      <Chip label={key.token_hint} variant="outlined" size="small" />
                      {key.scopes.map((scope) => (
                        <Chip key={`${key.key_id}-${scope}`} label={scope} variant="outlined" size="small" />
                      ))}
                      <Chip label={`Created ${new Date(key.created_at).toLocaleString()}`} variant="outlined" size="small" />
                      <Chip
                        label={key.last_used_at ? `Last used ${new Date(key.last_used_at).toLocaleString()}` : "Never used"}
                        color={key.last_used_at ? "success" : "default"}
                        variant="outlined"
                        size="small"
                      />
                    </Stack>
                  </Box>
                  <Button
                    variant="text"
                    color="warning"
                    disabled={!csrfToken || deleteCacheApiKeyMutation.isPending}
                    onClick={() => deleteCacheApiKeyMutation.mutate(key.key_id)}
                  >
                    Delete Key
                  </Button>
                </Stack>
              </Paper>
            ))
          ) : (
            <Typography color="text.secondary">No API keys created yet.</Typography>
          )}
        </Stack>
      </Stack>
    </Paper>
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
              <TextField
                label="Save exact plugin ingest token"
                type="password"
                value={manualCacheIngestToken}
                onChange={(event) => setManualCacheIngestToken(event.target.value)}
                helperText="Use this when the Cameo plugin should start with a known token instead of a randomly generated one."
                fullWidth
              />
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
                <Button
                  variant="outlined"
                  disabled={!csrfToken || !manualCacheIngestToken.trim() || storeCacheIngestTokenMutation.isPending}
                  onClick={() => storeCacheIngestTokenMutation.mutate()}
                >
                  Save Exact Token
                </Button>
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
                {storeCacheIngestTokenMutation.isPending || rotateCacheIngestTokenMutation.isPending || clearCacheIngestTokenMutation.isPending ? <CircularProgress size={24} /> : null}
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

  const renderDeveloperApi = () => (
    <Stack spacing={2}>
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Typography variant="h5">Developer API</Typography>
          <Typography variant="body2" color="text.secondary">
            Workbench exposes a cache-first API for scripts, notebooks, AI agents, and integration services. Use a personal API key from this page or from Settings, then call the cache manifest first to discover the available route set.
          </Typography>
          <Alert severity="info">
            Plugin-backed branches are the preferred source for designated cache targets. For those branches, Workbench serves the shared cached model data and checks your per-user TWC visibility overlay instead of duplicating the model itself per user.
          </Alert>
          <Typography variant="caption" color="text.secondary">
            API keys are labeled and tracked with last-used timestamps so you can tell which automation key is still alive before rotating or deleting it.
          </Typography>
          <TextField
            label="Read example"
            value={'curl -H "Authorization: Bearer <your-key>" https://your-workbench-host/api/cache'}
            fullWidth
            multiline
            minRows={2}
            InputProps={{ readOnly: true }}
          />
          <TextField
            label="Edit example"
            value={'curl -X PATCH -H "Authorization: Bearer <your-key>" -H "Content-Type: application/json" https://your-workbench-host/api/cache/servers/<server_id>/projects/<project_id>/branches/<branch_id>/elements/<element_id> -d "{\"documentation\":\"Updated from automation\"}"'}
            fullWidth
            multiline
            minRows={3}
            InputProps={{ readOnly: true }}
          />
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip label="read -> cache reads" />
            <Chip label="write -> cache ingest" variant="outlined" />
            <Chip label="edit -> plugin-backed cache edits" variant="outlined" />
          </Stack>
        </Stack>
      </Paper>
      {renderCacheApiKeys()}
    </Stack>
  );

  const renderSettingsExtras = () => (
    <Stack spacing={2}>
      {renderCacheApiKeys()}
      {isAdmin ? renderAdminSettings() : null}
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
                  {selectedContainmentSegments.length ? (
                    <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
                      {selectedContainmentSegments.map((segment, index) => (
                        <Chip
                          key={`${segment}-${index}`}
                          label={segment}
                          size="small"
                          variant={index === selectedContainmentSegments.length - 1 ? "filled" : "outlined"}
                        />
                      ))}
                    </Stack>
                  ) : null}
                </Stack>
              </Paper>
            ) : null}
            <Divider />
            <ProjectTree
              nodes={treeNodes}
              selectedId={selectedItemId}
              filter={treeFilter}
              onSelect={(node) => selectContainmentNode(node, "models")}
              onExpand={loadTreeChildren}
              loadingIds={loadingTreeNodeIds}
            />
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
              <Tab label="Developer API" value="developer" />
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
            {tab === "developer" ? renderDeveloperApi() : null}
            {tab === "api" ? renderApiExplorer() : null}
          </Box>
        </Stack>
      </Box>
      <SettingsDialog
        open={settingsOpen}
        preferences={session?.preferences ?? { theme_mode: "system", font_scale: 1, request_timeout_seconds: 30, live_log_poll_interval_ms: 2500, presentation_font_scale: 1.2 }}
        saving={settingsMutation.isPending}
        extraContent={renderSettingsExtras()}
        onClose={() => {
          setSettingsOpen(false);
          setRevealedCacheIngestToken("");
          setRevealedCacheApiKey("");
        }}
        onSave={async (preferences) => {
          await settingsMutation.mutateAsync(preferences);
        }}
      />
    </Box>
  );
}
