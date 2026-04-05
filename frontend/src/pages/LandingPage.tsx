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
import { ServerHealth, ServerProfile, ServerProfileInput, TokenLoginRequest } from "../models/api";
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
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  const [tokenForm, setTokenForm] = useState<TokenLoginRequest>({
    server_id: "",
    token: "",
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

  const tokenMutation = useMutation({
    mutationFn: api.tokenLogin,
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
  const selectedTokenServer = servers.find((server) => server.id === tokenForm.server_id) ?? null;

  const openTokenDialog = (serverId: string) => {
    setTokenForm({ server_id: serverId, token: "" });
    setTokenDialogOpen(true);
  };

  const closeTokenDialog = () => {
    setTokenDialogOpen(false);
    setTokenForm((current) => ({ ...current, token: "" }));
  };

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
                  The backend brokers workspace actions strictly through the active user’s Teamwork Cloud identity. Sign-in reuses a valid TWC browser session when available, or validates a direct TWC token for that same user.
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
                    <Chip label="User-scoped TWC auth" sx={{ color: "white", borderColor: "rgba(255,255,255,0.22)" }} variant="outlined" />
                  </Stack>
                  <Typography variant="body2" sx={{ color: "rgba(255,255,255,0.8)" }}>
                    TWC remains the authentication and authorization authority. The workbench never asks for client IDs or callback URLs and never substitutes an admin credential for the active user.
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
              <Typography variant="body2" color="text.secondary">
                Save as many editable server profiles as you need, then sign into the one you want to make active for the current workspace session.
              </Typography>
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
                                <Chip label="TWC user auth" variant="outlined" />
                                <Chip label={health?.status ?? "probing"} color={healthColor(health?.status)} />
                                <Chip label={server.verify_tls ? "TLS verified" : "TLS relaxed"} variant="outlined" />
                              </Stack>
                              <Stack spacing={0.75}>
                                <Typography variant="body2" color="text.secondary">
                                  Sign-in reuses the browser’s forwarded Teamwork Cloud session cookie when available, or accepts a direct TWC token for the same user.
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
                                  Use TWC Session
                                </Button>
                                {authOptions?.token_signin_enabled !== false ? (
                                  <Button
                                    fullWidth
                                    variant="outlined"
                                    startIcon={<VpnKeyRoundedIcon />}
                                    onClick={() => openTokenDialog(server.id)}
                                  >
                                    Use TWC Token
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
                    Create your first Teamwork Cloud connection profile to begin workspace operations with the user’s delegated TWC permissions.
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
                    Reuse the browser’s existing TWC session when this app is deployed behind the same cookie domain or a trusted reverse proxy that forwards the TWC session cookie.
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    When session reuse is not available, provide a user-scoped Teamwork Cloud token. The backend validates it against TWC before opening a workbench session.
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

      <Dialog open={tokenDialogOpen} onClose={closeTokenDialog} fullWidth maxWidth="sm">
        <DialogTitle>Teamwork Cloud Token Sign-In</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ mt: 1 }}>
            <Alert severity="info">
              Provide a user-scoped Teamwork Cloud token. The backend will validate it against TWC and create a local session only after resolving the authenticated TWC user.
            </Alert>
            {selectedTokenServer ? <Typography variant="body2">Server: {selectedTokenServer.name}</Typography> : null}
            <TextField
              label="Teamwork Cloud Token"
              type="password"
              value={tokenForm.token}
              onChange={(event) => setTokenForm((current) => ({ ...current, token: event.target.value }))}
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 3 }}>
          <Button onClick={closeTokenDialog}>Cancel</Button>
          <Button
            variant="contained"
            startIcon={<VpnKeyRoundedIcon />}
            disabled={!tokenForm.server_id || !tokenForm.token || tokenMutation.isPending}
            onClick={async () => {
              await tokenMutation.mutateAsync(tokenForm);
              closeTokenDialog();
            }}
          >
            Sign In with Token
          </Button>
        </DialogActions>
      </Dialog>
    </Container>
  );
}