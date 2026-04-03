import {
  Box,
  Button,
  Chip,
  LinearProgress,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import CancelRoundedIcon from "@mui/icons-material/CancelRounded";
import DownloadRoundedIcon from "@mui/icons-material/DownloadRounded";

import { JobRecord } from "../models/api";
import { api } from "../services/api";
import { formatDate, jobStatusColor } from "../utils/format";

interface JobStripProps {
  jobs: JobRecord[];
  onCancel: (jobId: string) => void;
}

export default function JobStrip({ jobs, onCancel }: JobStripProps) {
  if (!jobs.length) {
    return (
      <Paper sx={{ p: 2.5, borderRadius: 4 }}>
        <Typography fontWeight={600}>Job Center</Typography>
        <Typography variant="body2" color="text.secondary">
          No background work is running. Simulation, publish, and export jobs will appear here with live progress.
        </Typography>
      </Paper>
    );
  }

  return (
    <Stack spacing={1.5}>
      {jobs.map((job) => (
        <Paper key={job.id} sx={{ p: 2, borderRadius: 4 }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} justifyContent="space-between">
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                <Typography fontWeight={700}>{job.title}</Typography>
                <Chip size="small" color={jobStatusColor(job.status)} label={job.status} />
                <Chip size="small" variant="outlined" label={job.job_type} />
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                {job.message} · Updated {formatDate(job.updated_at)}
              </Typography>
              <LinearProgress variant="determinate" value={job.progress} sx={{ mt: 1.5, borderRadius: 999, height: 8 }} />
            </Box>
            <Stack direction="row" spacing={1} alignItems="center">
              {job.artifact_path ? (
                <Button component="a" href={api.jobArtifactUrl(job.id)} target="_blank" rel="noreferrer" startIcon={<DownloadRoundedIcon />}>
                  Artifact
                </Button>
              ) : null}
              {(job.status === "running" || job.status === "pending") && !job.cancel_requested ? (
                <Button color="warning" onClick={() => onCancel(job.id)} startIcon={<CancelRoundedIcon />}>
                  Cancel
                </Button>
              ) : null}
            </Stack>
          </Stack>
        </Paper>
      ))}
    </Stack>
  );
}