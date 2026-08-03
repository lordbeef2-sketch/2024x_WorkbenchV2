// Created by: Raymond Reeves Engineering Tech 4 2026
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
  Accordion,
  AccordionDetails,
  AccordionSummary,
} from "@mui/material";
import Grid from "@mui/material/GridLegacy";
import ExpandMoreRoundedIcon from "@mui/icons-material/ExpandMoreRounded";

import { ServerProfile, ServerProfileInput, TWCVersion } from "../models/api";

interface ServerProfileDialogProps {
  open: boolean;
  initialValue?: ServerProfile | null;
  defaultDisplayOrder?: number;
  onClose: () => void;
  onSubmit: (value: ServerProfileInput) => Promise<void> | void;
}

function createDefaultProfile(defaultDisplayOrder = 0): ServerProfileInput {
  return {
    id: "",
    name: "",
    base_url: "",
    version: "2024x",
    verify_tls: true,
    ca_bundle_path: null,
    enabled: true,
    display_order: defaultDisplayOrder,
    auth_discovery_url: null,
    auth_authorize_url: null,
    auth_token_url: null,
    auth_login_path: null,
    auth_login_port: null,
    auth_token_path: null,
    auth_client_id: null,
    auth_client_secret: null,
    auth_scope: "openid",
    auth_return_url_parameter: "redirect_uri",
    oslc_base_url: null,
    oslc_consumer_key: null,
    oslc_consumer_secret: null,
    oslc_callback_url: null,
  };
}

