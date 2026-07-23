package com.twcworkbench.cameo.action;

import com.nomagic.actions.AMConfigurator;
import com.nomagic.actions.ActionsCategory;
import com.nomagic.actions.ActionsManager;
import com.nomagic.actions.NMAction;
import com.nomagic.magicdraw.actions.MDActionsCategory;
import com.twcworkbench.cameo.TWCWorkbenchCameoPlugin;

public class TWCWorkbenchMenuConfigurator implements AMConfigurator {
    private final TWCWorkbenchCameoPlugin plugin;

    public TWCWorkbenchMenuConfigurator(TWCWorkbenchCameoPlugin plugin) {
        this.plugin = plugin;
    }

    @Override
    public int getPriority() {
        return 0;
    }

    @Override
    public void configure(ActionsManager manager) {
        NMAction categoryAction = manager.getActionFor("TWCWORKBENCHMAIN");
        if (categoryAction == null) {
            categoryAction = new MDActionsCategory("TWCWORKBENCHMAIN", "TWC Workbench");
            manager.addCategory((ActionsCategory) categoryAction);
        }
        ActionsCategory category = (ActionsCategory) categoryAction;
        category.setNested(true);

        ConfigureWorkbenchConnectionAction configureAction = new ConfigureWorkbenchConnectionAction(plugin);
        if (manager.getActionFor(configureAction.getID()) == null) {
            category.addAction(configureAction);
        }

        ManualSnapshotExportAction exportAction = new ManualSnapshotExportAction(plugin);
        if (manager.getActionFor(exportAction.getID()) == null) {
            category.addAction(exportAction);
        }

        OpenWorkbenchAgentAction agentAction = new OpenWorkbenchAgentAction(plugin);
        if (manager.getActionFor(agentAction.getID()) == null) {
            category.addAction(agentAction);
        }
    }
}
