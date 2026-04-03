import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/GridLegacy";
import AddRoundedIcon from "@mui/icons-material/AddRounded";
import DeleteOutlineRoundedIcon from "@mui/icons-material/DeleteOutlineRounded";
import EditRoundedIcon from "@mui/icons-material/EditRounded";
import FavoriteRoundedIcon from "@mui/icons-material/FavoriteRounded";
import HttpsRoundedIcon from "@mui/icons-material/HttpsRounded";
import LoginRoundedIcon from "@mui/icons-material/LoginRounded";
import MonitorHeartRoundedIcon from "@mui/icons-material/MonitorHeartRounded";
import PublicRoundedIcon from "@mui/icons-material/PublicRounded";
import VpnKeyRoundedIcon from "@mui/icons-material/VpnKeyRounded";

import ServerProfileDialog from "../components/ServerProfileDialog";
import { PatLoginRequest, ServerHealth, ServerProfile, ServerProfileInput } from "../models/api";
import { api } from "../services/api";
import { useSession } from "../state/SessionProvider";
import { formatDate } from "../utils/format";

function healthColor(status?: ServerHealth["status"]): "success" | "warning" | "error" | "default" {
  if (status === "healthy") {
    return "success";
  }
  if (status === "degraded") {
    return "warning";
  }
  if (status === "unreachable") {
    return "error";
  }
  return "default";
}

function errorMessage(caught: unknown): string {
  return caught instanceof Error ? caught.message : "The request failed.";
}

