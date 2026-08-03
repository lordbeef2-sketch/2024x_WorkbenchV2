// Created by: Raymond Reeves Engineering Tech 4 2026
package com.twcworkbench.cameo.action;

import com.nomagic.magicdraw.actions.MDAction;
import com.twcworkbench.cameo.TWCWorkbenchCameoPlugin;

import java.awt.event.ActionEvent;

public class ManualSnapshotExportAction extends MDAction {
    public static final String ACTION_ID = "TWCWORKBENCH_EXPORT_CURRENT_PROJECT";

    private final TWCWorkbenchCameoPlugin plugin;

    public ManualSnapshotExportAction(TWCWorkbenchCameoPlugin plugin) {
        super(ACTION_ID, "Publish Current Project Snapshot", null, null);
        this.plugin = plugin;
    }

    @Override
    public void actionPerformed(ActionEvent actionEvent) {
        plugin.exportCurrentProjectSnapshot();
    }
}

// Fully-commented edition notes:
// - File path: plugin/src/main/java/com/twcworkbench/cameo/action/ManualSnapshotExportAction.java
// - This branch intentionally carries extra explanatory comments for handoff, review, and training.
// - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
// - The normal main branch keeps the production-readable version with only provenance headers.