// Created by: Raymond Reeves Engineering Tech 4 2026
package com.twcworkbench.cameo.action;

import com.nomagic.magicdraw.actions.MDAction;
import com.twcworkbench.cameo.TWCWorkbenchCameoPlugin;

import java.awt.event.ActionEvent;

public class ConfigureWorkbenchConnectionAction extends MDAction {
    public static final String ACTION_ID = "TWCWORKBENCH_CONFIGURE_CONNECTION";

    private final TWCWorkbenchCameoPlugin plugin;

    public ConfigureWorkbenchConnectionAction(TWCWorkbenchCameoPlugin plugin) {
        super(ACTION_ID, "Configure Workbench Connection...", null, null);
        this.plugin = plugin;
    }

    @Override
    public void actionPerformed(ActionEvent actionEvent) {
        plugin.configureWorkbenchConnection();
    }
}

// Fully-commented edition notes:
// - File path: plugin/src/main/java/com/twcworkbench/cameo/action/ConfigureWorkbenchConnectionAction.java
// - This branch intentionally carries extra explanatory comments for handoff, review, and training.
// - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
// - The normal main branch keeps the production-readable version with only provenance headers.