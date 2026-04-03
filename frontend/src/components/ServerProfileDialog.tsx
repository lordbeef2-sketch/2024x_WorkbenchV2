import { useEffect, useState } from "react";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Button,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/GridLegacy";

import { ServerProfile, ServerProfileInput, TWCVersion } from "../models/api";

interface ServerProfileDialogProps {
  open: boolean;
  initialValue?: ServerProfile | null;
  onClose: () => void;
  onSubmit: (value: ServerProfileInput) => Promise<void> | void;
}

function buildDefaultCallbackUrl() {
  if (typeof window === "undefined") {
    return "http://localhost:8000/api/auth/callback";
  }
  return `${window.location.protocol}//${window.location.hostname}:8000/api/auth/callback`;
}

function createDefaultProfile(): ServerProfileInput {
  return {
    name: "",
    base_url: "",
    auth_url: "",
    version: "auto",
    client_id: "",
    callback_url: buildDefaultCallbackUrl(),
    verify_tls: true,
    ca_bundle_path: null,
    favorite: false,
  };
}

export default function ServerProfileDialog({ open, initialValue, onClose, onSubmit }: ServerProfileDialogProps) {
  const [form, setForm] = useState<ServerProfileInput>(createDefaultProfile());
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (!initialValue) {
      setForm(createDefaultProfile());
      return;
    }
    setForm({
      name: initialValue.name,
      base_url: initialValue.base_url,
      auth_url: initialValue.auth_url,
      version: initialValue.version,
      client_id: initialValue.client_id,
      callback_url: initialValue.callback_url,
      verify_tls: initialValue.verify_tls,
      ca_bundle_path: initialValue.ca_bundle_path,
      favorite: initialValue.favorite,
    });
  }, [initialValue, open]);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await onSubmit({
        ...form,
        base_url: form.base_url.trim(),
        auth_url: form.auth_url.trim(),
        callback_url: form.callback_url.trim(),
        client_id: form.client_id.trim(),
        ca_bundle_path: form.ca_bundle_path?.trim() || null,
      });
      onClose();
    } finally {
      setSubmitting(false);
    }
  };

  const setField = <K extends keyof ServerProfileInput>(key: K, value: ServerProfileInput[K]) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>{initialValue ? "Edit Teamwork Cloud Server" : "Add Teamwork Cloud Server"}</DialogTitle>
      <DialogContent>
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          <Grid item xs={12} md={6}>
            <TextField
              label="Display Name"
              value={form.name}
              onChange={(event) => setField("name", event.target.value)}
              fullWidth
              required
            />
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField
              select
              label="Version"
              value={form.version}
              onChange={(event) => setField("version", event.target.value as TWCVersion)}
              fullWidth
            >
              <MenuItem value="auto">Auto Detect</MenuItem>
              <MenuItem value="2022x">2022x</MenuItem>
              <MenuItem value="2024x">2024x</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12}>
            <TextField
              label="Base URL"
              value={form.base_url}
              onChange={(event) => setField("base_url", event.target.value)}
              placeholder="https://twc.company.example"
              fullWidth
              required
            />
          </Grid>
          <Grid item xs={12}>
            <TextField
              label="Authentication URL"
              value={form.auth_url}
              onChange={(event) => setField("auth_url", event.target.value)}
              placeholder="https://auth.company.example/realms/teamwork/protocol/openid-connect/auth"
              fullWidth
              required
            />
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField
              label="Client ID"
              value={form.client_id}
              onChange={(event) => setField("client_id", event.target.value)}
              fullWidth
              required
            />
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField
              label="Callback URL"
              value={form.callback_url}
              onChange={(event) => setField("callback_url", event.target.value)}
              fullWidth
              required
            />
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField
              label="Custom CA Bundle Path"
              value={form.ca_bundle_path ?? ""}
              onChange={(event) => setField("ca_bundle_path", event.target.value || null)}
              placeholder="C:\\certs\\twc-ca.pem"
              fullWidth
            />
          </Grid>
          <Grid item xs={12} md={6}>
            <Stack
              direction="row"
              spacing={2}
              alignItems="center"
              sx={{ px: 2, py: 1.5, borderRadius: 3, border: "1px solid", borderColor: "divider", height: "100%" }}
            >
              <Switch checked={form.verify_tls} onChange={(event) => setField("verify_tls", event.target.checked)} />
              <div>
                <Typography fontWeight={600}>Certificate Validation</Typography>
                <Typography variant="body2" color="text.secondary">
                  Enforce TLS verification and optionally pin a custom CA bundle.
                </Typography>
              </div>
            </Stack>
          </Grid>
          <Grid item xs={12}>
            <Stack
              direction="row"
              spacing={2}
              alignItems="center"
              sx={{ px: 2, py: 1.5, borderRadius: 3, border: "1px solid", borderColor: "divider" }}
            >
              <Switch checked={form.favorite} onChange={(event) => setField("favorite", event.target.checked)} />
              <div>
                <Typography fontWeight={600}>Favorite Server</Typography>
                <Typography variant="body2" color="text.secondary">
                  Favorite servers surface to the top of the landing page and quick actions.
                </Typography>
              </div>
            </Stack>
          </Grid>
        </Grid>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 3 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSubmit} disabled={submitting || !form.name || !form.base_url || !form.auth_url || !form.client_id}>
          {initialValue ? "Save Changes" : "Create Server"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}