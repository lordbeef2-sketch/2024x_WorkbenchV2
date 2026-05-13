package com.twcworkbench.cameo.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.nomagic.magicdraw.core.Application;
import com.twcworkbench.cameo.config.PluginConfig;
import com.twcworkbench.cameo.model.BranchDeltaPayload;
import com.twcworkbench.cameo.model.BranchSnapshotPayload;

import java.io.File;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.time.Duration;
import java.time.format.DateTimeFormatter;

public class WorkbenchIngestClient {
    private final File pluginDirectory;
    private final PluginConfig config;
    private final ObjectMapper objectMapper;

    public WorkbenchIngestClient(File pluginDirectory, PluginConfig config) {
        this.pluginDirectory = pluginDirectory;
        this.config = config;
        this.objectMapper = new ObjectMapper();
    }

    public void publishSnapshot(BranchSnapshotPayload payload, String reason) throws IOException, InterruptedException {
        payload.exportReason = reason;
        if (config.hasWorkbenchIngestTarget()) {
            validateSnapshotForWorkbench(payload);
            postJson("/api/cache-ingest/branch-snapshots", payload);
            return;
        }
        writeLocal("snapshot", payload.projectId, payload.branchId, payload);
    }

    public void publishDelta(BranchDeltaPayload payload, String reason) throws IOException, InterruptedException {
        payload.exportReason = reason;
        if (config.hasWorkbenchIngestTarget()) {
            validateDeltaForWorkbench(payload);
            postJson("/api/cache-ingest/branch-deltas", payload);
            return;
        }
        writeLocal("delta", payload.projectId, payload.branchId, payload);
    }

    private void postJson(String path, Object payload) throws IOException, InterruptedException {
        byte[] body = objectMapper.writerWithDefaultPrettyPrinter().writeValueAsBytes(payload);
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(trimTrailingSlash(config.workbenchBaseUrl) + path))
                .timeout(Duration.ofSeconds(config.readTimeoutSeconds))
                .header("Authorization", "Bearer " + config.workbenchIngestToken)
                .header("Content-Type", "application/json")
                .header("User-Agent", "twc-workbench-cameo-plugin/0.1.0")
                .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                .build();

        HttpClient httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(config.connectTimeoutSeconds))
                .build();
        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        int statusCode = response.statusCode();
        if (statusCode < 200 || statusCode >= 300) {
            throw new IOException("Workbench ingest failed with status " + statusCode + ": " + response.body());
        }
        Application.getInstance().getGUILog().log("[INFO] Posted payload to Workbench ingest endpoint: " + path);
    }

    private void writeLocal(String prefix, String projectId, String branchId, Object payload) throws IOException {
        File outputDirectory = config.resolveOutputDirectory(pluginDirectory);
        String safeProject = sanitize(projectId);
        String safeBranch = sanitize(branchId);
        String timestamp = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss").format(java.time.LocalDateTime.now());
        File outputFile = new File(outputDirectory, prefix + "-" + safeProject + "-" + safeBranch + "-" + timestamp + ".json");
        Files.writeString(outputFile.toPath(), objectMapper.writerWithDefaultPrettyPrinter().writeValueAsString(payload), StandardCharsets.UTF_8);
        Application.getInstance().getGUILog().log("[INFO] Wrote local export payload: " + outputFile.getAbsolutePath());
    }

    private String trimTrailingSlash(String value) {
        return value.endsWith("/") ? value.substring(0, value.length() - 1) : value;
    }

    private String sanitize(String value) {
        if (value == null || value.isBlank()) {
            return "unknown";
        }
        return value.replaceAll("[^A-Za-z0-9._-]", "_");
    }

    private void validateSnapshotForWorkbench(BranchSnapshotPayload payload) throws IOException {
        validateCommonWorkbenchFields(payload.serverId, payload.serverUrl, payload.resourceId, payload.projectId, payload.branchId, payload.sourceUser);
    }

    private void validateDeltaForWorkbench(BranchDeltaPayload payload) throws IOException {
        validateCommonWorkbenchFields(payload.serverId, payload.serverUrl, payload.resourceId, payload.projectId, payload.branchId, payload.sourceUser);
    }

    private void validateCommonWorkbenchFields(
            String serverId,
            String serverUrl,
            String resourceId,
            String projectId,
            String branchId,
            String sourceUser
    ) throws IOException {
        if (isBlank(serverId) || (!isBlank(serverUrl) && serverId.equals(serverUrl))) {
            throw new IOException("Workbench ingest requires config/workbench-plugin.properties metadata.serverId to match the Workbench server profile id.");
        }
        if (isBlank(resourceId)) {
            throw new IOException("Workbench ingest requires a resolvable TWC resource ID. Open a remote TWC project or set metadata.resourceId.");
        }
        if (isBlank(projectId)) {
            throw new IOException("Workbench ingest requires a project ID. The plugin now uses the TWC resource ID as the Workbench project key.");
        }
        if (isBlank(branchId)) {
            throw new IOException("Workbench ingest requires a branch ID.");
        }
        if (isBlank(sourceUser)) {
            throw new IOException("Workbench ingest requires the active Cameo/TWC user identity.");
        }
    }

    private boolean isBlank(String value) {
        return value == null || value.isBlank();
    }
}
