package com.twcworkbench.cameo.model;

import java.util.ArrayList;
import java.util.List;

public class PermissionManifestEntry {
    public String scopeId = "";
    public String scopeType = "project";
    public String principalId = "";
    public String principalName = "";
    public String principalType = "";
    public String roleName = "";
    public String action = "";
    public String application = "";
    public boolean inherited;
    public boolean accessible;
    public boolean editable;
    public boolean branchAdminAccess;
    public boolean accessAdminAccess;
    public List<String> viaGroups = new ArrayList<>();
}
