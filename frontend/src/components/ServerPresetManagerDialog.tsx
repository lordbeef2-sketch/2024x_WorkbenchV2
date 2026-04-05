import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Card,
  CardContent,
  Chip,
  Dialog,
  DialogContent,
  DialogTitle,
  IconButton,
  Stack,
  Typography,
} from "@mui/material";
import AddRoundedIcon from "@mui/icons-material/AddRounded";
import ArrowDownwardRoundedIcon from "@mui/icons-material/ArrowDownwardRounded";
import ArrowUpwardRoundedIcon from "@mui/icons-material/ArrowUpwardRounded";
import DeleteOutlineRoundedIcon from "@mui/icons-material/DeleteOutlineRounded";
import EditRoundedIcon from "@mui/icons-material/EditRounded";

import { ServerProfile, ServerProfileInput } from "../models/api";
import { api } from "../services/api";
import { formatDate } from "../utils/format";
import ServerProfileDialog from "./ServerProfileDialog";

interface ServerPresetManagerDialogProps {
  open: boolean;
  onClose: () => void;
  csrfToken: string;
}

function errorMessage(caught: unknown): string {
  return caught instanceof Error ? caught.message : "The request failed.";
}

export default function ServerPresetManagerDialog({ open, onClose, csrfToken }: ServerPresetManagerDialogProps) {
  const queryClient = useQueryClient();
  const [banner, setBanner] = useState<{ severity: "success" | "error"; message: string } | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingServer, setEditingServer] = useState<ServerProfile | null>(null);

  const serversQuery = useQuery({
    queryKey: ["managed-servers"],
    queryFn: api.listManagedServers,
    enabled: open,
  });

  const createOrUpdateMutation = useMutation({
    mutationFn: async ({ serverId, payload }: { serverId?: string; payload: ServerProfileInput }) => {
      if (serverId) {
        return api.updateServer(serverId, payload, csrfToken);
      }
      return api.createServer(payload, csrfToken);
    },
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ["managed-servers"] });
      await queryClient.invalidateQueries({ queryKey: ["servers"] });
      await queryClient.invalidateQueries({ queryKey: ["server-health"] });
      setBanner({
        severity: "success",
        message: variables.serverId ? "Preset server updated." : "Preset server created.",
      });
      setEditingServer(null);
    },
    onError: (caught) => setBanner({ severity: "error", message: errorMessage(caught) }),
  });

  const deleteMutation = useMutation({
    mutationFn: (serverId: string) => api.deleteServer(serverId, csrfToken),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["managed-servers"] });
      await queryClient.invalidateQueries({ queryKey: ["servers"] });
      await queryClient.invalidateQueries({ queryKey: ["server-health"] });
      setBanner({ severity: "success", message: "Preset server deleted." });
    },
    onError: (caught) => setBanner({ severity: "error", message: errorMessage(caught) }),
  });

  const reorderMutation = useMutation({
    mutationFn: (serverIds: string[]) => api.reorderServers(serverIds, csrfToken),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["managed-servers"] });
      await queryClient.invalidateQueries({ queryKey: ["servers"] });
    },
    onError: (caught) => setBanner({ severity: "error", message: errorMessage(caught) }),
  });

  const servers = serversQuery.data ?? [];

  const moveServer = async (serverId: string, offset: -1 | 1) => {
    const index = servers.findIndex((server) => server.id === serverId);
    const targetIndex = index + offset;
    if (index < 0 || targetIndex < 0 || targetIndex >= servers.length) {
      return;
    }

    const next = [...servers];
    const [server] = next.splice(index, 1);
    next.splice(targetIndex, 0, server);
    await reorderMutation.mutateAsync(next.map((item) => item.id));
  };

  return (
    <>
      <Dialog open={open} onClose={onClose} fullWidth maxWidth="lg">
        <DialogTitle>Manage Preset Teamwork Cloud Servers</DialogTitle>
        <DialogContent>
          <Stack spacing={2.5} sx={{ py: 1 }}>
            {banner ? <Alert severity={banner.severity}>{banner.message}</Alert> : null}
            <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={1.5}>
              <Typography variant="body2" color="text.secondary">
                Preset servers are global. Administrators can add, edit, disable, delete, and reorder them without restarting the app. Regular users only see enabled presets on the landing page.
              </Typography>
              <Button
                variant="contained"
                startIcon={<AddRoundedIcon />}
                onClick={() => {
                  setEditingServer(null);
                  setEditorOpen(true);
                }}
              >
                Add Preset
              </Button>
            </Stack>

            {serversQuery.isLoading ? (
              <Alert severity="info">Loading preset servers...</Alert>
            ) : servers.length ? (
              <Stack spacing={1.5}>
                {servers.map((server, index) => (
                  <Card key={server.id} sx={{ borderRadius: 4 }}>
                    <CardContent>
                      <Stack spacing={1.5}>
                        <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" spacing={2}>
                          <Box>
                            <Typography variant="h6">{server.name}</Typography>
                            <Typography variant="body2" color="text.secondary">
                              {server.base_url}
                            </Typography>
                          </Box>
                          <Stack direction="row" spacing={0.5} alignItems="center">
                            <IconButton onClick={() => void moveServer(server.id, -1)} disabled={index === 0 || reorderMutation.isPending}>
                              <ArrowUpwardRoundedIcon fontSize="small" />
                            </IconButton>
                            <IconButton onClick={() => void moveServer(server.id, 1)} disabled={index === servers.length - 1 || reorderMutation.isPending}>
                              <ArrowDownwardRoundedIcon fontSize="small" />
                            </IconButton>
                            <IconButton
                              onClick={() => {
                                setEditingServer(server);
                                setEditorOpen(true);
                              }}
                            >
                              <EditRoundedIcon fontSize="small" />
                            </IconButton>
                            <IconButton
                              color="error"
                              onClick={() => {
                                if (window.confirm(`Delete preset server ${server.name}?`)) {
                                  deleteMutation.mutate(server.id);
                                }
                              }}
                            >
                              <DeleteOutlineRoundedIcon fontSize="small" />
                            </IconButton>
                          </Stack>
                        </Stack>

                        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                          <Chip label={`Order ${server.display_order}`} variant="outlined" />
                          <Chip label={`Version ${server.version}`} variant="outlined" />
                          <Chip label={server.verify_tls ? "TLS verified" : "TLS relaxed"} variant="outlined" />
                          <Chip label={server.enabled ? "Enabled" : "Disabled"} color={server.enabled ? "success" : "default"} />
                        </Stack>

                        <Typography variant="body2" color="text.secondary">
                          Updated {formatDate(server.updated_at)}
                        </Typography>
                      </Stack>
                    </CardContent>
                  </Card>
                ))}
              </Stack>
            ) : (
              <Alert severity="warning">No preset servers exist yet. Add one to expose a Teamwork Cloud sign-in option.</Alert>
            )}
          </Stack>
        </DialogContent>
      </Dialog>

      <ServerProfileDialog
        open={editorOpen}
        initialValue={editingServer}
        defaultDisplayOrder={servers.length}
        onClose={() => {
          setEditorOpen(false);
          setEditingServer(null);
        }}
        onSubmit={async (payload) => {
          await createOrUpdateMutation.mutateAsync({
            serverId: editingServer?.id,
            payload,
          });
        }}
      />
    </>
  );
}