// Created by: Raymond Reeves Engineering Tech 4 2026
package com.twcworkbench.cameo.model;

import java.util.ArrayList;
import java.util.List;

public class BranchSnapshotPayload {
    public String schemaVersion = "1.1";
    public String source = "cameo-plugin";
    public String exportedAt;
    public String exportReason;
    public String serverId;
    public String serverUrl;
    public String workspaceId;
    public String resourceId;
    public String projectId;
    public String projectName;
    public String branchId;
    public String branchName;
    public String revisionId;
    public String snapshotHash;
    public String sourceUser;
    public PermissionManifest permissionManifest;
    public List<ModelRecord> models = new ArrayList<>();
    public List<ElementRecord> elements = new ArrayList<>();
}

// Fully-commented edition notes:
// - File path: plugin/src/main/java/com/twcworkbench/cameo/model/BranchSnapshotPayload.java
// - This branch intentionally carries extra explanatory comments for handoff, review, and training.
// - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
// - The normal main branch keeps the production-readable version with only provenance headers.