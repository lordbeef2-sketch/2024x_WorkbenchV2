import { ChangeEvent, useDeferredValue, useEffect, useState, startTransition } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
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
  Chip,
  Dialog,
  Divider,
  FormControlLabel,
  IconButton,
  InputAdornment,
  LinearProgress,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Tab,
  Tabs,
  TextField,
  Toolbar,
  Tooltip,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/GridLegacy";
import ArrowBackRoundedIcon from "@mui/icons-material/ArrowBackRounded";
import ArrowForwardRoundedIcon from "@mui/icons-material/ArrowForwardRounded";
import AdminPanelSettingsRoundedIcon from "@mui/icons-material/AdminPanelSettingsRounded";
import BookmarkAddRoundedIcon from "@mui/icons-material/BookmarkAddRounded";
import CompareArrowsRoundedIcon from "@mui/icons-material/CompareArrowsRounded";
import DownloadRoundedIcon from "@mui/icons-material/DownloadRounded";
import EditRoundedIcon from "@mui/icons-material/EditRounded";
import ExpandMoreRoundedIcon from "@mui/icons-material/ExpandMoreRounded";
import FullscreenRoundedIcon from "@mui/icons-material/FullscreenRounded";
import LogoutRoundedIcon from "@mui/icons-material/LogoutRounded";
import PlayArrowRoundedIcon from "@mui/icons-material/PlayArrowRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import SaveRoundedIcon from "@mui/icons-material/SaveRounded";
import SearchRoundedIcon from "@mui/icons-material/SearchRounded";
import SettingsRoundedIcon from "@mui/icons-material/SettingsRounded";
import SwapHorizRoundedIcon from "@mui/icons-material/SwapHorizRounded";
import UploadRoundedIcon from "@mui/icons-material/UploadRounded";

import CapabilityBadges from "../components/CapabilityBadges";
import JobStrip from "../components/JobStrip";
import ProjectTree from "../components/ProjectTree";
import ServerPresetManagerDialog from "../components/ServerPresetManagerDialog";
import SettingsDialog from "../components/SettingsDialog";
import {
  AttachmentInfo,
  Bookmark,
  BranchSummary,
  CommentEntry,
  CompareDifference,
  ItemDetails,
  JobRecord,
  SessionPreferences,
  SimulationConfig,
  SimulationParameter,
  TreeNode,
} from "../models/api";
import { api } from "../services/api";
import { useSession } from "../state/SessionProvider";
import { capabilityColor, formatBytes, formatDate, jobStatusColor } from "../utils/format";

type WorkspaceTab =
  | "dashboard"
  | "projects"
  | "models"
  | "details"
  | "compare"
  | "simulation"
  | "collaborator"
  | "search"
  | "jobs";

const WORKSPACE_TABS: Array<{ value: WorkspaceTab; label: string }> = [
  { value: "dashboard", label: "Dashboard" },
  { value: "projects", label: "Project Browser" },
  { value: "models", label: "Model Browser" },
  { value: "details", label: "Item Details" },
  { value: "compare", label: "Compare" },
  { value: "simulation", label: "Simulation" },
  { value: "collaborator", label: "Collaborator Workspace" },
  { value: "search", label: "Search Results" },
  { value: "jobs", label: "Job Center" },
];

function flattenNodes(nodes: TreeNode[]): TreeNode[] {
  return nodes.flatMap((node) => [node, ...flattenNodes(node.children)]);
}

function prettyValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value, null, 2);
}

function notificationMessage(caught: unknown): string {
  return caught instanceof Error ? caught.message : "The request failed.";
}

function buildCompareRows(left: JobRecord | undefined, right: JobRecord | undefined): CompareDifference[] {
  const leftMetrics = (left?.result?.metrics as Record<string, unknown> | undefined) ?? {};
  const rightMetrics = (right?.result?.metrics as Record<string, unknown> | undefined) ?? {};
  const keys = Array.from(new Set([...Object.keys(leftMetrics), ...Object.keys(rightMetrics)])).sort();

  return keys
    .filter((key) => leftMetrics[key] !== rightMetrics[key])
    .map((key) => ({
      field_path: key,
      left_value: leftMetrics[key],
      right_value: rightMetrics[key],
      summary: `${key} changed`,
    }));
}

function MetricCard({ label, value, caption }: { label: string; value: string; caption: string }) {
  return (
    <Card sx={{ borderRadius: 5, height: "100%" }}>
      <CardContent>
        <Typography variant="overline" color="text.secondary">
          {label}
        </Typography>
        <Typography variant="h4" sx={{ mt: 0.5 }}>
          {value}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1.25 }}>
          {caption}
        </Typography>
      </CardContent>
    </Card>
  );
}

function ParameterField({
  parameter,
  value,
  onChange,
}: {
  parameter: SimulationParameter;
  value: string | number | boolean;
  onChange: (value: string | number | boolean) => void;
}) {
  if (parameter.kind === "choice") {
    return (
      <TextField
        select
        label={parameter.label}
        fullWidth
        value={String(value)}
        onChange={(event) => onChange(event.target.value)}
        helperText={parameter.description}
      >
        {parameter.options.map((option) => (
          <MenuItem key={option} value={option}>
            {option}
          </MenuItem>
        ))}
      </TextField>
    );
  }

  if (parameter.kind === "boolean") {
    return (
      <TextField
        select
        label={parameter.label}
        fullWidth
        value={String(value)}
        onChange={(event) => onChange(event.target.value === "true")}
        helperText={parameter.description}
      >
        <MenuItem value="true">True</MenuItem>
        <MenuItem value="false">False</MenuItem>
      </TextField>
    );
  }

  return (
    <TextField
      label={parameter.label}
      type={parameter.kind === "integer" || parameter.kind === "number" ? "number" : "text"}
      fullWidth
      value={String(value)}
      onChange={(event) => {
        if (parameter.kind === "integer") {
          onChange(Number.parseInt(event.target.value, 10) || 0);
          return;
        }
        if (parameter.kind === "number") {
          onChange(Number.parseFloat(event.target.value) || 0);
          return;
        }
        onChange(event.target.value);
      }}
      helperText={parameter.description}
    />
  );
}