export default function ServerProfileDialog({ open, initialValue, defaultDisplayOrder = 0, onClose, onSubmit }: ServerProfileDialogProps) {
  const [form, setForm] = useState<ServerProfileInput>(createDefaultProfile(defaultDisplayOrder));
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }
    if (!initialValue) {
      setForm(createDefaultProfile(defaultDisplayOrder));
      return;
    }
    setForm({
      id: initialValue.id,
      name: initialValue.name,
      base_url: initialValue.base_url,
      version: initialValue.version,
      verify_tls: initialValue.verify_tls,
      ca_bundle_path: initialValue.ca_bundle_path,
      enabled: initialValue.enabled,
      display_order: initialValue.display_order,
      auth_discovery_url: initialValue.auth_discovery_url,
      auth_authorize_url: initialValue.auth_authorize_url,
      auth_token_url: initialValue.auth_token_url,
      auth_login_path: initialValue.auth_login_path,
      auth_login_port: initialValue.auth_login_port,
      auth_token_path: initialValue.auth_token_path,
      auth_client_id: initialValue.auth_client_id,
      auth_client_secret: null,
      auth_scope: initialValue.auth_scope ?? "openid",
      auth_return_url_parameter: initialValue.auth_return_url_parameter ?? "redirect_uri",
      oslc_base_url: initialValue.oslc_base_url,
      oslc_consumer_key: initialValue.oslc_consumer_key,
      oslc_consumer_secret: null,
      oslc_callback_url: initialValue.oslc_callback_url,
    });
  }, [defaultDisplayOrder, initialValue, open]);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await onSubmit({
        ...form,
        id: form.id?.trim() || undefined,
        base_url: form.base_url.trim(),
        ca_bundle_path: form.ca_bundle_path?.trim() || null,
        auth_discovery_url: form.auth_discovery_url?.trim() || null,
        auth_authorize_url: form.auth_authorize_url?.trim() || null,
        auth_token_url: form.auth_token_url?.trim() || null,
        auth_login_path: form.auth_login_path?.trim() || null,
        auth_token_path: form.auth_token_path?.trim() || null,
        auth_client_id: form.auth_client_id?.trim() || null,
        auth_client_secret: form.auth_client_secret?.trim() || null,
        auth_scope: form.auth_scope?.trim() || null,
        auth_return_url_parameter: form.auth_return_url_parameter?.trim() || null,
        oslc_base_url: form.oslc_base_url?.trim() || null,
        oslc_consumer_key: form.oslc_consumer_key?.trim() || null,
        oslc_consumer_secret: form.oslc_consumer_secret?.trim() || null,
        oslc_callback_url: form.oslc_callback_url?.trim() || null,
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
      <DialogTitle>{initialValue ? "Edit Workbench Server" : "Add Workbench Server"}</DialogTitle>
      <DialogContent>
        <Grid container spacing={2} sx={{ mt: 0.5 }}>
          {!initialValue ? (
            <Grid item xs={12} md={6}>
              <TextField
                label="Server Key"
                value={form.id ?? ""}
                onChange={(event) => setField("id", event.target.value.trim())}
                helperText="This becomes the Cameo plugin metadata.serverId. Example: prod-2024x"
                fullWidth
                required
              />
            </Grid>
          ) : (
            <Grid item xs={12} md={6}>
              <TextField
                label="Server Key"
                value={initialValue.id}
                helperText="Copy this into the Cameo plugin as metadata.serverId."
                fullWidth
                InputProps={{ readOnly: true }}
              />
            </Grid>
          )}
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
              <MenuItem value="2024x">2024x</MenuItem>
              <MenuItem value="2022x">2022x</MenuItem>
            </TextField>
          </Grid>
          <Grid item xs={12}>
            <TextField
              label="Teamwork Cloud Base URL"
              value={form.base_url}
              onChange={(event) => setField("base_url", event.target.value)}
              placeholder="https://twc.company.example:8111"
              fullWidth
              required
            />
          </Grid>
          <Grid item xs={12}>
            <Accordion variant="outlined" disableGutters>
              <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                <Typography fontWeight={700}>TWC AuthServer / SSO overrides</Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Grid container spacing={2}>
                  <Grid item xs={12} md={6}>
                    <TextField label="OIDC discovery URL" value={form.auth_discovery_url ?? ""} onChange={(event) => setField("auth_discovery_url", event.target.value || null)} fullWidth />
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <TextField label="Authorize URL" value={form.auth_authorize_url ?? ""} onChange={(event) => setField("auth_authorize_url", event.target.value || null)} fullWidth />
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <TextField label="Token URL" value={form.auth_token_url ?? ""} onChange={(event) => setField("auth_token_url", event.target.value || null)} fullWidth />
                  </Grid>
                  <Grid item xs={12} md={3}>
                    <TextField
                      label="Login port"
                      type="number"
                      value={form.auth_login_port ?? ""}
                      onChange={(event) => setField("auth_login_port", event.target.value ? Number.parseInt(event.target.value, 10) : null)}
                      fullWidth
                    />
                  </Grid>
                  <Grid item xs={12} md={3}>
                    <TextField label="Scope" value={form.auth_scope ?? ""} onChange={(event) => setField("auth_scope", event.target.value || null)} fullWidth />
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <TextField label="Client ID" value={form.auth_client_id ?? ""} onChange={(event) => setField("auth_client_id", event.target.value || null)} fullWidth />
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <TextField label="Client secret" type="password" value={form.auth_client_secret ?? ""} onChange={(event) => setField("auth_client_secret", event.target.value || null)} helperText="Saved on submit; not shown again after reload." fullWidth />
                  </Grid>
                </Grid>
              </AccordionDetails>
            </Accordion>
          </Grid>
          <Grid item xs={12}>
            <Accordion variant="outlined" disableGutters>
              <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                <Typography fontWeight={700}>OSLC / RealSwagger overrides</Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Grid container spacing={2}>
                  <Grid item xs={12} md={6}>
                    <TextField label="OSLC/OSMC Base URL" value={form.oslc_base_url ?? ""} onChange={(event) => setField("oslc_base_url", event.target.value || null)} helperText="Leave blank to use the TWC Base URL for /osmc requests." fullWidth />
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <TextField label="OSLC callback URL" value={form.oslc_callback_url ?? ""} onChange={(event) => setField("oslc_callback_url", event.target.value || null)} fullWidth />
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <TextField label="OSLC consumer key" value={form.oslc_consumer_key ?? ""} onChange={(event) => setField("oslc_consumer_key", event.target.value || null)} fullWidth />
                  </Grid>
                  <Grid item xs={12} md={6}>
                    <TextField label="OSLC consumer secret" type="password" value={form.oslc_consumer_secret ?? ""} onChange={(event) => setField("oslc_consumer_secret", event.target.value || null)} helperText="Saved on submit; not shown again after reload." fullWidth />
                  </Grid>
                </Grid>
              </AccordionDetails>
            </Accordion>
          </Grid>
          <Grid item xs={12}>
            <Stack
              spacing={0.5}
              sx={{ px: 2, py: 1.75, borderRadius: 3, border: "1px solid", borderColor: "divider", bgcolor: "background.default" }}
            >
              <Typography fontWeight={600}>TWC Authentication</Typography>
              <Typography variant="body2" color="text.secondary">
                This profile uses Teamwork Cloud as the authentication authority. Operators can either reuse an existing TWC browser session or provide a user-scoped TWC token at sign-in time.
              </Typography>
            </Stack>
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
          <Grid item xs={12} md={6}>
            <TextField
              label="Display Order"
              type="number"
              value={form.display_order}
              onChange={(event) => setField("display_order", Math.max(0, Number.parseInt(event.target.value, 10) || 0))}
              fullWidth
              inputProps={{ min: 0 }}
            />
          </Grid>
          <Grid item xs={12} md={6}>
            <Stack
              direction="row"
              spacing={2}
              alignItems="center"
              sx={{ px: 2, py: 1.5, borderRadius: 3, border: "1px solid", borderColor: "divider" }}
            >
              <Switch checked={form.enabled} onChange={(event) => setField("enabled", event.target.checked)} />
              <div>
                <Typography fontWeight={600}>Preset Enabled</Typography>
                <Typography variant="body2" color="text.secondary">
                  Disabled servers remain visible to administrators but are hidden from normal user sign-in flows.
                </Typography>
              </div>
            </Stack>
          </Grid>
        </Grid>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 3 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant="contained"
          onClick={handleSubmit}
          disabled={submitting || !form.name || !form.base_url || (!initialValue && !form.id)}
        >
          {initialValue ? "Save Changes" : "Create Server"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
