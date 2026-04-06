import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
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
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/GridLegacy";
import HttpsRoundedIcon from "@mui/icons-material/HttpsRounded";
import LoginRoundedIcon from "@mui/icons-material/LoginRounded";
import MonitorHeartRoundedIcon from "@mui/icons-material/MonitorHeartRounded";
import PublicRoundedIcon from "@mui/icons-material/PublicRounded";
import VpnKeyRoundedIcon from "@mui/icons-material/VpnKeyRounded";

import { ServerHealth, TokenLoginRequest } from "../models/api";
import { api } from "../services/api";
import { useSession } from "../state/SessionProvider";

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
  const [searchParams] = useSearchParams();
  const queryClient = useQueryClient();
  const { authOptions, error, session, setSessionSnapshot } = useSession();
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
  const pendingServer = session?.pending_server ?? null;
  const selectedTokenServer = servers.find((server) => server.id === tokenForm.server_id) ?? null;
  const authError = searchParams.get("authError");
  const redirectSignInEnabled = authOptions?.redirect_signin_enabled !== false;

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
                  Administrators publish the Teamwork Cloud preset catalog centrally. End users can see that server list before app login, choose a target TWC server, and then authenticate against the selected server through a real redirect-based auth flow.
                </Typography>
                <Button variant="outlined" color="inherit" startIcon={<MonitorHeartRoundedIcon />} onClick={() => queryClient.invalidateQueries({ queryKey: ["server-health"] })}>
                  Refresh Health
                </Button>
              </Stack>
            </Grid>
            <Grid item xs={12} lg={4}>
              <Paper sx={{ p: 3, borderRadius: 5, bgcolor: "rgba(7, 22, 39, 0.28)", color: "white" }}>
                <Stack spacing={2}>
                  <Typography variant="h5">Platform Summary</Typography>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label={`${servers.length} available presets`} sx={{ color: "white", borderColor: "rgba(255,255,255,0.22)" }} variant="outlined" />
                    <Chip label="Central admin catalog" sx={{ color: "white", borderColor: "rgba(255,255,255,0.22)" }} variant="outlined" />
                    <Chip label="User-scoped TWC auth" sx={{ color: "white", borderColor: "rgba(255,255,255,0.22)" }} variant="outlined" />
                  </Stack>
                  <Typography variant="body2" sx={{ color: "rgba(255,255,255,0.8)" }}>
                    TWC remains the authentication and authorization authority. Redirect sign-in binds the app session to the selected TWC server, while token sign-in remains available as a header-based fallback.
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
        {authError ? <Alert severity="error">{authError}</Alert> : null}
        {authOptions?.redirect_signin_message ? <Alert severity="warning">{authOptions.redirect_signin_message}</Alert> : null}
        {pendingServer ? (
          <Alert
            severity="info"
            action={
              <Button color="inherit" size="small" onClick={() => window.location.assign(api.signInUrl(pendingServer.id))} disabled={!redirectSignInEnabled}>
                Continue TWC Sign-In
              </Button>
            }
          >
            Selected server: {pendingServer.name}. Redirect sign-in uses that Teamwork Cloud server's authentication service and preserves the selected server through the callback. It does not rely on browser cookie reuse from another host.
          </Alert>
        ) : null}
        {error ? <Alert severity="warning">{error}</Alert> : null}

        <Grid container spacing={3}>
          <Grid item xs={12} lg={8}>
            <Stack spacing={2}>
              <Typography variant="h4">Teamwork Cloud Presets</Typography>
              <Typography variant="body2" color="text.secondary">
                Choose one enabled preset server before app authentication. Preset definitions are global app data, readable on this landing page without prior login, and managed centrally by administrators.
              </Typography>
              {serversQuery.isLoading ? (
                <Paper sx={{ p: 4, borderRadius: 5 }}>
                  <Typography color="text.secondary">Loading preset servers...</Typography>
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
                              <Stack spacing={1}>
                                <Box>
                                  <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                                    <Typography variant="h5">{server.name}</Typography>
                                    <Chip size="small" label="Preset" variant="outlined" />
                                  </Stack>
                                  <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                                    {server.base_url}
                                  </Typography>
                                </Box>
                              </Stack>
                              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                                <Chip label={`Version ${health?.version_hint ?? server.version}`} variant="outlined" />
                                <Chip label={`Order ${server.display_order}`} variant="outlined" />
                                <Chip label="TWC user auth" variant="outlined" />
                                <Chip label={health?.status ?? "probing"} color={healthColor(health?.status)} />
                                <Chip label={server.verify_tls ? "TLS verified" : "TLS relaxed"} variant="outlined" />
                              </Stack>
                              <Stack spacing={0.75}>
                                <Typography variant="body2" color="text.secondary">
                                  The selected preset server is established first. Redirect sign-in sends the browser to that Teamwork Cloud server's auth service, then the callback creates an app session bound to that same server.
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
                                  disabled={!redirectSignInEnabled}
                                >
                                  Sign In via TWC
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
                  <Typography variant="h5">No preset servers available</Typography>
                  <Typography variant="body1" color="text.secondary" sx={{ mt: 1 }}>
                    An administrator needs to publish at least one enabled Teamwork Cloud preset before users can sign in.
                  </Typography>
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
                    Preset servers are visible before login so users can choose the target Teamwork Cloud server first. Redirect sign-in completes only after the selected server's auth service redirects back to this app callback.
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Cross-host redirect login does not assume the browser shares Teamwork Cloud session cookies with this app host.
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Use TWC Token remains supported as the cross-host fallback because it is header-based. The backend validates that token against the selected Teamwork Cloud server before opening a workbench session.
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Preset server definitions are global and admin-managed. Users do not edit `.env` and do not create their own target servers on the landing page.
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