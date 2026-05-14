package com.twcworkbench.cameo.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.nomagic.magicdraw.core.Application;
import com.twcworkbench.cameo.config.PluginConfig;
import com.twcworkbench.cameo.model.BranchDeltaPayload;
import com.twcworkbench.cameo.model.BranchSnapshotPayload;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.security.GeneralSecurityException;
import java.security.SecureRandom;

import javax.net.ssl.SSLContext;
import javax.net.ssl.SSLParameters;
import javax.net.ssl.TrustManager;
import javax.net.ssl.X509TrustManager;
import java.security.cert.X509Certificate;
import java.util.function.Consumer;

public class WorkbenchIngestClient {
    private final PluginConfig config;
    private final ObjectMapper objectMapper;

    public WorkbenchIngestClient(PluginConfig config) {
        this.config = config;
        this.objectMapper = new ObjectMapper();
    }

    public void publishSnapshot(BranchSnapshotPayload payload, String reason) throws IOException, InterruptedException {
        publishSnapshot(payload, reason, null);
    }

    public void publishSnapshot(BranchSnapshotPayload payload, String reason, Consumer<String> progress) throws IOException, InterruptedException {
        payload.exportReason = reason;
        requireWorkbenchIngestTarget();
        validateSnapshotForWorkbench(payload);
        postJson("/api/cache-ingest/branch-snapshots", payload, progress);
    }

    public void publishDelta(BranchDeltaPayload payload, String reason) throws IOException, InterruptedException {
        publishDelta(payload, reason, null);
    }

    public void publishDelta(BranchDeltaPayload payload, String reason, Consumer<String> progress) throws IOException, InterruptedException {
        payload.exportReason = reason;
        requireWorkbenchIngestTarget();
        validateDeltaForWorkbench(payload);
        postJson("/api/cache-ingest/branch-deltas", payload, progress);
    }

    private void postJson(String path, Object payload, Consumer<String> progress) throws IOException, InterruptedException {
        report(progress, "Serializing snapshot payload for Workbench...");
        byte[] body = objectMapper.writerWithDefaultPrettyPrinter().writeValueAsBytes(payload);
        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(trimTrailingSlash(config.workbenchBaseUrl) + path))
                .timeout(Duration.ofSeconds(config.readTimeoutSeconds))
                .header("Authorization", "Bearer " + config.workbenchIngestToken)
                .header("Content-Type", "application/json")
                .header("User-Agent", "twc-workbench-cameo-plugin/0.1.0")
                .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                .build();

        HttpClient httpClient = createHttpClient();
        report(progress, "Posting payload to Workbench: " + path);
        HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
        int statusCode = response.statusCode();
        if (statusCode < 200 || statusCode >= 300) {
            throw new IOException("Workbench ingest failed with status " + statusCode + ": " + response.body());
        }
        report(progress, "Workbench ingest accepted the payload.");
        Application.getInstance().getGUILog().log("[INFO] Posted payload to Workbench ingest endpoint: " + path);
    }

    private HttpClient createHttpClient() throws IOException {
        HttpClient.Builder builder = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(config.connectTimeoutSeconds));
        if (config.insecureTls) {
            try {
                builder.sslContext(buildInsecureSslContext());
                SSLParameters sslParameters = new SSLParameters();
                sslParameters.setEndpointIdentificationAlgorithm("");
                builder.sslParameters(sslParameters);
            }
            catch (GeneralSecurityException exception) {
                throw new IOException("Failed to initialize insecure TLS mode for Workbench ingest.", exception);
            }
        }
        return builder.build();
    }

    private SSLContext buildInsecureSslContext() throws GeneralSecurityException {
        TrustManager[] trustManagers = new TrustManager[]{
                new X509TrustManager() {
                    @Override
                    public void checkClientTrusted(X509Certificate[] chain, String authType) {
                    }

                    @Override
                    public void checkServerTrusted(X509Certificate[] chain, String authType) {
                    }

                    @Override
                    public X509Certificate[] getAcceptedIssuers() {
                        return new X509Certificate[0];
                    }
                }
        };
        SSLContext sslContext = SSLContext.getInstance("TLS");
        sslContext.init(null, trustManagers, new SecureRandom());
        return sslContext;
    }

    private String trimTrailingSlash(String value) {
        return value.endsWith("/") ? value.substring(0, value.length() - 1) : value;
    }

    private void requireWorkbenchIngestTarget() throws IOException {
        if (!config.hasWorkbenchIngestTarget()) {
            throw new IOException("Workbench Base URL and Ingest Bearer Token are required. Configure them from TWC Workbench -> Configure Workbench Connection...");
        }
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
            throw new IOException("Workbench ingest requires a resolvable TWC resource ID from the active remote TWC project.");
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

    private void report(Consumer<String> progress, String message) {
        if (progress != null) {
            progress.accept(message);
        }
    }
}
