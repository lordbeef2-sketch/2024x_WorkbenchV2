package com.twcworkbench.cameo.action;

import com.nomagic.magicdraw.actions.MDAction;
import com.twcworkbench.cameo.TWCWorkbenchCameoPlugin;

import java.awt.event.ActionEvent;

public class OpenWorkbenchAgentAction extends MDAction {
    public static final String ACTION_ID = "TWCWORKBENCH_OPEN_AGENT";

    private final TWCWorkbenchCameoPlugin plugin;

    public OpenWorkbenchAgentAction(TWCWorkbenchCameoPlugin plugin) {
        super(ACTION_ID, "Workbench Agent...", null, null);
        this.plugin = plugin;
    }

    @Override
    public void actionPerformed(ActionEvent actionEvent) {
        plugin.openWorkbenchAgent();
    }
}
