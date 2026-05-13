package com.twcworkbench.cameo.config;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.Properties;

public class PluginConfig {
    private static final String CONFIG_RELATIVE_PATH = "config/workbench-plugin.properties";

    public final File configFile;
    public String workbenchBaseUrl;
    public String workbenchIngestToken;
    public String exportOutputDir;
    public boolean snapshotOnOpen;
    public boolean snapshotOnSave;
    public boolean deltaOnClose;
    public int connectTimeoutSeconds;
    public int readTimeoutSeconds;
    public String workspaceIdOverride;
    public String serverIdOverride;
    public String resourceIdOverride;

    private PluginConfig(File configFile, Properties properties) {
        this.configFile = configFile;
        this.workbenchBaseUrl = trimToNull(properties.getProperty("workbench.baseUrl"));
        this.workbenchIngestToken = trimToNull(properties.getProperty("workbench.ingestToken"));
        this.exportOutputDir = properties.getProperty("export.outputDir", "exports").trim();
        this.snapshotOnOpen = Boolean.parseBoolean(properties.getProperty("capture.snapshotOnOpen", "true"));
        this.snapshotOnSave = Boolean.parseBoolean(properties.getProperty("capture.snapshotOnSave", "true"));
        this.deltaOnClose = Boolean.parseBoolean(properties.getProperty("capture.deltaOnClose", "true"));
        this.connectTimeoutSeconds = Integer.parseInt(properties.getProperty("http.connectTimeoutSeconds", "15"));
        this.readTimeoutSeconds = Integer.parseInt(properties.getProperty("http.readTimeoutSeconds", "60"));
        this.workspaceIdOverride = trimToNull(properties.getProperty("metadata.workspaceId"));
        this.serverIdOverride = trimToNull(properties.getProperty("metadata.serverId"));
        this.resourceIdOverride = trimToNull(properties.getProperty("metadata.resourceId"));
    }

    public static PluginConfig load(File pluginDirectory) {
        File configFile = new File(pluginDirectory, CONFIG_RELATIVE_PATH);
        Properties properties = new Properties();
        if (configFile.isFile()) {
            try (FileInputStream fileInputStream = new FileInputStream(configFile)) {
                properties.load(fileInputStream);
            }
            catch (IOException exception) {
                throw new IllegalStateException("Failed to load plugin config from " + configFile.getAbsolutePath(), exception);
            }
        }
        return new PluginConfig(configFile, properties);
    }

    public boolean hasWorkbenchIngestTarget() {
        return workbenchBaseUrl != null && workbenchIngestToken != null;
    }

    public synchronized void applyEditableSettings(
            String workbenchBaseUrl,
            String workbenchIngestToken,
            String exportOutputDir,
            boolean snapshotOnOpen,
            boolean snapshotOnSave,
            boolean deltaOnClose,
            int connectTimeoutSeconds,
            int readTimeoutSeconds,
            String workspaceIdOverride,
            String serverIdOverride,
            String resourceIdOverride
    ) {
        this.workbenchBaseUrl = trimToNull(workbenchBaseUrl);
        this.workbenchIngestToken = trimToNull(workbenchIngestToken);
        this.exportOutputDir = defaultIfBlank(exportOutputDir, "exports");
        this.snapshotOnOpen = snapshotOnOpen;
        this.snapshotOnSave = snapshotOnSave;
        this.deltaOnClose = deltaOnClose;
        this.connectTimeoutSeconds = connectTimeoutSeconds;
        this.readTimeoutSeconds = readTimeoutSeconds;
        this.workspaceIdOverride = trimToNull(workspaceIdOverride);
        this.serverIdOverride = trimToNull(serverIdOverride);
        this.resourceIdOverride = trimToNull(resourceIdOverride);
    }

    public synchronized void save() {
        Properties properties = new Properties();
        properties.setProperty("workbench.baseUrl", emptyIfNull(workbenchBaseUrl));
        properties.setProperty("workbench.ingestToken", emptyIfNull(workbenchIngestToken));
        properties.setProperty("export.outputDir", defaultIfBlank(exportOutputDir, "exports"));
        properties.setProperty("capture.snapshotOnOpen", Boolean.toString(snapshotOnOpen));
        properties.setProperty("capture.snapshotOnSave", Boolean.toString(snapshotOnSave));
        properties.setProperty("capture.deltaOnClose", Boolean.toString(deltaOnClose));
        properties.setProperty("http.connectTimeoutSeconds", Integer.toString(connectTimeoutSeconds));
        properties.setProperty("http.readTimeoutSeconds", Integer.toString(readTimeoutSeconds));
        properties.setProperty("metadata.workspaceId", emptyIfNull(workspaceIdOverride));
        properties.setProperty("metadata.serverId", emptyIfNull(serverIdOverride));
        properties.setProperty("metadata.resourceId", emptyIfNull(resourceIdOverride));

        File parent = configFile.getParentFile();
        if (parent != null && !parent.exists() && !parent.mkdirs()) {
            throw new IllegalStateException("Failed to create config directory: " + parent.getAbsolutePath());
        }
        try (FileOutputStream outputStream = new FileOutputStream(configFile)) {
            properties.store(outputStream, "TWC Workbench Cameo Plugin");
        }
        catch (IOException exception) {
            throw new IllegalStateException("Failed to save plugin config to " + configFile.getAbsolutePath(), exception);
        }
    }

    public File resolveOutputDirectory(File pluginDirectory) {
        File outputDirectory = new File(pluginDirectory, exportOutputDir);
        if (!outputDirectory.exists() && !outputDirectory.mkdirs()) {
            throw new IllegalStateException("Failed to create export directory: " + outputDirectory.getAbsolutePath());
        }
        return outputDirectory;
    }

    private static String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private static String defaultIfBlank(String value, String fallback) {
        String trimmed = value == null ? "" : value.trim();
        return trimmed.isEmpty() ? fallback : trimmed;
    }

    private static String emptyIfNull(String value) {
        return value == null ? "" : value;
    }
}