export default function WorkspacePage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { refreshSession, session } = useSession();
  const [searchParams, setSearchParams] = useSearchParams();
  const [treeFilter, setTreeFilter] = useState("");
  const [searchDraft, setSearchDraft] = useState(searchParams.get("q") ?? "");
  const [itemMetadataDraft, setItemMetadataDraft] = useState("{}");
  const [itemDraft, setItemDraft] = useState<Partial<ItemDetails>>({});
  const [documentDraft, setDocumentDraft] = useState("");
  const [commentDraft, setCommentDraft] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [serverManagerOpen, setServerManagerOpen] = useState(false);
  const [presentationOpen, setPresentationOpen] = useState(false);
  const [branchDialogOpen, setBranchDialogOpen] = useState(false);
  const [documentEditMode, setDocumentEditMode] = useState(false);
  const [branchDraft, setBranchDraft] = useState<{ name: string; description: string }>({ name: "", description: "" });
  const [selectedSimulationConfigId, setSelectedSimulationConfigId] = useState("");
  const [simulationValues, setSimulationValues] = useState<Record<string, string | number | boolean>>({});
  const [publishForm, setPublishForm] = useState({
    scope: "full",
    template: "board-deck",
    category: "governance",
    republish: false,
    open_result: true,
  });
  const [simulationCompareLeftId, setSimulationCompareLeftId] = useState("");
  const [simulationCompareRightId, setSimulationCompareRightId] = useState("");
  const [banner, setBanner] = useState<{ severity: "success" | "error" | "info"; message: string } | null>(null);
  const deferredTreeFilter = useDeferredValue(treeFilter);

  const csrfToken = session?.csrf_token ?? "";
  const selectedTab = (searchParams.get("tab") as WorkspaceTab | null) ?? "dashboard";
  const selectedProjectId = searchParams.get("project") ?? undefined;
  const selectedBranchId = searchParams.get("branch") ?? undefined;
  const selectedItemId = searchParams.get("item") ?? undefined;
  const selectedDocumentId = searchParams.get("doc") ?? undefined;
  const compareLeftId = searchParams.get("compareLeft") ?? "";
  const compareRightId = searchParams.get("compareRight") ?? "";
  const searchQuery = searchParams.get("q") ?? "";

  const updateParams = (updates: Record<string, string | undefined>, replace = false) => {
    const next = new URLSearchParams(searchParams);
    Object.entries(updates).forEach(([key, value]) => {
      if (!value) {
        next.delete(key);
      } else {
        next.set(key, value);
      }
    });
    startTransition(() => setSearchParams(next, { replace }));
  };

  const capabilities = session?.capabilities?.capabilities ?? {};
  const canRunSimulation = capabilities.simulation?.state !== "not_available";
  const canPublish = capabilities.publish?.state !== "not_available";
  const canEditItems = capabilities.edit?.state !== "not_available";
  const canAttach = capabilities.attachment?.state !== "not_available";
  const canEditBranches = capabilities.branch_edit?.state === "ready";

  const dashboardQuery = useQuery({
    queryKey: ["dashboard"],
    queryFn: api.getDashboard,
  });

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: api.getProjects,
  });

  const treeQuery = useQuery({
    queryKey: ["tree", selectedProjectId, selectedBranchId],
    queryFn: () => api.getTree(selectedProjectId, selectedBranchId),
    enabled: Boolean(selectedProjectId),
  });

  const itemQuery = useQuery({
    queryKey: ["item", selectedProjectId, selectedBranchId, selectedItemId],
    queryFn: () => api.getItem(selectedItemId!, selectedProjectId, selectedBranchId),
    enabled: Boolean(selectedItemId),
  });

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: api.getDocuments,
  });

  const documentQuery = useQuery({
    queryKey: ["document", selectedDocumentId],
    queryFn: () => api.getDocument(selectedDocumentId!),
    enabled: Boolean(selectedDocumentId),
  });

  const attachmentsQuery = useQuery({
    queryKey: ["attachments", selectedDocumentId],
    queryFn: () => api.getAttachments(selectedDocumentId!),
    enabled: Boolean(selectedDocumentId),
  });

  const commentsQuery = useQuery({
    queryKey: ["comments", selectedDocumentId],
    queryFn: () => api.getComments(selectedDocumentId!),
    enabled: Boolean(selectedDocumentId),
  });

  const searchResultsQuery = useQuery({
    queryKey: ["search", searchQuery],
    queryFn: () => api.search(searchQuery),
    enabled: Boolean(searchQuery),
  });

  const compareQuery = useQuery({
    queryKey: ["compare", compareLeftId, compareRightId],
    queryFn: () => api.compare(compareLeftId, compareRightId),
    enabled: Boolean(compareLeftId && compareRightId),
  });

  const simulationConfigsQuery = useQuery({
    queryKey: ["simulation-configs", selectedProjectId],
    queryFn: () => api.getSimulationConfigurations(selectedProjectId),
    enabled: Boolean(selectedProjectId),
  });

  const simulationHistoryQuery = useQuery({
    queryKey: ["simulation-history"],
    queryFn: api.getSimulationHistory,
  });

  const jobsQuery = useQuery({
    queryKey: ["jobs"],
    queryFn: api.listJobs,
    refetchInterval: session?.preferences.live_log_poll_interval_ms ?? 2500,
  });

  const refreshCapabilityMutation = useMutation({
    mutationFn: () => api.refreshCapabilities(csrfToken),
    onSuccess: async () => {
      await refreshSession();
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setBanner({ severity: "success", message: "Capabilities refreshed." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const logoutMutation = useMutation({
    mutationFn: () => api.logout(csrfToken),
    onSuccess: async () => {
      queryClient.clear();
      await refreshSession();
      navigate("/", { replace: true });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const saveItemMutation = useMutation({
    mutationFn: async () => {
      if (!selectedItemId) {
        throw new Error("Select an item before saving.");
      }
      return api.updateItem(
        selectedItemId,
        {
          ...itemDraft,
          metadata: JSON.parse(itemMetadataDraft) as Record<string, string>,
        },
        csrfToken,
        selectedProjectId,
        selectedBranchId,
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["item", selectedProjectId, selectedBranchId, selectedItemId] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setBanner({ severity: "success", message: "Model item saved." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const updateDocumentMutation = useMutation({
    mutationFn: async () => {
      if (!selectedDocumentId) {
        throw new Error("Select a collaborator document before saving.");
      }
      return api.updateDocument(selectedDocumentId, documentDraft, csrfToken);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["document", selectedDocumentId] });
      await queryClient.invalidateQueries({ queryKey: ["documents"] });
      setBanner({ severity: "success", message: "Collaborator document saved." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const updateBranchMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProjectId || !selectedBranchId) {
        throw new Error("Select a project and branch before updating branch settings.");
      }
      return api.updateBranch(selectedProjectId, selectedBranchId, branchDraft, csrfToken);
    },
    onSuccess: async (branch: BranchSummary) => {
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setBranchDraft({ name: branch.name, description: branch.description });
      setBranchDialogOpen(false);
      setBanner({ severity: "success", message: "Branch metadata saved." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const runSimulationMutation = useMutation({
    mutationFn: async () => {
      const config = simulationConfigsQuery.data?.find((candidate) => candidate.id === selectedSimulationConfigId);
      if (!config || !selectedProjectId || !selectedBranchId) {
        throw new Error("Choose a simulation configuration, project, and branch.");
      }
      return api.runSimulation(
        {
          config_id: config.id,
          project_id: selectedProjectId,
          branch_id: selectedBranchId,
          parameters: simulationValues,
        },
        csrfToken,
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["simulation-history"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      updateParams({ tab: "jobs" });
      setBanner({ severity: "success", message: "Simulation job submitted." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const publishMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProjectId || !selectedBranchId) {
        throw new Error("Select a project and branch before publishing.");
      }
      return api.publish(
        {
          project_id: selectedProjectId,
          branch_id: selectedBranchId,
          scope: publishForm.scope,
          template: publishForm.template,
          category: publishForm.category,
          republish: publishForm.republish,
          open_result: publishForm.open_result,
          presets: {},
        },
        csrfToken,
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      updateParams({ tab: "jobs" });
      setBanner({ severity: "success", message: "Publish job submitted." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const exportMutation = useMutation({
    mutationFn: (payload: Parameters<typeof api.exportData>[0]) => api.exportData(payload, csrfToken),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      updateParams({ tab: "jobs" });
      setBanner({ severity: "success", message: "Export job submitted." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const uploadAttachmentMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!selectedDocumentId) {
        throw new Error("Select a document before uploading attachments.");
      }
      return api.uploadAttachment(selectedDocumentId, file, csrfToken);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["attachments", selectedDocumentId] });
      setBanner({ severity: "success", message: "Attachment uploaded." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const deleteAttachmentMutation = useMutation({
    mutationFn: async (attachmentId: string) => {
      if (!selectedDocumentId) {
        throw new Error("Select a document before deleting attachments.");
      }
      return api.deleteAttachment(selectedDocumentId, attachmentId, csrfToken);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["attachments", selectedDocumentId] });
      setBanner({ severity: "success", message: "Attachment removed." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const addCommentMutation = useMutation({
    mutationFn: async () => {
      if (!selectedDocumentId) {
        throw new Error("Select a document before adding comments.");
      }
      return api.addComment(selectedDocumentId, commentDraft, csrfToken);
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["comments", selectedDocumentId] });
      setCommentDraft("");
      setBanner({ severity: "success", message: "Comment added." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const saveSettingsMutation = useMutation({
    mutationFn: (preferences: SessionPreferences) => api.updatePreferences(preferences, csrfToken),
    onSuccess: async () => {
      await refreshSession();
      setBanner({ severity: "success", message: "Settings saved." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const saveBookmarkMutation = useMutation({
    mutationFn: (bookmark: Bookmark) => api.addBookmark(bookmark, csrfToken),
    onSuccess: async () => {
      await refreshSession();
      await queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      setBanner({ severity: "success", message: "Bookmark saved." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const saveSearchMutation = useMutation({
    mutationFn: (payload: { name: string; query: string }) =>
      api.saveSearch(
        {
          id: crypto.randomUUID(),
          name: payload.name,
          query: payload.query,
          filters: {},
        },
        csrfToken,
      ),
    onSuccess: async () => {
      await refreshSession();
      setBanner({ severity: "success", message: "Saved search added." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  const cancelJobMutation = useMutation({
    mutationFn: (jobId: string) => api.cancelJob(jobId, csrfToken),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["jobs"] });
      await queryClient.invalidateQueries({ queryKey: ["simulation-history"] });
      setBanner({ severity: "success", message: "Job cancellation requested." });
    },
    onError: (caught) => setBanner({ severity: "error", message: notificationMessage(caught) }),
  });

  useEffect(() => {
    setSearchDraft(searchQuery);
  }, [searchQuery]);

  useEffect(() => {
    if (!projectsQuery.data?.length) {
      return;
    }
    const project = projectsQuery.data.find((candidate) => candidate.id === selectedProjectId) ?? projectsQuery.data[0];
    const branch = project.branches.find((candidate) => candidate.id === selectedBranchId) ?? project.branches[0];

    if (!selectedProjectId || selectedProjectId !== project.id || !selectedBranchId || selectedBranchId !== branch?.id) {
      updateParams(
        {
          project: project.id,
          branch: branch?.id ?? "main",
        },
        true,
      );
    }
  }, [projectsQuery.data, selectedBranchId, selectedProjectId]);

  useEffect(() => {
    if (documentsQuery.data?.length && !selectedDocumentId) {
      updateParams({ doc: documentsQuery.data[0].id }, true);
    }
  }, [documentsQuery.data, selectedDocumentId]);

  useEffect(() => {
    if (!itemQuery.data) {
      return;
    }
    setItemDraft({
      name: itemQuery.data.name,
      description: itemQuery.data.description,
      documentation_markdown: itemQuery.data.documentation_markdown,
      version: itemQuery.data.version,
    });
    setItemMetadataDraft(JSON.stringify(itemQuery.data.metadata ?? {}, null, 2));
  }, [itemQuery.data]);

  useEffect(() => {
    if (!documentQuery.data) {
      return;
    }
    setDocumentDraft(documentQuery.data.body_markdown);
    setDocumentEditMode(false);
  }, [documentQuery.data]);

  useEffect(() => {
    if (branchDialogOpen) {
      return;
    }
    const project = (projectsQuery.data ?? []).find((candidate) => candidate.id === selectedProjectId);
    const branch = project?.branches.find((candidate) => candidate.id === selectedBranchId) ?? project?.branches[0];
    setBranchDraft({
      name: branch?.name ?? "",
      description: branch?.description ?? "",
    });
  }, [branchDialogOpen, projectsQuery.data, selectedBranchId, selectedProjectId]);

  useEffect(() => {
    const configs = simulationConfigsQuery.data ?? [];
    if (!configs.length) {
      return;
    }
    const config = configs.find((candidate) => candidate.id === selectedSimulationConfigId) ?? configs[0];
    if (config.id !== selectedSimulationConfigId) {
      setSelectedSimulationConfigId(config.id);
    }
  }, [selectedSimulationConfigId, simulationConfigsQuery.data]);

  useEffect(() => {
    const config = simulationConfigsQuery.data?.find((candidate) => candidate.id === selectedSimulationConfigId);
    if (!config) {
      return;
    }
    const nextValues: Record<string, string | number | boolean> = {};
    config.editable_parameters.forEach((parameter) => {
      nextValues[parameter.name] =
        parameter.default_value ?? (parameter.kind === "boolean" ? false : parameter.kind === "choice" ? parameter.options[0] ?? "" : "");
    });
    setSimulationValues(nextValues);
  }, [selectedSimulationConfigId, simulationConfigsQuery.data]);

  useEffect(() => {
    const history = simulationHistoryQuery.data ?? [];
    if (history.length && !simulationCompareLeftId) {
      setSimulationCompareLeftId(history[0].id);
      setSimulationCompareRightId(history[1]?.id ?? "");
    }
  }, [simulationCompareLeftId, simulationHistoryQuery.data]);

  const selectedProject = (projectsQuery.data ?? []).find((project) => project.id === selectedProjectId) ?? null;
  const selectedBranch = selectedProject?.branches.find((branch) => branch.id === selectedBranchId) ?? selectedProject?.branches[0] ?? null;
  const selectedConfig = (simulationConfigsQuery.data ?? []).find((config) => config.id === selectedSimulationConfigId) ?? null;
  const selectedItem = itemQuery.data ?? null;
  const selectedDocument = documentQuery.data ?? null;
  const allNodes = flattenNodes(treeQuery.data ?? []);
  const selectableNodes = allNodes.filter((node) => node.node_type !== "package");
  const latestSimulationJob = (simulationHistoryQuery.data ?? []).find((job) => job.status === "running") ?? simulationHistoryQuery.data?.[0];
  const simulationCompareRows = buildCompareRows(
    simulationHistoryQuery.data?.find((job) => job.id === simulationCompareLeftId),
    simulationHistoryQuery.data?.find((job) => job.id === simulationCompareRightId),
  );

  const openItem = (itemId: string, targetTab: WorkspaceTab = "details") => {
    updateParams({ item: itemId, tab: targetTab });
  };

  const activeJobs = (jobsQuery.data ?? []).filter((job) => job.status === "running" || job.status === "pending");

  const handleItemSave = async () => {
    try {
      await saveItemMutation.mutateAsync();
      await itemQuery.refetch();
    } catch {
      return;
    }
  };

  const handleDocumentSave = async () => {
    try {
      await updateDocumentMutation.mutateAsync();
      await documentQuery.refetch();
    } catch {
      return;
    }
  };

  const handleSearchSubmit = () => {
    if (!searchDraft.trim()) {
      updateParams({ q: undefined });
      return;
    }
    updateParams({ q: searchDraft.trim(), tab: "search" });
  };

  const triggerExport = async (payload: Parameters<typeof api.exportData>[0]) => {
    try {
      await exportMutation.mutateAsync(payload);
    } catch {
      return;
    }
  };

  const openBranchDialog = () => {
    if (!selectedBranch) {
      return;
    }
    setBranchDraft({
      name: selectedBranch.name,
      description: selectedBranch.description,
    });
    setBranchDialogOpen(true);
  };

  return (
    <Box sx={{ minHeight: "100vh", display: "grid", gridTemplateRows: "auto 1fr auto" }}>
      <AppBar position="sticky" elevation={0}>
        <Toolbar sx={{ gap: 1.5, flexWrap: "wrap", py: 1 }}>
          <IconButton onClick={() => navigate(-1)}>
            <ArrowBackRoundedIcon />
          </IconButton>
          <IconButton onClick={() => navigate(1)}>
            <ArrowForwardRoundedIcon />
          </IconButton>
          <Stack sx={{ minWidth: 220, flex: 1 }}>
            <Typography variant="h5">TWC Workbench</Typography>
            <Typography variant="body2" color="text.secondary">
              Signed in as {session?.user?.preferred_username} on {session?.server?.name}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              The active server comes from the selected preset server, not from `.env`.
            </Typography>
          </Stack>
          <TextField
            value={searchDraft}
            onChange={(event) => setSearchDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                handleSearchSubmit();
              }
            }}
            size="small"
            placeholder="Global search"
            sx={{ minWidth: { xs: "100%", md: 360 } }}
            InputProps={{
              endAdornment: (
                <InputAdornment position="end">
                  <IconButton onClick={handleSearchSubmit}>
                    <SearchRoundedIcon />
                  </IconButton>
                </InputAdornment>
              ),
            }}
          />
          <Button
            variant="outlined"
            startIcon={<SwapHorizRoundedIcon />}
            onClick={() => logoutMutation.mutate()}
            disabled={logoutMutation.isPending}
          >
            Switch Server
          </Button>
          {session?.can_manage_server_presets ? (
            <Button
              variant="outlined"
              startIcon={<AdminPanelSettingsRoundedIcon />}
              onClick={() => setServerManagerOpen(true)}
            >
              Manage Presets
            </Button>
          ) : null}
          <Tooltip title="Refresh capabilities and workspace state">
            <span>
              <IconButton onClick={() => refreshCapabilityMutation.mutate()} disabled={refreshCapabilityMutation.isPending}>
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
              <IconButton onClick={() => logoutMutation.mutate()} disabled={logoutMutation.isPending}>
                <LogoutRoundedIcon />
              </IconButton>
            </span>
          </Tooltip>
        </Toolbar>
      </AppBar>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", xl: "320px minmax(0, 1fr) 320px" },
          gap: 2,
          p: 2,
          minHeight: 0,
        }}
      >
        <Paper sx={{ p: 2.5, borderRadius: 5, minHeight: 0, overflow: "auto" }}>
          <Stack spacing={2.5}>
            <div>
              <Typography variant="h6">Navigation</Typography>
              <Typography variant="body2" color="text.secondary">
                Projects, branches, bookmarks, recent items, and saved searches.
              </Typography>
            </div>

            <TextField
              select
              label="Project"
              value={selectedProjectId ?? ""}
              onChange={(event) => updateParams({ project: event.target.value, branch: undefined }, false)}
              fullWidth
            >
              {(projectsQuery.data ?? []).map((project) => (
                <MenuItem key={project.id} value={project.id}>
                  {project.name}
                </MenuItem>
              ))}
            </TextField>

            <Stack spacing={1}>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ xs: "stretch", sm: "flex-start" }}>
                <TextField
                  select
                  label="Branch"
                  value={selectedBranchId ?? ""}
                  onChange={(event) => updateParams({ branch: event.target.value })}
                  fullWidth
                  disabled={!selectedProject}
                >
                  {(selectedProject?.branches ?? []).map((branch) => (
                    <MenuItem key={branch.id} value={branch.id}>
                      {branch.name}
                    </MenuItem>
                  ))}
                </TextField>
                <Button
                  variant="outlined"
                  startIcon={<EditRoundedIcon />}
                  disabled={!selectedBranch || !canEditBranches}
                  onClick={openBranchDialog}
                >
                  Edit
                </Button>
              </Stack>
              {selectedBranch?.description ? (
                <Typography variant="body2" color="text.secondary">
                  {selectedBranch.description}
                </Typography>
              ) : null}
              {capabilities.branch_edit && !canEditBranches ? (
                <Typography variant="caption" color="text.secondary">
                  {capabilities.branch_edit.reason}
                </Typography>
              ) : null}
            </Stack>

            <TextField
              label="Filter tree"
              value={treeFilter}
              onChange={(event) => setTreeFilter(event.target.value)}
              fullWidth
            />

            <ProjectTree
              nodes={treeQuery.data ?? []}
              selectedId={selectedItemId}
              filter={deferredTreeFilter}
              onSelect={(node) => {
                if (node.node_type !== "package") {
                  openItem(node.id, "details");
                }
              }}
            />

            <Divider />
            <div>
              <Typography variant="subtitle1" fontWeight={700}>
                Bookmarks
              </Typography>
              <List dense disablePadding>
                {(session?.bookmarks ?? []).map((bookmark) => (
                  <ListItemButton key={bookmark.id} onClick={() => openItem(bookmark.item_id, "details")} sx={{ borderRadius: 2 }}>
                    <ListItemText primary={bookmark.title} secondary={bookmark.path} />
                  </ListItemButton>
                ))}
              </List>
            </div>

            <div>
              <Typography variant="subtitle1" fontWeight={700}>
                Recent Items
              </Typography>
              <List dense disablePadding>
                {(session?.recent_items ?? []).map((bookmark) => (
                  <ListItemButton key={bookmark.id} onClick={() => openItem(bookmark.item_id, "details")} sx={{ borderRadius: 2 }}>
                    <ListItemText primary={bookmark.title} secondary={bookmark.path} />
                  </ListItemButton>
                ))}
              </List>
            </div>

            <div>
              <Typography variant="subtitle1" fontWeight={700}>
                Saved Searches
              </Typography>
              <List dense disablePadding>
                {(session?.saved_searches ?? []).map((savedSearch) => (
                  <ListItemButton key={savedSearch.id} onClick={() => updateParams({ q: savedSearch.query, tab: "search" })} sx={{ borderRadius: 2 }}>
                    <ListItemText primary={savedSearch.name} secondary={savedSearch.query} />
                  </ListItemButton>
                ))}
              </List>
            </div>
          </Stack>
        </Paper>

        <Paper sx={{ borderRadius: 5, minHeight: 0, overflow: "hidden", display: "flex", flexDirection: "column" }}>
          <Box sx={{ px: 2, pt: 1 }}>
            <Tabs value={selectedTab} onChange={(_, value: WorkspaceTab) => updateParams({ tab: value })} variant="scrollable" scrollButtons="auto">
              {WORKSPACE_TABS.map((tab) => (
                <Tab key={tab.value} value={tab.value} label={tab.label} />
              ))}
            </Tabs>
          </Box>
          <Divider />
          <Box sx={{ p: 2.5, overflow: "auto", minHeight: 0, flex: 1 }}>
            {banner ? <Alert severity={banner.severity} sx={{ mb: 2 }}>{banner.message}</Alert> : null}

            {selectedTab === "dashboard" ? (
              <Stack spacing={2.5}>
                <Typography variant="h4">Workspace Dashboard</Typography>
                <Grid container spacing={2}>
                  <Grid item xs={12} md={6} xl={3}>
                    <MetricCard label="Projects" value={String((dashboardQuery.data?.projects ?? []).length)} caption="Projects visible to the active Teamwork Cloud session." />
                  </Grid>
                  <Grid item xs={12} md={6} xl={3}>
                    <MetricCard label="Active Jobs" value={String(activeJobs.length)} caption="Simulation, publish, and export work currently running." />
                  </Grid>
                  <Grid item xs={12} md={6} xl={3}>
                    <MetricCard label="Bookmarks" value={String(session?.bookmarks.length ?? 0)} caption="Pinned assets for repeat review and presentation paths." />
                  </Grid>
                  <Grid item xs={12} md={6} xl={3}>
                    <MetricCard label="Saved Searches" value={String(session?.saved_searches.length ?? 0)} caption="Reusable search lenses for model review workflows." />
                  </Grid>
                </Grid>

                <Card sx={{ borderRadius: 5 }}>
                  <CardContent>
                    <Stack spacing={2}>
                      <Typography variant="h5">Capability Envelope</Typography>
                      <CapabilityBadges capabilities={capabilities} size="medium" />
                      <Typography variant="body2" color="text.secondary">
                        Actions are enabled or softened based on live capability probes and safe fallback adapters.
                      </Typography>
                    </Stack>
                  </CardContent>
                </Card>

                <Grid container spacing={2}>
                  <Grid item xs={12} lg={7}>
                    <Card sx={{ borderRadius: 5, height: "100%" }}>
                      <CardContent>
                        <Stack spacing={2}>
                          <Typography variant="h5">Publish to Collaborator</Typography>
                          {capabilities.publish ? (
                            <Alert severity={capabilityColor(capabilities.publish.state) === "success" ? "success" : "warning"}>
                              {capabilities.publish.reason}
                            </Alert>
                          ) : null}
                          <Grid container spacing={2}>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="Scope"
                                fullWidth
                                value={publishForm.scope}
                                onChange={(event) => setPublishForm((current) => ({ ...current, scope: event.target.value }))}
                              />
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                select
                                label="Preset"
                                fullWidth
                                value={`${publishForm.template}::${publishForm.category}`}
                                onChange={(event) => {
                                  const [template, category] = event.target.value.split("::");
                                  setPublishForm((current) => ({ ...current, template, category }));
                                }}
                              >
                                {(dashboardQuery.data?.publish_presets ?? []).map((preset) => (
                                  <MenuItem key={preset.id} value={`${preset.template}::${preset.category}`}>
                                    {preset.name}
                                  </MenuItem>
                                ))}
                              </TextField>
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="Template"
                                fullWidth
                                value={publishForm.template}
                                onChange={(event) => setPublishForm((current) => ({ ...current, template: event.target.value }))}
                              />
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="Category"
                                fullWidth
                                value={publishForm.category}
                                onChange={(event) => setPublishForm((current) => ({ ...current, category: event.target.value }))}
                              />
                            </Grid>
                          </Grid>
                          <Stack direction={{ xs: "column", md: "row" }} spacing={2}>
                            <FormControlLabel
                              control={<Switch checked={publishForm.republish} onChange={(event) => setPublishForm((current) => ({ ...current, republish: event.target.checked }))} />}
                              label="Republish"
                            />
                            <FormControlLabel
                              control={<Switch checked={publishForm.open_result} onChange={(event) => setPublishForm((current) => ({ ...current, open_result: event.target.checked }))} />}
                              label="Open result when ready"
                            />
                          </Stack>
                          <Button variant="contained" disabled={!canPublish || publishMutation.isPending} onClick={() => publishMutation.mutate()}>
                            Submit Publish Job
                          </Button>
                        </Stack>
                      </CardContent>
                    </Card>
                  </Grid>
                  <Grid item xs={12} lg={5}>
                    <Card sx={{ borderRadius: 5, height: "100%" }}>
                      <CardContent>
                        <Stack spacing={2}>
                          <Typography variant="h5">Recent Activity</Typography>
                          <List dense disablePadding>
                            {(dashboardQuery.data?.recent_items ?? []).map((item) => (
                              <ListItemButton key={item.id} onClick={() => openItem(item.item_id, "details")} sx={{ borderRadius: 2 }}>
                                <ListItemText primary={item.title} secondary={item.path} />
                              </ListItemButton>
                            ))}
                          </List>
                        </Stack>
                      </CardContent>
                    </Card>
                  </Grid>
                </Grid>
              </Stack>
            ) : null}

            {selectedTab === "projects" ? (
              <Stack spacing={2.5}>
                <Typography variant="h4">Project Browser</Typography>
                <Grid container spacing={2}>
                  {(projectsQuery.data ?? []).map((project) => (
                    <Grid item xs={12} md={6} key={project.id}>
                      <Card sx={{ borderRadius: 5, height: "100%" }}>
                        <CardContent>
                          <Stack spacing={1.5}>
                            <Stack direction="row" justifyContent="space-between" alignItems="center">
                              <Typography variant="h5">{project.name}</Typography>
                              <Chip size="small" label={project.favorite ? "favorite" : "project"} />
                            </Stack>
                            <Typography color="text.secondary">{project.description}</Typography>
                            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                              {project.branches.map((branch) => (
                                <Chip key={branch.id} label={branch.name} variant={branch.id === selectedBranchId && project.id === selectedProjectId ? "filled" : "outlined"} />
                              ))}
                            </Stack>
                            <Button variant="contained" onClick={() => updateParams({ project: project.id, branch: project.branches[0]?.id, tab: "models" })}>
                              Open Project
                            </Button>
                          </Stack>
                        </CardContent>
                      </Card>
                    </Grid>
                  ))}
                </Grid>
              </Stack>
            ) : null}

            {selectedTab === "models" ? (
              <Stack spacing={2.5}>
                <Typography variant="h4">Model Browser</Typography>
                <Alert severity="info">
                  Browse packages, branches, and model elements from the left navigation tree. The center view shows the currently loaded model slice for the selected project and branch.
                </Alert>
                <Grid container spacing={2}>
                  {selectableNodes.map((node) => (
                    <Grid item xs={12} md={6} lg={4} key={node.id}>
                      <Card sx={{ borderRadius: 5, height: "100%" }}>
                        <CardContent>
                          <Stack spacing={1.5}>
                            <Typography variant="h6">{node.label}</Typography>
                            <Typography variant="body2" color="text.secondary">
                              {node.path}
                            </Typography>
                            <Chip size="small" label={node.node_type} sx={{ width: "fit-content" }} />
                            <Button variant="outlined" onClick={() => openItem(node.id, "details")}>
                              Open Details
                            </Button>
                          </Stack>
                        </CardContent>
                      </Card>
                    </Grid>
                  ))}
                </Grid>
              </Stack>
            ) : null}

            {selectedTab === "details" ? (
              selectedItem ? (
                <Stack spacing={2.5}>
                  <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2}>
                    <div>
                      <Typography variant="h4">{selectedItem.name}</Typography>
                      <Typography color="text.secondary">{selectedItem.path}</Typography>
                    </div>
                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                      <Button
                        variant="outlined"
                        startIcon={<BookmarkAddRoundedIcon />}
                        onClick={() =>
                          saveBookmarkMutation.mutate({
                            id: crypto.randomUUID(),
                            title: selectedItem.name,
                            item_id: selectedItem.id,
                            item_type: selectedItem.item_type,
                            path: selectedItem.path,
                          })
                        }
                      >
                        Bookmark
                      </Button>
                      <Button variant="outlined" startIcon={<CompareArrowsRoundedIcon />} onClick={() => updateParams({ compareLeft: selectedItem.id, tab: "compare" })}>
                        Set Compare Left
                      </Button>
                      <Button variant="outlined" startIcon={<CompareArrowsRoundedIcon />} onClick={() => updateParams({ compareRight: selectedItem.id, tab: "compare" })}>
                        Set Compare Right
                      </Button>
                    </Stack>
                  </Stack>

                  {!selectedItem.editable || !canEditItems ? (
                    <Alert severity="info">
                      This item is currently read-only. Editable items can be saved when both the active branch and capability probe permit updates.
                    </Alert>
                  ) : (
                    <Alert severity={capabilities.edit?.state === "restricted" ? "warning" : "success"}>
                      {capabilities.edit?.reason ?? "Editing is enabled for this item."}
                    </Alert>
                  )}

                  <Grid container spacing={2}>
                    <Grid item xs={12} lg={8}>
                      <Card sx={{ borderRadius: 5 }}>
                        <CardContent>
                          <Stack spacing={2}>
                            <TextField
                              label="Name"
                              fullWidth
                              value={itemDraft.name ?? ""}
                              disabled={!selectedItem.editable || !canEditItems}
                              onChange={(event) => setItemDraft((current) => ({ ...current, name: event.target.value }))}
                            />
                            <TextField
                              label="Description"
                              fullWidth
                              multiline
                              minRows={3}
                              value={itemDraft.description ?? ""}
                              disabled={!selectedItem.editable || !canEditItems}
                              onChange={(event) => setItemDraft((current) => ({ ...current, description: event.target.value }))}
                            />
                            <TextField
                              label="Documentation"
                              fullWidth
                              multiline
                              minRows={10}
                              value={itemDraft.documentation_markdown ?? ""}
                              disabled={!selectedItem.editable || !canEditItems}
                              onChange={(event) => setItemDraft((current) => ({ ...current, documentation_markdown: event.target.value }))}
                            />
                            <Grid container spacing={2}>
                              <Grid item xs={12} md={4}>
                                <TextField
                                  label="Version"
                                  fullWidth
                                  value={itemDraft.version ?? ""}
                                  disabled={!selectedItem.editable || !canEditItems}
                                  onChange={(event) => setItemDraft((current) => ({ ...current, version: event.target.value }))}
                                />
                              </Grid>
                              <Grid item xs={12} md={8}>
                                <TextField
                                  label="Metadata JSON"
                                  fullWidth
                                  multiline
                                  minRows={6}
                                  value={itemMetadataDraft}
                                  disabled={!selectedItem.editable || !canEditItems}
                                  onChange={(event) => setItemMetadataDraft(event.target.value)}
                                />
                              </Grid>
                            </Grid>
                            <Stack direction="row" spacing={1}>
                              <Button
                                variant="contained"
                                startIcon={<SaveRoundedIcon />}
                                disabled={!selectedItem.editable || !canEditItems || saveItemMutation.isPending}
                                onClick={handleItemSave}
                              >
                                Save
                              </Button>
                              <Button
                                variant="outlined"
                                disabled={saveItemMutation.isPending}
                                onClick={() => itemQuery.refetch()}
                              >
                                Revert from Server
                              </Button>
                              <Button
                                variant="text"
                                onClick={() => {
                                  setItemDraft({
                                    name: selectedItem.name,
                                    description: selectedItem.description,
                                    documentation_markdown: selectedItem.documentation_markdown,
                                    version: selectedItem.version,
                                  });
                                  setItemMetadataDraft(JSON.stringify(selectedItem.metadata ?? {}, null, 2));
                                }}
                              >
                                Discard Draft
                              </Button>
                            </Stack>
                          </Stack>
                        </CardContent>
                      </Card>
                    </Grid>
                    <Grid item xs={12} lg={4}>
                      <Card sx={{ borderRadius: 5 }}>
                        <CardContent>
                          <Stack spacing={2}>
                            <Typography variant="h6">Relationships</Typography>
                            <List dense disablePadding>
                              {selectedItem.relationships.map((relationship, index) => (
                                <ListItemButton key={`${relationship.type}-${relationship.target}-${index}`} sx={{ borderRadius: 2 }}>
                                  <ListItemText primary={`${relationship.type} → ${relationship.target}`} />
                                </ListItemButton>
                              ))}
                            </List>
                            <Divider />
                            <Typography variant="h6">Export</Typography>
                            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                              {["json", "markdown", "html", "pdf"].map((format) => (
                                <Button
                                  key={format}
                                  variant="outlined"
                                  onClick={() =>
                                    triggerExport({
                                      export_type: "item",
                                      export_format: format as "json" | "markdown" | "html" | "pdf",
                                      reference_id: selectedItem.id,
                                      payload: {},
                                    })
                                  }
                                >
                                  {format.toUpperCase()}
                                </Button>
                              ))}
                            </Stack>
                          </Stack>
                        </CardContent>
                      </Card>
                    </Grid>
                  </Grid>
                </Stack>
              ) : (
                <Alert severity="info">Select a model item from the navigation tree or search results to inspect and edit details.</Alert>
              )
            ) : null}

            {selectedTab === "compare" ? (
              <Stack spacing={2.5}>
                <Typography variant="h4">Compare</Typography>
                <Grid container spacing={2}>
                  <Grid item xs={12} md={6}>
                    <TextField select label="Left Item" fullWidth value={compareLeftId} onChange={(event) => updateParams({ compareLeft: event.target.value })}>
                      {selectableNodes.map((node) => (
                        <MenuItem key={node.id} value={node.id}>
                          {node.label}
                        </MenuItem>
                      ))}
                    </TextField>
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <TextField select label="Right Item" fullWidth value={compareRightId} onChange={(event) => updateParams({ compareRight: event.target.value })}>
                      {selectableNodes.map((node) => (
                        <MenuItem key={node.id} value={node.id}>
                          {node.label}
                        </MenuItem>
                      ))}
                    </TextField>
                  </Grid>
                </Grid>

                {compareQuery.data ? (
                  <Card sx={{ borderRadius: 5 }}>
                    <CardContent>
                      <Stack spacing={2}>
                        <Stack direction="row" justifyContent="space-between" alignItems="center">
                          <Typography variant="h5">Item Comparison</Typography>
                          <Button
                            variant="outlined"
                            onClick={() =>
                              triggerExport({
                                export_type: "compare",
                                export_format: "json",
                                payload: compareQuery.data as unknown as Record<string, unknown>,
                              })
                            }
                          >
                            Export Comparison
                          </Button>
                        </Stack>
                        <Typography color="text.secondary">{compareQuery.data.summary}</Typography>
                        <List dense disablePadding>
                          {compareQuery.data.differences.map((difference) => (
                            <ListItemButton key={difference.field_path} sx={{ borderRadius: 2 }}>
                              <ListItemText
                                primary={difference.field_path}
                                secondary={`Left: ${prettyValue(difference.left_value)} | Right: ${prettyValue(difference.right_value)}`}
                              />
                            </ListItemButton>
                          ))}
                        </List>
                      </Stack>
                    </CardContent>
                  </Card>
                ) : (
                  <Alert severity="info">Choose two items to compare structure, metadata, and documentation fields.</Alert>
                )}

                <Card sx={{ borderRadius: 5 }}>
                  <CardContent>
                    <Stack spacing={2}>
                      <Typography variant="h5">Simulation Run Comparison</Typography>
                      <Grid container spacing={2}>
                        <Grid item xs={12} md={6}>
                          <TextField select label="Left Run" fullWidth value={simulationCompareLeftId} onChange={(event) => setSimulationCompareLeftId(event.target.value)}>
                            {(simulationHistoryQuery.data ?? []).map((job) => (
                              <MenuItem key={job.id} value={job.id}>
                                {job.title} · {formatDate(job.created_at)}
                              </MenuItem>
                            ))}
                          </TextField>
                        </Grid>
                        <Grid item xs={12} md={6}>
                          <TextField select label="Right Run" fullWidth value={simulationCompareRightId} onChange={(event) => setSimulationCompareRightId(event.target.value)}>
                            {(simulationHistoryQuery.data ?? []).map((job) => (
                              <MenuItem key={job.id} value={job.id}>
                                {job.title} · {formatDate(job.created_at)}
                              </MenuItem>
                            ))}
                          </TextField>
                        </Grid>
                      </Grid>
                      <List dense disablePadding>
                        {simulationCompareRows.map((difference) => (
                          <ListItemButton key={difference.field_path} sx={{ borderRadius: 2 }}>
                            <ListItemText
                              primary={difference.field_path}
                              secondary={`Left: ${prettyValue(difference.left_value)} | Right: ${prettyValue(difference.right_value)}`}
                            />
                          </ListItemButton>
                        ))}
                      </List>
                    </Stack>
                  </CardContent>
                </Card>
              </Stack>
            ) : null}

            {selectedTab === "simulation" ? (
              <Stack spacing={2.5}>
                <Typography variant="h4">Simulation</Typography>
                {capabilities.simulation ? (
                  <Alert severity={capabilities.simulation.state === "ready" ? "success" : "warning"}>
                    {capabilities.simulation.reason}
                  </Alert>
                ) : null}

                <Grid container spacing={2}>
                  <Grid item xs={12} lg={7}>
                    <Card sx={{ borderRadius: 5 }}>
                      <CardContent>
                        <Stack spacing={2}>
                          <TextField
                            select
                            label="Simulation Configuration"
                            fullWidth
                            value={selectedSimulationConfigId}
                            onChange={(event) => setSelectedSimulationConfigId(event.target.value)}
                          >
                            {(simulationConfigsQuery.data ?? []).map((config) => (
                              <MenuItem key={config.id} value={config.id}>
                                {config.name}
                              </MenuItem>
                            ))}
                          </TextField>
                          <Typography color="text.secondary">{selectedConfig?.description}</Typography>
                          <Grid container spacing={2}>
                            {(selectedConfig?.editable_parameters ?? []).map((parameter) => (
                              <Grid item xs={12} md={6} key={parameter.name}>
                                <ParameterField
                                  parameter={parameter}
                                  value={simulationValues[parameter.name] ?? ""}
                                  onChange={(value) => setSimulationValues((current) => ({ ...current, [parameter.name]: value }))}
                                />
                              </Grid>
                            ))}
                          </Grid>
                          <Button
                            variant="contained"
                            startIcon={<PlayArrowRoundedIcon />}
                            disabled={!canRunSimulation || runSimulationMutation.isPending}
                            onClick={() => runSimulationMutation.mutate()}
                          >
                            Run Simulation
                          </Button>
                        </Stack>
                      </CardContent>
                    </Card>
                  </Grid>
                  <Grid item xs={12} lg={5}>
                    <Card sx={{ borderRadius: 5, height: "100%" }}>
                      <CardContent>
                        <Stack spacing={2}>
                          <Typography variant="h5">Latest Result</Typography>
                          {latestSimulationJob?.result?.metrics ? (
                            <Grid container spacing={2}>
                              {Object.entries(latestSimulationJob.result.metrics as Record<string, unknown>).map(([key, value]) => (
                                <Grid item xs={12} sm={6} key={key}>
                                  <Paper sx={{ p: 2, borderRadius: 4 }}>
                                    <Typography variant="overline" color="text.secondary">
                                      {key}
                                    </Typography>
                                    <Typography variant="h5">{prettyValue(value)}</Typography>
                                  </Paper>
                                </Grid>
                              ))}
                            </Grid>
                          ) : (
                            <Typography color="text.secondary">Run a simulation to populate live metrics and result packages.</Typography>
                          )}
                          {latestSimulationJob ? (
                            <Box>
                              <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                                Live Logs
                              </Typography>
                              <Paper sx={{ p: 2, borderRadius: 4, bgcolor: "background.default", maxHeight: 220, overflow: "auto" }}>
                                <Typography component="pre" sx={{ m: 0, fontFamily: '"IBM Plex Mono", Consolas, monospace', whiteSpace: "pre-wrap" }}>
                                  {latestSimulationJob.logs.join("\n") || "No logs yet."}
                                </Typography>
                              </Paper>
                            </Box>
                          ) : null}
                        </Stack>
                      </CardContent>
                    </Card>
                  </Grid>
                </Grid>

                <Card sx={{ borderRadius: 5 }}>
                  <CardContent>
                    <Stack spacing={2}>
                      <Typography variant="h5">Run History</Typography>
                      <List dense disablePadding>
                        {(simulationHistoryQuery.data ?? []).map((job) => (
                          <ListItemButton key={job.id} sx={{ borderRadius: 2 }}>
                            <ListItemText
                              primary={job.title}
                              secondary={`${job.status} · ${formatDate(job.created_at)} · ${job.message}`}
                            />
                            {job.artifact_path ? (
                              <Button component="a" href={api.jobArtifactUrl(job.id)} target="_blank" rel="noreferrer" startIcon={<DownloadRoundedIcon />}>
                                Artifact
                              </Button>
                            ) : null}
                          </ListItemButton>
                        ))}
                      </List>
                    </Stack>
                  </CardContent>
                </Card>
              </Stack>
            ) : null}

            {selectedTab === "collaborator" ? (
              selectedDocument ? (
                <Stack spacing={2.5}>
                  <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2}>
                    <div>
                      <Typography variant="h4">{selectedDocument.title}</Typography>
                      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                        {selectedDocument.breadcrumbs.map((crumb) => (
                          <Chip key={crumb} label={crumb} variant="outlined" />
                        ))}
                      </Stack>
                    </div>
                    <Stack direction="row" spacing={1}>
                      <Button variant="outlined" startIcon={<FullscreenRoundedIcon />} onClick={() => setPresentationOpen(true)}>
                        Presentation Mode
                      </Button>
                      <TextField
                        select
                        size="small"
                        label="Document"
                        value={selectedDocument.id}
                        onChange={(event) => updateParams({ doc: event.target.value })}
                        sx={{ minWidth: 220 }}
                      >
                        {(documentsQuery.data ?? []).map((document) => (
                          <MenuItem key={document.id} value={document.id}>
                            {document.title}
                          </MenuItem>
                        ))}
                      </TextField>
                    </Stack>
                  </Stack>

                  {!selectedDocument.editable || !canEditItems ? (
                    <Alert severity="info">Document editing is currently read-only for this session or branch.</Alert>
                  ) : (
                    <Alert severity={capabilities.edit?.state === "restricted" ? "warning" : "success"}>{capabilities.edit?.reason}</Alert>
                  )}

                  <Grid container spacing={2}>
                    <Grid item xs={12} lg={8}>
                      <Card sx={{ borderRadius: 5 }}>
                        <CardContent>
                          <Stack spacing={2}>
                            <Stack direction="row" spacing={1} justifyContent="space-between" alignItems="center">
                              <Typography variant="h5">Document View</Typography>
                              {selectedDocument.editable ? (
                                <FormControlLabel
                                  control={<Switch checked={documentEditMode} onChange={(event) => setDocumentEditMode(event.target.checked)} />}
                                  label="Edit Mode"
                                />
                              ) : null}
                            </Stack>
                            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                              {selectedDocument.toc.map((entry) => (
                                <Chip key={entry} label={entry} variant="outlined" />
                              ))}
                            </Stack>
                            {documentEditMode && selectedDocument.editable && canEditItems ? (
                              <Stack spacing={2}>
                                <TextField
                                  value={documentDraft}
                                  onChange={(event) => setDocumentDraft(event.target.value)}
                                  fullWidth
                                  multiline
                                  minRows={18}
                                />
                                <Stack direction="row" spacing={1}>
                                  <Button variant="contained" startIcon={<SaveRoundedIcon />} onClick={handleDocumentSave} disabled={updateDocumentMutation.isPending}>
                                    Save
                                  </Button>
                                  <Button variant="outlined" onClick={() => documentQuery.refetch()}>
                                    Revert from Server
                                  </Button>
                                  <Button variant="text" onClick={() => setDocumentDraft(selectedDocument.body_markdown)}>
                                    Discard Draft
                                  </Button>
                                </Stack>
                              </Stack>
                            ) : (
                              <Paper sx={{ p: 3, borderRadius: 4, bgcolor: "background.default" }}>
                                <ReactMarkdown>{selectedDocument.body_markdown}</ReactMarkdown>
                              </Paper>
                            )}
                          </Stack>
                        </CardContent>
                      </Card>
                    </Grid>
                    <Grid item xs={12} lg={4}>
                      <Stack spacing={2}>
                        <Card sx={{ borderRadius: 5 }}>
                          <CardContent>
                            <Stack spacing={2}>
                              <Typography variant="h5">Attachments</Typography>
                              {capabilities.attachment ? (
                                <Alert severity={capabilities.attachment.state === "ready" ? "success" : "warning"}>
                                  {capabilities.attachment.reason}
                                </Alert>
                              ) : null}
                              <Button component="label" variant="outlined" startIcon={<UploadRoundedIcon />} disabled={!selectedDocument.attachments_supported || !canAttach}>
                                Upload Attachment
                                <input
                                  hidden
                                  type="file"
                                  onChange={(event: ChangeEvent<HTMLInputElement>) => {
                                    const file = event.target.files?.[0];
                                    if (file) {
                                      uploadAttachmentMutation.mutate(file);
                                    }
                                  }}
                                />
                              </Button>
                              <Stack spacing={1.5}>
                                {(attachmentsQuery.data ?? []).map((attachment: AttachmentInfo) => (
                                  <Paper key={attachment.id} sx={{ p: 1.5, borderRadius: 4 }}>
                                    <Stack spacing={1.25}>
                                      {attachment.content_type.startsWith("image/") ? (
                                        <Box
                                          component="img"
                                          src={api.attachmentDownloadUrl(attachment.document_id, attachment.id)}
                                          alt={attachment.file_name}
                                          sx={{ width: "100%", borderRadius: 3, maxHeight: 160, objectFit: "cover" }}
                                        />
                                      ) : null}
                                      <Typography fontWeight={600}>{attachment.file_name}</Typography>
                                      <Typography variant="body2" color="text.secondary">
                                        {formatBytes(attachment.size_bytes)} · {attachment.content_type}
                                      </Typography>
                                      <Stack direction="row" spacing={1}>
                                        <Button component="a" href={api.attachmentDownloadUrl(attachment.document_id, attachment.id)} target="_blank" rel="noreferrer" size="small">
                                          Download
                                        </Button>
                                        <Button color="error" size="small" onClick={() => deleteAttachmentMutation.mutate(attachment.id)}>
                                          Remove
                                        </Button>
                                      </Stack>
                                    </Stack>
                                  </Paper>
                                ))}
                              </Stack>
                            </Stack>
                          </CardContent>
                        </Card>

                        <Card sx={{ borderRadius: 5 }}>
                          <CardContent>
                            <Stack spacing={2}>
                              <Typography variant="h5">Comments and Notes</Typography>
                              <TextField
                                multiline
                                minRows={3}
                                value={commentDraft}
                                onChange={(event) => setCommentDraft(event.target.value)}
                                placeholder="Add a reviewer note or annotation"
                              />
                              <Button variant="contained" onClick={() => addCommentMutation.mutate()} disabled={!commentDraft.trim()}>
                                Add Comment
                              </Button>
                              <List dense disablePadding>
                                {(commentsQuery.data ?? []).map((comment: CommentEntry) => (
                                  <ListItemButton key={comment.id} sx={{ borderRadius: 2 }}>
                                    <ListItemText primary={`${comment.author} · ${formatDate(comment.created_at)}`} secondary={comment.content} />
                                  </ListItemButton>
                                ))}
                              </List>
                            </Stack>
                          </CardContent>
                        </Card>
                      </Stack>
                    </Grid>
                  </Grid>
                </Stack>
              ) : (
                <Alert severity="info">Select a collaborator document to review, present, annotate, or edit.</Alert>
              )
            ) : null}

            {selectedTab === "search" ? (
              <Stack spacing={2.5}>
                <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2}>
                  <div>
                    <Typography variant="h4">Search Results</Typography>
                    <Typography color="text.secondary">Search models, documents, and normalized workspace items.</Typography>
                  </div>
                  <Button
                    variant="outlined"
                    disabled={!searchQuery}
                    onClick={() => {
                      const suggestedName = window.prompt("Saved search name", `Search: ${searchQuery}`);
                      if (suggestedName) {
                        saveSearchMutation.mutate({ name: suggestedName, query: searchQuery });
                      }
                    }}
                  >
                    Save Search
                  </Button>
                </Stack>
                {searchQuery ? (
                  <Typography color="text.secondary">Results for “{searchQuery}”</Typography>
                ) : (
                  <Alert severity="info">Run a global search from the toolbar to populate this view.</Alert>
                )}
                <Grid container spacing={2}>
                  {(searchResultsQuery.data?.results ?? []).map((result) => (
                    <Grid item xs={12} md={6} key={result.id}>
                      <Card sx={{ borderRadius: 5, height: "100%" }}>
                        <CardContent>
                          <Stack spacing={1.5}>
                            <Typography variant="h6">{result.title}</Typography>
                            <Typography variant="body2" color="text.secondary">
                              {result.path}
                            </Typography>
                            <Typography variant="body2">{result.excerpt}</Typography>
                            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                              <Chip size="small" label={result.item_type} />
                              <Chip size="small" variant="outlined" label={`Score ${result.score.toFixed(2)}`} />
                            </Stack>
                            <Button variant="outlined" onClick={() => openItem(result.id, "details")}>
                              Open Item
                            </Button>
                          </Stack>
                        </CardContent>
                      </Card>
                    </Grid>
                  ))}
                </Grid>
              </Stack>
            ) : null}

            {selectedTab === "jobs" ? (
              <Stack spacing={2.5}>
                <Typography variant="h4">Job Center</Typography>
                {(jobsQuery.data ?? []).map((job) => (
                  <Accordion key={job.id} sx={{ borderRadius: 4, overflow: "hidden" }}>
                    <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                      <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} alignItems={{ xs: "flex-start", md: "center" }} sx={{ width: "100%" }}>
                        <Typography fontWeight={700} sx={{ flex: 1 }}>
                          {job.title}
                        </Typography>
                        <Chip size="small" color={jobStatusColor(job.status)} label={job.status} />
                        <Chip size="small" variant="outlined" label={job.job_type} />
                      </Stack>
                    </AccordionSummary>
                    <AccordionDetails>
                      <Stack spacing={2}>
                        <Typography variant="body2" color="text.secondary">
                          {job.message} · Created {formatDate(job.created_at)}
                        </Typography>
                        <LinearProgress variant="determinate" value={job.progress} sx={{ borderRadius: 999, height: 8 }} />
                        <Stack direction="row" spacing={1}>
                          {job.artifact_path ? (
                            <Button component="a" href={api.jobArtifactUrl(job.id)} target="_blank" rel="noreferrer" startIcon={<DownloadRoundedIcon />}>
                              Download Artifact
                            </Button>
                          ) : null}
                          {(job.status === "running" || job.status === "pending") && !job.cancel_requested ? (
                            <Button color="warning" onClick={() => cancelJobMutation.mutate(job.id)}>
                              Cancel Job
                            </Button>
                          ) : null}
                        </Stack>
                        <Paper sx={{ p: 2, borderRadius: 4, bgcolor: "background.default" }}>
                          <Typography component="pre" sx={{ m: 0, fontFamily: '"IBM Plex Mono", Consolas, monospace', whiteSpace: "pre-wrap" }}>
                            {job.logs.join("\n") || "No logs yet."}
                          </Typography>
                        </Paper>
                        {job.result ? (
                          <Paper sx={{ p: 2, borderRadius: 4, bgcolor: "background.default" }}>
                            <Typography component="pre" sx={{ m: 0, fontFamily: '"IBM Plex Mono", Consolas, monospace', whiteSpace: "pre-wrap" }}>
                              {JSON.stringify(job.result, null, 2)}
                            </Typography>
                          </Paper>
                        ) : null}
                      </Stack>
                    </AccordionDetails>
                  </Accordion>
                ))}
              </Stack>
            ) : null}
          </Box>
        </Paper>

        <Paper sx={{ p: 2.5, borderRadius: 5, minHeight: 0, overflow: "auto" }}>
          <Stack spacing={2.5}>
            <div>
              <Typography variant="h6">Inspector</Typography>
              <Typography variant="body2" color="text.secondary">
                Session context, capability badges, and details for the current selection.
              </Typography>
            </div>

            <Card sx={{ borderRadius: 5 }}>
              <CardContent>
                <Stack spacing={1.5}>
                  <Typography variant="subtitle1" fontWeight={700}>
                    Session
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Server: {session?.server?.name}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    User: {session?.user?.preferred_username}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Version: {session?.capabilities?.detected_version ?? "unknown"}
                  </Typography>
                </Stack>
              </CardContent>
            </Card>

            <Card sx={{ borderRadius: 5 }}>
              <CardContent>
                <Stack spacing={2}>
                  <Typography variant="subtitle1" fontWeight={700}>
                    Capabilities
                  </Typography>
                  <CapabilityBadges capabilities={capabilities} />
                </Stack>
              </CardContent>
            </Card>

            {selectedItem ? (
              <Card sx={{ borderRadius: 5 }}>
                <CardContent>
                  <Stack spacing={1.5}>
                    <Typography variant="subtitle1" fontWeight={700}>
                      Selected Item
                    </Typography>
                    <Typography variant="body1">{selectedItem.name}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {selectedItem.path}
                    </Typography>
                    <Chip size="small" label={selectedItem.item_type} sx={{ width: "fit-content" }} />
                    <Typography variant="body2" color="text.secondary">
                      Version {selectedItem.version}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      Collaborators: {selectedItem.collaborators.join(", ") || "-"}
                    </Typography>
                  </Stack>
                </CardContent>
              </Card>
            ) : null}

            {selectedDocument ? (
              <Card sx={{ borderRadius: 5 }}>
                <CardContent>
                  <Stack spacing={1.5}>
                    <Typography variant="subtitle1" fontWeight={700}>
                      Document Versions
                    </Typography>
                    {(selectedDocument.versions ?? []).map((version) => (
                      <Paper key={version.id} sx={{ p: 1.5, borderRadius: 3 }}>
                        <Typography fontWeight={600}>{version.label}</Typography>
                        <Typography variant="body2" color="text.secondary">
                          {formatDate(version.created_at)} · {version.summary}
                        </Typography>
                      </Paper>
                    ))}
                  </Stack>
                </CardContent>
              </Card>
            ) : null}
          </Stack>
        </Paper>
      </Box>

      <Box sx={{ p: 2, pt: 0 }}>
        <JobStrip jobs={(jobsQuery.data ?? []).slice(0, 4)} onCancel={(jobId) => cancelJobMutation.mutate(jobId)} />
      </Box>

      <SettingsDialog
        open={settingsOpen}
        preferences={session?.preferences ?? {
          theme_mode: "system",
          font_scale: 1,
          request_timeout_seconds: 30,
          live_log_poll_interval_ms: 2500,
          presentation_font_scale: 1.2,
        }}
        saving={saveSettingsMutation.isPending}
        onClose={() => setSettingsOpen(false)}
        onSave={async (preferences) => {
          await saveSettingsMutation.mutateAsync(preferences);
        }}
      />

      {session?.csrf_token ? (
        <ServerPresetManagerDialog
          open={serverManagerOpen}
          onClose={() => setServerManagerOpen(false)}
          csrfToken={session.csrf_token}
        />
      ) : null}

      <Dialog open={branchDialogOpen} onClose={() => setBranchDialogOpen(false)} fullWidth maxWidth="sm">
        <Box sx={{ p: 3 }}>
          <Stack spacing={2}>
            <div>
              <Typography variant="h5">Edit Branch</Typography>
              <Typography variant="body2" color="text.secondary">
                Rename the active branch or update its description metadata.
              </Typography>
            </div>
            <TextField
              label="Branch Name"
              fullWidth
              value={branchDraft.name}
              onChange={(event) => setBranchDraft((current) => ({ ...current, name: event.target.value }))}
            />
            <TextField
              label="Description"
              fullWidth
              multiline
              minRows={4}
              value={branchDraft.description}
              onChange={(event) => setBranchDraft((current) => ({ ...current, description: event.target.value }))}
            />
            <Stack direction="row" spacing={1} justifyContent="flex-end">
              <Button variant="text" onClick={() => setBranchDialogOpen(false)} disabled={updateBranchMutation.isPending}>
                Cancel
              </Button>
              <Button
                variant="contained"
                onClick={() => updateBranchMutation.mutate()}
                disabled={!branchDraft.name.trim() || updateBranchMutation.isPending}
              >
                Save Branch
              </Button>
            </Stack>
          </Stack>
        </Box>
      </Dialog>

      <Dialog fullScreen open={presentationOpen} onClose={() => setPresentationOpen(false)}>
        <Box sx={{ p: { xs: 3, md: 6 }, bgcolor: "background.default", minHeight: "100%" }}>
          <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={2} sx={{ mb: 3 }}>
            <div>
              <Typography variant="h3">{selectedDocument?.title}</Typography>
              <Typography color="text.secondary">Presentation mode for collaborator review and room display.</Typography>
            </div>
            <Button variant="outlined" onClick={() => setPresentationOpen(false)}>
              Exit Presentation
            </Button>
          </Stack>
          <Paper sx={{ p: { xs: 3, md: 5 }, borderRadius: 6 }}>
            <Box sx={{ fontSize: `${(session?.preferences.presentation_font_scale ?? 1.2) * 1.1}rem`, lineHeight: 1.8 }}>
              <ReactMarkdown>{selectedDocument?.body_markdown ?? ""}</ReactMarkdown>
            </Box>
          </Paper>
        </Box>
      </Dialog>
    </Box>
  );
}