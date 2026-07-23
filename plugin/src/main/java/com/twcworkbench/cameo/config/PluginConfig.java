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
    public boolean snapshotOnOpen;
    public boolean snapshotOnSave;
    public boolean insecureTls;
    public int connectTimeoutSeconds;
    public int readTimeoutSeconds;
    public String serverIdOverride;

    private PluginConfig(File configFile, Properties properties) {
        this.configFile = configFile;
        this.workbenchBaseUrl = trimToNull(properties.getProperty("workbench.baseUrl"));
        this.workbenchIngestToken = trimToNull(properties.getProperty("workbench.ingestToken"));
        this.snapshotOnOpen = Boolean.parseBoolean(properties.getProperty("capture.snapshotOnOpen", "true"));
        this.snapshotOnSave = Boolean.parseBoolean(properties.getProperty("capture.snapshotOnSave", "true"));
        this.insecureTls = Boolean.parseBoolean(properties.getProperty("http.insecureTls", "false"));
        this.connectTimeoutSeconds = Integer.parseInt(properties.getProperty("http.connectTimeoutSeconds", "15"));
        this.readTimeoutSeconds = Integer.parseInt(properties.getProperty("http.readTimeoutSeconds", "600"));
        this.serverIdOverride = trimToNull(properties.getProperty("metadata.serverId"));
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
            boolean snapshotOnOpen,
            boolean snapshotOnSave,
            boolean insecureTls,
            int connectTimeoutSeconds,
            int readTimeoutSeconds,
            String serverIdOverride
    ) {
        this.workbenchBaseUrl = trimToNull(workbenchBaseUrl);
        this.workbenchIngestToken = trimToNull(workbenchIngestToken);
        this.snapshotOnOpen = snapshotOnOpen;
        this.snapshotOnSave = snapshotOnSave;
        this.insecureTls = insecureTls;
        this.connectTimeoutSeconds = connectTimeoutSeconds;
        this.readTimeoutSeconds = readTimeoutSeconds;
        this.serverIdOverride = trimToNull(serverIdOverride);
    }

    public synchronized void save() {
        Properties properties = new Properties();
        properties.setProperty("workbench.baseUrl", emptyIfNull(workbenchBaseUrl));
        properties.setProperty("workbench.ingestToken", emptyIfNull(workbenchIngestToken));
        properties.setProperty("capture.snapshotOnOpen", Boolean.toString(snapshotOnOpen));
        properties.setProperty("capture.snapshotOnSave", Boolean.toString(snapshotOnSave));
        properties.setProperty("http.insecureTls", Boolean.toString(insecureTls));
        properties.setProperty("http.connectTimeoutSeconds", Integer.toString(connectTimeoutSeconds));
        properties.setProperty("http.readTimeoutSeconds", Integer.toString(readTimeoutSeconds));
        properties.setProperty("metadata.serverId", emptyIfNull(serverIdOverride));

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

    private static String trimToNull(String value) {
        if (value == null) {
            return null;
        }
        String trimmed = value.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private static String emptyIfNull(String value) {
        return value == null ? "" : value;
    }
}
