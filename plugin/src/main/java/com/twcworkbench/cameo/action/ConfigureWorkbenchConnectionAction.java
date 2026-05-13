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
