package com.twcworkbench.cameo.listener;

import com.nomagic.magicdraw.core.Application;
import com.nomagic.magicdraw.core.Project;
import com.nomagic.magicdraw.core.project.ProjectEventListenerAdapter;
import com.twcworkbench.cameo.config.PluginConfig;
import com.twcworkbench.cameo.model.BranchDeltaPayload;
import com.twcworkbench.cameo.model.BranchSnapshotPayload;
import com.twcworkbench.cameo.service.DeltaExportService;
import com.twcworkbench.cameo.service.SnapshotExportService;
import com.twcworkbench.cameo.service.WorkbenchIngestClient;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

public class TWCWorkbenchProjectListener extends ProjectEventListenerAdapter {
    private final PluginConfig config;
    private final SnapshotExportService snapshotExportService;
    private final DeltaExportService deltaExportService;
    private final WorkbenchIngestClient ingestClient;
    private final Map<String, BranchSnapshotPayload> baselines = new ConcurrentHashMap<>();

    public TWCWorkbenchProjectListener(
            PluginConfig config,
            SnapshotExportService snapshotExportService,
            DeltaExportService deltaExportService,
            WorkbenchIngestClient ingestClient
    ) {
        this.config = config;
        this.snapshotExportService = snapshotExportService;
        this.deltaExportService = deltaExportService;
        this.ingestClient = ingestClient;
    }

    @Override
    public void projectOpened(Project project) {
        if (!config.snapshotOnOpen) {
            return;
        }
        try {
            BranchSnapshotPayload baseline = snapshotExportService.capture(project, config);
            baselines.put(projectKey(project), baseline);
            Application.getInstance().getGUILog().log("[INFO] Captured open baseline for " + baseline.projectName + " [" + baseline.branchName + "].");
        }
        catch (Exception exception) {
            Application.getInstance().getGUILog().log("[WARNING] Failed to capture project-open baseline: " + exception.getMessage());
        }
    }

    @Override
    public void projectSaved(Project project, boolean savedInServer) {
        if (!config.snapshotOnSave) {
            return;
        }
        try {
            String key = projectKey(project);
            BranchSnapshotPayload previous = baselines.get(key);
            BranchSnapshotPayload current = snapshotExportService.capture(project, config);

            if (previous == null) {
                ingestClient.publishSnapshot(current, "save");
                baselines.put(key, current);
                Application.getInstance().getGUILog().log("[INFO] Published save snapshot for " + current.projectName + " [" + current.branchName + "] because no baseline was available.");
                return;
            }

            BranchDeltaPayload delta = deltaExportService.createDelta(previous, current);
            if (!delta.hasChanges()) {
                baselines.put(key, current);
                Application.getInstance().getGUILog().log("[INFO] Save produced no model changes for " + current.projectName + " [" + current.branchName + "]; skipped publish.");
                return;
            }

            ingestClient.publishDelta(delta, "save");
            baselines.put(key, current);
            Application.getInstance().getGUILog().log("[INFO] Published save delta for " + current.projectName + " [" + current.branchName + "].");
        }
        catch (Exception exception) {
            Application.getInstance().getGUILog().log("[ERROR] Failed to publish project-save delta: " + exception.getMessage());
        }
    }

    @Override
    public void projectClosed(Project project) {
        try {
            String key = projectKey(project);
            BranchSnapshotPayload previous = baselines.get(key);
            if (!config.deltaOnClose || previous == null) {
                baselines.remove(key);
                return;
            }
            BranchSnapshotPayload current = snapshotExportService.capture(project, config);
            BranchDeltaPayload delta = deltaExportService.createDelta(previous, current);
            if (!delta.hasChanges()) {
                baselines.remove(key);
                Application.getInstance().getGUILog().log("[INFO] Project close produced no unpublished model changes for " + current.projectName + " [" + current.branchName + "].");
                return;
            }
            ingestClient.publishDelta(delta, "close");
            baselines.remove(key);
            Application.getInstance().getGUILog().log("[INFO] Published close delta for " + current.projectName + " [" + current.branchName + "].");
        }
        catch (Exception exception) {
            Application.getInstance().getGUILog().log("[WARNING] Failed to publish project-close delta: " + exception.getMessage());
        }
    }

    public void rememberBaseline(Project project, BranchSnapshotPayload payload) {
        baselines.put(projectKey(project), payload);
    }

    private String projectKey(Project project) {
        return project.getID();
    }
}
