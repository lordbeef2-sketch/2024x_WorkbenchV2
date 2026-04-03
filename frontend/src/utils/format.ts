import { CapabilityState, JobStatus } from "../models/api";

export function formatDate(value?: string | null): string {
  if (!value) {
    return "-";
  }
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export function formatBytes(size: number): string {
  if (size < 1024) {
    return `${size} B`;
  }
  if (size < 1024 * 1024) {
    return `${(size / 1024).toFixed(1)} KB`;
  }
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function capabilityColor(state: CapabilityState): "success" | "warning" | "default" | "error" {
  if (state === "ready") {
    return "success";
  }
  if (state === "restricted") {
    return "warning";
  }
  if (state === "not_available") {
    return "error";
  }
  return "default";
}

export function jobStatusColor(status: JobStatus): "success" | "warning" | "default" | "error" | "info" {
  if (status === "succeeded") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  if (status === "cancelled") {
    return "warning";
  }
  if (status === "running") {
    return "info";
  }
  return "default";
}