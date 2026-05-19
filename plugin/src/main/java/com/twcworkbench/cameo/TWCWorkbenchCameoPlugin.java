package com.twcworkbench.cameo;

import com.nomagic.magicdraw.actions.ActionsConfiguratorsManager;
import com.nomagic.magicdraw.core.Application;
import com.nomagic.magicdraw.core.Project;
import com.nomagic.magicdraw.plugins.Plugin;
import com.twcworkbench.cameo.action.TWCWorkbenchMenuConfigurator;
import com.twcworkbench.cameo.config.PluginConfig;
import com.twcworkbench.cameo.listener.TWCWorkbenchProjectListener;
import com.twcworkbench.cameo.model.BranchSnapshotPayload;
import com.twcworkbench.cameo.service.DeltaExportService;
import com.twcworkbench.cameo.service.SnapshotExportService;
import com.twcworkbench.cameo.service.WorkbenchIngestClient;
import com.twcworkbench.cameo.ui.PluginProgressDialog;
import com.twcworkbench.cameo.ui.WorkbenchConnectionDialog;

import java.io.File;
import javax.swing.SwingWorker;

public class TWCWorkbenchCameoPlugin extends Plugin {
    private PluginConfig config;
    private WorkbenchIngestClient ingestClient;
    private SnapshotExportService snapshotExportService;
    private DeltaExportService deltaExportService;
    private TWCWorkbenchProjectListener projectListener;

    @Override
    public void init() {
        File pluginDirectory = getDescriptor().getPluginDirectory();
        this.config = PluginConfig.load(pluginDirectory);
        this.ingestClient = new WorkbenchIngestClient(config);
        this.snapshotExportService = new SnapshotExportService();
        this.deltaExportService = new DeltaExportService();
        this.projectListener = new TWCWorkbenchProjectListener(config, snapshotExportService, deltaExportService, ingestClient);

        ActionsConfiguratorsManager.getInstance().addMainMenuConfigurator(new TWCWorkbenchMenuConfigurator(this));
        Application.getInstance().getProjectsManager().addProjectListener(projectListener);
        Application.getInstance().getGUILog().log("[INFO] TWC Workbench Cache Exporter initialized.");
    }

    @Override
    public boolean close() {
        return true;
    }

    @Override
    public boolean isSupported() {
        return true;
    }

    public void exportCurrentProjectSnapshot() {
        Project project = Application.getInstance().getProject();
        if (project == null) {
            Application.getInstance().getGUILog().log("[WARNING] No active project is open.");
            return;
        }
        PluginProgressDialog progressDialog = new PluginProgressDialog(Application.getInstance().getMainFrame(), "Publishing Workbench Snapshot");
        progressDialog.appendMessage("Starting manual snapshot publish...");
        progressDialog.showDialog();

        SwingWorker<BranchSnapshotPayload, String> worker = new SwingWorker<>() {
            @Override
            protected BranchSnapshotPayload doInBackground() throws Exception {
                java.util.function.Consumer<String> reporter = message -> super.publish(message);
                reporter.accept("[INFO] Capturing current project snapshot...");
                BranchSnapshotPayload payload = snapshotExportService.capture(project, config, reporter);
                reporter.accept("[INFO] Planning the best Workbench publish mode...");
                WorkbenchIngestClient.PublishResult result = ingestClient.publishWithPrecheck(payload, null, deltaExportService, "manual", reporter);
                reporter.accept("[INFO] " + result.message);
                projectListener.rememberBaseline(project, payload);
                return payload;
            }

            @Override
            protected void process(java.util.List<String> chunks) {
                for (String message : chunks) {
                    progressDialog.appendMessage(message);
                    Application.getInstance().getGUILog().log("[INFO] " + message);
                }
            }

            @Override
            protected void done() {
                try {
                    BranchSnapshotPayload payload = get();
                    String success = "Published snapshot for " + payload.projectName + " [" + payload.branchName + "].";
                    progressDialog.markSuccess(success);
                    Application.getInstance().getGUILog().log("[INFO] " + success);
                }
                catch (Exception exception) {
                    Throwable cause = exception.getCause() == null ? exception : exception.getCause();
                    String failure = "Manual snapshot export failed: " + cause.getMessage();
                    progressDialog.markFailure(failure);
                    Application.getInstance().getGUILog().log("[ERROR] " + failure);
                    cause.printStackTrace();
                }
            }
        };
        worker.execute();
    }

    public void configureWorkbenchConnection() {
        try {
            boolean saved = WorkbenchConnectionDialog.show(Application.getInstance().getMainFrame(), config);
            if (!saved) {
                Application.getInstance().getGUILog().log("[INFO] TWC Workbench connection settings unchanged.");
                return;
            }
            Application.getInstance().getGUILog().log("[INFO] TWC Workbench connection settings saved to " + config.configFile.getAbsolutePath() + ".");
        }
        catch (Exception exception) {
            Application.getInstance().getGUILog().log("[ERROR] Failed to update TWC Workbench connection settings: " + exception.getMessage());
            exception.printStackTrace();
        }
    }
}
