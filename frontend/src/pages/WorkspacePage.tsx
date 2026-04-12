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

type WorkspaceTab = "dashboard" | "projects" | "models" | "details" | "compare" | "oslc" | "api";

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

function branchLabel(project: ProjectSummary | null, branchId: string): string {
  return project?.branches.find((branch) => branch.id === branchId)?.name ?? branchId;
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

  const [tab, setTab] = useState<WorkspaceTab>("dashboard");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [selectedBranchId, setSelectedBranchId] = useState("");
  const [treeFilter, setTreeFilter] = useState("");
  const [selectedItemId, setSelectedItemId] = useState("");
  const [itemDraft, setItemDraft] = useState<ItemDetails | null>(null);
  const [compareLeft, setCompareLeft] = useState("");
  const [compareRight, setCompareRight] = useState("");
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
  const [notice, setNotice] = useState<{ severity: "success" | "error"; message: string } | null>(null);

  const dashboardQuery = useQuery({
    queryKey: ["workspace-dashboard"],
    queryFn: api.getDashboard,
  });

  const projectsQuery = useQuery({
    queryKey: ["workspace-projects"],
    queryFn: api.getProjects,
  });

  const contractQuery = useQuery({
    queryKey: ["workspace-contract"],
    queryFn: api.getContractManifest,
  });

  const oslcStatusQuery = useQuery({
    queryKey: ["workspace-oslc-status", session?.server?.id],
    queryFn: api.getOslcStatus,
    enabled: Boolean(session?.server?.id),
  });

  const projects = projectsQuery.data ?? dashboardQuery.data?.projects ?? [];
  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );

  useEffect(() => {
    if (!selectedProjectId && projects.length) {
      setSelectedProjectId(projects[0].id);
    }
  }, [projects, selectedProjectId]);

  useEffect(() => {
    if (!selectedProject) {
      return;
    }
    if (!selectedProject.branches.length) {
      setSelectedBranchId("");
      return;
    }
    if (!selectedProject.branches.some((branch) => branch.id === selectedBranchId)) {
      setSelectedBranchId(selectedProject.branches[0].id);
    }
  }, [selectedBranchId, selectedProject]);

  const treeQuery = useQuery({
    queryKey: ["workspace-tree", selectedProjectId, selectedBranchId],
    queryFn: () => api.getTree(selectedProjectId || undefined, selectedBranchId || undefined),
    enabled: Boolean(selectedProjectId),
  });

  const treeNodes = treeQuery.data ?? [];
  const flatNodes = useMemo(() => flattenTree(treeNodes), [treeNodes]);
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

  useEffect(() => {
    if (oslcConsumerName) {
      return;
    }
    const serverId = session?.server?.id ?? "server";
    setOslcConsumerName(`twcworkbench-${serverId}`);
  }, [oslcConsumerName, session?.server?.id]);

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
      void queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status"] });
    } else if (authError) {
      setNotice({ severity: "error", message: authError });
    }

    const nextParams = new URLSearchParams(searchParams);
    nextParams.delete("oslcAuth");
    nextParams.delete("oslcAuthError");
    setSearchParams(nextParams, { replace: true });
  }, [queryClient, searchParams, setSearchParams]);

  const itemQuery = useQuery({
    queryKey: ["workspace-item", selectedItemId, selectedProjectId, selectedBranchId],
    queryFn: () => api.getItem(selectedItemId, selectedProjectId || undefined, selectedBranchId || undefined),
    enabled: Boolean(selectedItemId),
  });

  useEffect(() => {
    setItemDraft(itemQuery.data ?? null);
  }, [itemQuery.data]);

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
      await queryClient.invalidateQueries({ queryKey: ["workspace-item"] });
      await queryClient.invalidateQueries({ queryKey: ["workspace-tree"] });
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

  const disconnectOslcMutation = useMutation({
    mutationFn: () => api.disconnectOslc(csrfToken),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status"] });
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
          remember_for_session: true,
        },
        csrfToken,
      ),
    onSuccess: async (result) => {
      setOslcManualKey(result.consumer_key);
      setOslcConsumerSecret("");
      await queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status"] });
      setNotice({ severity: "success", message: result.message });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const storeOslcConsumerMutation = useMutation({
    mutationFn: () =>
      api.storeOslcConsumer(
        {
          consumer_key: oslcManualKey.trim(),
          consumer_secret: oslcManualSecret,
        },
        csrfToken,
      ),
    onSuccess: async (result) => {
      setOslcManualSecret("");
      await queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status"] });
      setNotice({ severity: "success", message: result.message || "OSLC consumer credentials were stored for this app session." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const clearOslcConsumerMutation = useMutation({
    mutationFn: () => api.clearOslcConsumer(csrfToken),
    onSuccess: async () => {
      setOslcManualKey("");
      setOslcManualSecret("");
      await queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status"] });
      setNotice({ severity: "success", message: "Session-scoped OSLC consumer credentials were cleared." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const handleTabChange = (_event: SyntheticEvent, nextTab: WorkspaceTab) => {
    setTab(nextTab);
  };

  const selectProject = (projectId: string) => {
    setSelectedProjectId(projectId);
    setSelectedItemId("");
    setItemDraft(null);
  };

  const openNode = (node: TreeNode) => {
    setSelectedItemId(node.id);
    setTab("details");
  };

  const pickCompareSide = (side: "left" | "right", itemId: string) => {
    if (side === "left") {
      setCompareLeft(itemId);
    } else {
      setCompareRight(itemId);
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
                Branches
              </Typography>
              <Typography variant="h3">{projects.reduce((count, project) => count + project.branches.length, 0)}</Typography>
              <Typography color="text.secondary">Branch records loaded through the repository API.</Typography>
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
            This workspace exposes only Teamwork Cloud operations present in RealSwagger.json. The curated tabs cover the common repository and model flows; API Explorer exposes the complete contract surface for advanced workflows.
          </Typography>
          <Typography color="text.secondary">
            Simulation, collaborator workspaces, global model search, publishing, export jobs, job center, saved searches, bookmarks, comments, documents, and collaborator-style attachments are not shown because this Swagger file does not define those APIs. Swagger artifact upload and download operations are available in API Explorer.
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
          {dashboardQuery.data?.capability_badges.length ? <CapabilityBadges capabilities={dashboardQuery.data.capability_badges} /> : null}
        </Stack>
      </Paper>
    </Stack>
  );

  const renderProjects = () => (
    <Stack spacing={2}>
      <Typography variant="h5">Project Browser</Typography>
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
                      {project.description || project.id}
                    </Typography>
                  </Stack>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label={`Resource ${project.resource_id ?? project.id}`} variant="outlined" />
                    {project.workspace_id ? <Chip label={`Workspace ${project.workspace_id}`} variant="outlined" /> : null}
                    <Chip label={`${project.branches.length} branches`} />
                  </Stack>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    {project.branches.map((branch) => (
                      <Chip key={branch.id} label={branch.name} variant={selectedBranchId === branch.id && selectedProjectId === project.id ? "filled" : "outlined"} />
                    ))}
                  </Stack>
                  <Button variant="contained" onClick={() => selectProject(project.id)}>
                    Open Project
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
            {selectedProject ? `${selectedProject.name} / ${branchLabel(selectedProject, selectedBranchId)}` : "Select a project to load models."}
          </Typography>
        </Box>
        <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => queryClient.invalidateQueries({ queryKey: ["workspace-tree"] })} disabled={!selectedProjectId}>
          Refresh Models
        </Button>
      </Stack>
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
                      {node.path}
                    </Typography>
                  </Box>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label={node.node_type} size="small" />
                    {Object.entries(node.metadata).slice(0, 3).map(([key, value]) => (
                      <Chip key={key} label={`${key}: ${valueText(value)}`} size="small" variant="outlined" />
                    ))}
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
            <Typography variant="h5">Item Details</Typography>
            <Typography variant="body2" color="text.secondary">
              {selectedItem?.path ?? selectedItemId}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1}>
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
              </Stack>
            </Paper>
          </Grid>
          <Grid item xs={12} md={5}>
            <Paper sx={{ p: 3, borderRadius: 2 }}>
              <Stack spacing={2}>
                <Typography variant="h6">Metadata</Typography>
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                  <Chip label={itemDraft.item_type} />
                  <Chip label={`Version ${itemDraft.version}`} variant="outlined" />
                  <Chip label={`Project ${itemDraft.project_id}`} variant="outlined" />
                  <Chip label={`Branch ${itemDraft.branch_id}`} variant="outlined" />
                </Stack>
                <Divider />
                {Object.entries(itemDraft.metadata).length ? (
                  <List dense disablePadding>
                    {Object.entries(itemDraft.metadata).map(([key, value]) => (
                      <ListItemButton key={key} dense>
                        <ListItemText primary={key} secondary={valueText(value)} />
                      </ListItemButton>
                    ))}
                  </List>
                ) : (
                  <Typography color="text.secondary">No metadata returned for this item.</Typography>
                )}
                <Divider />
                <Typography variant="h6">Relationships</Typography>
                {itemDraft.relationships.length ? (
                  <List dense disablePadding>
                    {itemDraft.relationships.map((relationship, index) => (
                      <ListItemButton key={`${relationship.type ?? "relationship"}-${index}`} dense>
                        <ListItemText primary={valueText(relationship.type ?? `Relationship ${index + 1}`)} secondary={valueText(relationship)} />
                      </ListItemButton>
                    ))}
                  </List>
                ) : (
                  <Typography color="text.secondary">No relationships returned for this item.</Typography>
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
        Compare element/model IDs in the current project context. Numeric left and right IDs on the same project use the RealSwagger revision diff endpoint.
      </Typography>
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Grid container spacing={2}>
          <Grid item xs={12} md={5}>
            <TextField label="Left ID or revision" value={compareLeft} onChange={(event) => setCompareLeft(event.target.value)} fullWidth />
          </Grid>
          <Grid item xs={12} md={5}>
            <TextField label="Right ID or revision" value={compareRight} onChange={(event) => setCompareRight(event.target.value)} fullWidth />
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
      {compareMutation.isPending ? <CircularProgress size={28} /> : null}
      {compareMutation.data ? (
        <Paper sx={{ p: 3, borderRadius: 2 }}>
          <Stack spacing={2}>
            <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
              <Typography variant="h6">{compareMutation.data.summary}</Typography>
              <Chip label={compareMutation.data.compare_type} />
              <Chip label={`${compareMutation.data.differences.length} differences`} variant="outlined" />
            </Stack>
            <List disablePadding>
              {compareMutation.data.differences.map((difference) => (
                <ListItemButton key={difference.field_path} alignItems="flex-start">
                  <ListItemText
                    primary={difference.field_path}
                    secondary={
                      <Box component="span" sx={{ display: "block", mt: 1 }}>
                        <Typography component="span" variant="body2" sx={{ display: "block" }}>
                          {difference.summary}
                        </Typography>
                        <Typography component="pre" variant="caption" sx={{ display: "block", whiteSpace: "pre-wrap", mt: 1, mb: 0 }}>
                          {`Left: ${valueText(difference.left_value)}\nRight: ${valueText(difference.right_value)}`}
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
        : oslcStatus?.consumer_key_source === "session"
          ? "Session consumer"
          : "No consumer";

    return (
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
          <Box>
            <Typography variant="h5">OSLC Explorer</Typography>
            <Typography variant="body2" color="text.secondary">
              OSLC is a separate connector from the RealSwagger `/osmc` API. This tab uses OSLC root services discovery and OAuth 1.0a consumer authorization.
            </Typography>
          </Box>
          <Stack direction="row" spacing={1}>
            <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => queryClient.invalidateQueries({ queryKey: ["workspace-oslc-status"] })}>
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
                  This server publishes an OSLC consumer registration endpoint. Generate a consumer below or paste an approved consumer key and secret for this app session.
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
              Teamwork Cloud OSLC uses OAuth 1.0a. You can either generate a consumer key through root services or paste an approved consumer key and secret for this app session.
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
                        ? "The returned key is stored for this app session, but it still needs admin approval in Magic Collaboration Studio Settings before OSLC sign-in will succeed."
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
                      Generate and Store for Session
                    </Button>
                    {generateOslcConsumerMutation.isPending ? <CircularProgress size={24} /> : null}
                  </Stack>
                </Stack>
              </Grid>
              <Grid item xs={12} md={6}>
                <Stack spacing={1.5}>
                  <Typography variant="body2" fontWeight={600}>
                    Use Approved Consumer for This Session
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
                    helperText="Use the key and secret created or approved in Teamwork Cloud Settings when you do not want to edit backend env config."
                    fullWidth
                  />
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
                    <Button
                      variant="outlined"
                      disabled={!csrfToken || !oslcManualKey.trim() || !oslcManualSecret || storeOslcConsumerMutation.isPending}
                      onClick={() => storeOslcConsumerMutation.mutate()}
                    >
                      Store for Session
                    </Button>
                    <Button
                      variant="text"
                      color="warning"
                      disabled={!csrfToken || oslcStatus?.consumer_key_source !== "session" || clearOslcConsumerMutation.isPending}
                      onClick={() => clearOslcConsumerMutation.mutate()}
                    >
                      Forget Session Consumer
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
                OSLC needs an approved consumer key and secret before authorization can start. Generate one from root services or store an approved pair for this app session.
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

  const renderApiExplorer = () => {
    const response = apiOperationMutation.data ?? null;
    return (
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
          <Box>
            <Typography variant="h5">API Explorer</Typography>
            <Typography variant="body2" color="text.secondary">
              Every action here is generated from RealSwagger.json and executed only through declared method/path/parameter combinations.
            </Typography>
          </Box>
          <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => queryClient.invalidateQueries({ queryKey: ["workspace-contract"] })}>
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
              disabled={!selectedProject?.branches.length}
            >
              {selectedProject?.branches.length ? (
                selectedProject.branches.map((branch) => (
                  <MenuItem key={branch.id} value={branch.id}>
                    {branch.name}
                  </MenuItem>
                ))
              ) : (
                <MenuItem value="">Default</MenuItem>
              )}
            </TextField>
            <TextField label="Filter model tree" value={treeFilter} onChange={(event) => setTreeFilter(event.target.value)} fullWidth />
            <Divider />
            <ProjectTree nodes={treeNodes} selectedId={selectedItemId} filter={treeFilter} onSelect={openNode} />
          </Stack>
        </Paper>
        <Stack spacing={2} component="main">
          {notice ? <Alert severity={notice.severity} onClose={() => setNotice(null)}>{notice.message}</Alert> : null}
          {dashboardQuery.error ? <Alert severity="error">{errorMessage(dashboardQuery.error)}</Alert> : null}
          {projectsQuery.error ? <Alert severity="error">{errorMessage(projectsQuery.error)}</Alert> : null}
          <Paper sx={{ borderRadius: 2 }}>
            <Tabs value={tab} onChange={handleTabChange} variant="scrollable" scrollButtons="auto">
              <Tab label="Dashboard" value="dashboard" />
              <Tab label="Project Browser" value="projects" />
              <Tab label="Model Browser" value="models" />
              <Tab label="Item Details" value="details" />
              <Tab label="Compare" value="compare" />
              <Tab label="OSLC Explorer" value="oslc" />
              <Tab label="API Explorer" value="api" />
            </Tabs>
          </Paper>
          <Box>
            {tab === "dashboard" ? renderDashboard() : null}
            {tab === "projects" ? renderProjects() : null}
            {tab === "models" ? renderModels() : null}
            {tab === "details" ? renderDetails() : null}
            {tab === "compare" ? renderCompare() : null}
            {tab === "oslc" ? renderOslc() : null}
            {tab === "api" ? renderApiExplorer() : null}
          </Box>
        </Stack>
      </Box>
      <SettingsDialog
        open={settingsOpen}
        preferences={session?.preferences ?? { theme_mode: "system", font_scale: 1, request_timeout_seconds: 30, live_log_poll_interval_ms: 2500, presentation_font_scale: 1.2 }}
        saving={settingsMutation.isPending}
        onClose={() => setSettingsOpen(false)}
        onSave={async (preferences) => {
          await settingsMutation.mutateAsync(preferences);
        }}
      />
    </Box>
  );
}