export default function LandingPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { authOptions, error, setSessionSnapshot } = useSession();
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<ServerProfile | null>(null);
  const [patDialogOpen, setPatDialogOpen] = useState(false);
  const [patForm, setPatForm] = useState<PatLoginRequest>({
    server_id: "",
    preferred_username: "",
    personal_access_token: "",
    admin_secret: "",
  });
  const [banner, setBanner] = useState<{ severity: "success" | "error"; message: string } | null>(null);

  const serversQuery = useQuery({
    queryKey: ["servers"],
    queryFn: api.listServers,
  });

  const healthQueries = useQueries({
    queries: (serversQuery.data ?? []).map((server) => ({
      queryKey: ["server-health", server.id],
      queryFn: () => api.getServerHealth(server.id),
      staleTime: 60_000,
    })),
  });

  const createOrUpdateMutation = useMutation({
    mutationFn: async ({ serverId, payload }: { serverId?: string; payload: ServerProfileInput }) => {
      if (serverId) {
        return api.updateServer(serverId, payload);
      }
      return api.createServer(payload);
    },
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["servers"] });
      await queryClient.invalidateQueries({ queryKey: ["server-health"] });
      setBanner({
        severity: "success",
        message: variables.serverId ? "Server profile updated." : "Server profile created.",
      });
      setEditingServer(null);
    },
    onError: (caught) => setBanner({ severity: "error", message: errorMessage(caught) }),
  });

  const deleteMutation = useMutation({
    mutationFn: api.deleteServer,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["servers"] });
      await queryClient.invalidateQueries({ queryKey: ["server-health"] });
      setBanner({ severity: "success", message: "Server profile deleted." });
    },
    onError: (caught) => setBanner({ severity: "error", message: errorMessage(caught) }),
  });

  const patMutation = useMutation({
    mutationFn: api.patLogin,
    onSuccess: (snapshot) => {
      setSessionSnapshot(snapshot);
      navigate("/workspace", { replace: true });
    },
    onError: (caught) => setBanner({ severity: "error", message: errorMessage(caught) }),
  });

  const healthById = new Map<string, ServerHealth>();
  healthQueries.forEach((query) => {
    if (query.data) {
      healthById.set(query.data.server_id, query.data);
    }
  });

  const servers = serversQuery.data ?? [];

  return (
    <Container maxWidth="xl" sx={{ py: { xs: 3, md: 5 } }}>
      <Stack spacing={3}>
        <Paper
          sx={{
            p: { xs: 3, md: 4 },
            borderRadius: 6,
            overflow: "hidden",
            position: "relative",
            background:
              "linear-gradient(135deg, rgba(18,103,181,0.92), rgba(10,63,117,0.92) 42%, rgba(15,159,110,0.9) 100%)",
            color: "white",
          }}
        >
          <Box
            sx={{
              position: "absolute",
              inset: 0,
              background:
                "radial-gradient(circle at top right, rgba(255,255,255,0.18), transparent 30%), radial-gradient(circle at bottom left, rgba(255,255,255,0.15), transparent 28%)",
              pointerEvents: "none",
            }}
          />
          <Grid container spacing={3} sx={{ position: "relative" }}>
            <Grid item xs={12} lg={8}>
              <Stack spacing={2.5}>
                <Chip icon={<MonitorHeartRoundedIcon />} label="Teamwork Cloud 2022x and 2024x" sx={{ width: "fit-content", color: "white", borderColor: "rgba(255,255,255,0.28)" }} variant="outlined" />
                <Typography variant="h2" sx={{ maxWidth: 900 }}>
                  Secure enterprise workbench for modeling, simulation, publishing, and collaborator presentation workflows.
                </Typography>
                <Typography variant="h6" sx={{ maxWidth: 900, color: "rgba(255,255,255,0.82)", fontWeight: 400 }}>
                  The backend owns Teamwork Cloud authentication, session security, token lifecycle, capability detection, and job orchestration. The frontend focuses on a fast operator experience.
                </Typography>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5}>
                  <Button variant="contained" color="secondary" startIcon={<AddRoundedIcon />} onClick={() => setDialogOpen(true)}>
                    Add Server Profile
                  </Button>
                  <Button variant="outlined" color="inherit" startIcon={<MonitorHeartRoundedIcon />} onClick={() => queryClient.invalidateQueries({ queryKey: ["server-health"] })}>
                    Refresh Health
                  </Button>
                </Stack>
              </Stack>
            </Grid>
            <Grid item xs={12} lg={4}>
              <Paper sx={{ p: 3, borderRadius: 5, bgcolor: "rgba(7, 22, 39, 0.28)", color: "white" }}>
                <Stack spacing={2}>
                  <Typography variant="h5">Platform Summary</Typography>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label={`${servers.length} configured servers`} sx={{ color: "white", borderColor: "rgba(255,255,255,0.22)" }} variant="outlined" />
                    <Chip label={`${servers.filter((server) => server.favorite).length} favorites`} sx={{ color: "white", borderColor: "rgba(255,255,255,0.22)" }} variant="outlined" />
                    <Chip label="HTTP-only secure sessions" sx={{ color: "white", borderColor: "rgba(255,255,255,0.22)" }} variant="outlined" />
                  </Stack>
                  <Typography variant="body2" sx={{ color: "rgba(255,255,255,0.8)" }}>
                    OAuth 2.0 authorization code flow is the primary path. An optional personal access token flow is available only when explicitly enabled on the backend.
                  </Typography>
                  <Stack spacing={1.5}>
                    <Stack direction="row" spacing={1.5} alignItems="center">
                      <HttpsRoundedIcon fontSize="small" />
                      <Typography variant="body2">TLS verification and custom CA bundle support</Typography>
                    </Stack>
                    <Stack direction="row" spacing={1.5} alignItems="center">
                      <PublicRoundedIcon fontSize="small" />
                      <Typography variant="body2">Capability-aware UX with server-specific fallbacks</Typography>
                    </Stack>
                  </Stack>
                </Stack>
              </Paper>
            </Grid>
          </Grid>
        </Paper>

        {banner ? <Alert severity={banner.severity}>{banner.message}</Alert> : null}
        {error ? <Alert severity="warning">{error}</Alert> : null}

        <Grid container spacing={3}>
          <Grid item xs={12} lg={8}>
            <Stack spacing={2}>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="h4">Teamwork Cloud Servers</Typography>
                <Button startIcon={<AddRoundedIcon />} variant="contained" onClick={() => setDialogOpen(true)}>
                  New Server
                </Button>
              </Stack>
              {serversQuery.isLoading ? (
                <Paper sx={{ p: 4, borderRadius: 5 }}>
                  <Typography color="text.secondary">Loading server profiles...</Typography>
                </Paper>
              ) : servers.length ? (
                <Grid container spacing={2}>
                  {servers.map((server) => {
                    const health = healthById.get(server.id);
                    return (
                      <Grid item xs={12} md={6} key={server.id}>
                        <Card sx={{ borderRadius: 5, height: "100%" }}>
                          <CardContent sx={{ p: 3 }}>
                            <Stack spacing={2.5} sx={{ height: "100%" }}>
                              <Stack direction="row" justifyContent="space-between" spacing={2} alignItems="flex-start">
                                <Box>
                                  <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                                    <Typography variant="h5">{server.name}</Typography>
                                    {server.favorite ? <FavoriteRoundedIcon color="error" fontSize="small" /> : null}
                                  </Stack>
                                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                                    {server.base_url}
                                  </Typography>
                                </Box>
                                <Stack direction="row" spacing={0.5}>
                                  <IconButton onClick={() => { setEditingServer(server); setDialogOpen(true); }}>
                                    <EditRoundedIcon fontSize="small" />
                                  </IconButton>
                                  <IconButton
                                    color="error"
                                    onClick={() => {
                                      if (window.confirm(`Delete server profile ${server.name}?`)) {
                                        deleteMutation.mutate(server.id);
                                      }
                                    }}
                                  >
                                    <DeleteOutlineRoundedIcon fontSize="small" />
                                  </IconButton>
                                </Stack>
                              </Stack>
                              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                                <Chip label={`Version ${health?.version_hint ?? server.version}`} variant="outlined" />
                                <Chip label={health?.status ?? "probing"} color={healthColor(health?.status)} />
                                <Chip label={server.verify_tls ? "TLS verified" : "TLS relaxed"} variant="outlined" />
                              </Stack>
                              <Stack spacing={0.75}>
                                <Typography variant="body2" color="text.secondary">
                                  Auth URL: {server.auth_url}
                                </Typography>
                                <Typography variant="body2" color="text.secondary">
                                  Callback: {server.callback_url}
                                </Typography>
                                <Typography variant="body2" color="text.secondary">
                                  Last used: {formatDate(server.last_used_at)}
                                </Typography>
                                {health?.message ? (
                                  <Typography variant="body2" color="warning.main">
                                    {health.message}
                                  </Typography>
                                ) : null}
                              </Stack>
                              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.25} sx={{ mt: "auto" }}>
                                <Button
                                  fullWidth
                                  variant="contained"
                                  startIcon={<LoginRoundedIcon />}
                                  onClick={() => window.location.assign(api.signInUrl(server.id))}
                                >
                                  Sign In
                                </Button>
                                {authOptions?.pat_enabled ? (
                                  <Button
                                    fullWidth
                                    variant="outlined"
                                    startIcon={<VpnKeyRoundedIcon />}
                                    onClick={() => {
                                      setPatForm((current) => ({ ...current, server_id: server.id }));
                                      setPatDialogOpen(true);
                                    }}
                                  >
                                    Admin PAT
                                  </Button>
                                ) : null}
                              </Stack>
                            </Stack>
                          </CardContent>
                        </Card>
                      </Grid>
                    );
                  })}
                </Grid>
              ) : (
                <Paper sx={{ p: 5, borderRadius: 5, textAlign: "center" }}>
                  <Typography variant="h5">No server profiles yet</Typography>
                  <Typography variant="body1" color="text.secondary" sx={{ mt: 1 }}>
                    Create your first Teamwork Cloud connection profile to begin authentication and workspace operations.
                  </Typography>
                  <Button sx={{ mt: 2.5 }} variant="contained" startIcon={<AddRoundedIcon />} onClick={() => setDialogOpen(true)}>
                    Add Server Profile
                  </Button>
                </Paper>
              )}
            </Stack>
          </Grid>
          <Grid item xs={12} lg={4}>
            <Stack spacing={2}>
              <Paper sx={{ p: 3, borderRadius: 5 }}>
                <Typography variant="h5">Operational Guidance</Typography>
                <Stack spacing={1.5} sx={{ mt: 2 }}>
                  <Typography variant="body2" color="text.secondary">
                    Use backend callback URLs registered with the Teamwork Cloud authentication provider. The default local callback is usually http://localhost:8000/api/auth/callback.
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    For enterprise deployments, keep certificate validation enabled and provide a CA bundle path when your Teamwork Cloud environment is issued by a private PKI.
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Version can be left on auto for discovery, or pinned to 2022x or 2024x when endpoint behaviors are known in advance.
                  </Typography>
                </Stack>
              </Paper>
              <Paper sx={{ p: 3, borderRadius: 5 }}>
                <Typography variant="h5">Feature Envelope</Typography>
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 2 }}>
                  <Chip label="Projects and model browsing" color="success" />
                  <Chip label="Simulation orchestration" color="success" />
                  <Chip label="Collaborator presentation" color="success" />
                  <Chip label="Pluggable publishing" color="success" />
                  <Chip label="Secure job center" color="success" />
                </Stack>
              </Paper>
            </Stack>
          </Grid>
        </Grid>
      </Stack>

      <ServerProfileDialog
        open={dialogOpen}
        initialValue={editingServer}
        onClose={() => {
          setDialogOpen(false);
          setEditingServer(null);
        }}
        onSubmit={async (payload) => {
          await createOrUpdateMutation.mutateAsync({
            serverId: editingServer?.id,
            payload,
          });
        }}
      />

      <Dialog open={patDialogOpen} onClose={() => setPatDialogOpen(false)} fullWidth maxWidth="sm">
        <DialogTitle>Admin Personal Access Token Sign-In</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert severity="warning">
              This flow is intended for controlled administrative use. OAuth remains the primary authentication path.
            </Alert>
            <TextField
              label="Preferred Username"
              value={patForm.preferred_username}
              onChange={(event) => setPatForm((current) => ({ ...current, preferred_username: event.target.value }))}
              fullWidth
            />
            <TextField
              label="Personal Access Token"
              type="password"
              value={patForm.personal_access_token}
              onChange={(event) => setPatForm((current) => ({ ...current, personal_access_token: event.target.value }))}
              fullWidth
            />
            <TextField
              label="Admin Secret"
              type="password"
              value={patForm.admin_secret ?? ""}
              onChange={(event) => setPatForm((current) => ({ ...current, admin_secret: event.target.value }))}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 3 }}>
          <Button onClick={() => setPatDialogOpen(false)}>Cancel</Button>
          <Button
            variant="contained"
            startIcon={<VpnKeyRoundedIcon />}
            disabled={!patForm.server_id || !patForm.preferred_username || !patForm.personal_access_token || patMutation.isPending}
            onClick={async () => {
              await patMutation.mutateAsync(patForm);
              setPatDialogOpen(false);
            }}
          >
            Sign In with PAT
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}