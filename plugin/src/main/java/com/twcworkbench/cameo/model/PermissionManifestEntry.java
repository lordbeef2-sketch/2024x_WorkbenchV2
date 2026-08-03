// Created by: Raymond Reeves Engineering Tech 4 2026
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

// Fully-commented edition notes:
// - File path: plugin/src/main/java/com/twcworkbench/cameo/model/PermissionManifestEntry.java
// - This branch intentionally carries extra explanatory comments for handoff, review, and training.
// - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
// - The normal main branch keeps the production-readable version with only provenance headers.