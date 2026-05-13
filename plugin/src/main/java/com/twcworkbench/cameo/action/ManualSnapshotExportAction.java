package com.twcworkbench.cameo.action;

import com.nomagic.magicdraw.actions.MDAction;
import com.twcworkbench.cameo.TWCWorkbenchCameoPlugin;

import java.awt.event.ActionEvent;

public class ManualSnapshotExportAction extends MDAction {
    public static final String ACTION_ID = "TWCWORKBENCH_EXPORT_CURRENT_PROJECT";

    private final TWCWorkbenchCameoPlugin plugin;

    public ManualSnapshotExportAction(TWCWorkbenchCameoPlugin plugin) {
        super(ACTION_ID, "Export Current Project Snapshot", null, null);
        this.plugin = plugin;
    }

    @Override
    public void actionPerformed(ActionEvent actionEvent) {
        plugin.exportCurrentProjectSnapshot();
    }
}
