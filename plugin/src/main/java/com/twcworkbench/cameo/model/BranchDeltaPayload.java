// Created by: Raymond Reeves Engineering Tech 4 2026
package com.twcworkbench.cameo.model;

import java.util.ArrayList;
import java.util.List;

public class BranchDeltaPayload {
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
    public String fromRevisionId;
    public String toRevisionId;
    public String baseSnapshotHash;
    public String targetSnapshotHash;
    public String sourceUser;
    public PermissionManifest permissionManifest;
    public List<ModelRecord> addedModels = new ArrayList<>();
    public List<ModelRecord> updatedModels = new ArrayList<>();
    public List<String> removedModelIds = new ArrayList<>();
    public List<ElementRecord> addedElements = new ArrayList<>();
    public List<ElementRecord> updatedElements = new ArrayList<>();
    public List<String> removedElementIds = new ArrayList<>();

    public boolean hasChanges() {
        return !addedModels.isEmpty()
                || !updatedModels.isEmpty()
                || !removedModelIds.isEmpty()
                || !addedElements.isEmpty()
                || !updatedElements.isEmpty()
                || !removedElementIds.isEmpty();
    }
}

// Fully-commented edition notes:
// - File path: plugin/src/main/java/com/twcworkbench/cameo/model/BranchDeltaPayload.java
// - This branch intentionally carries extra explanatory comments for handoff, review, and training.
// - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
// - The normal main branch keeps the production-readable version with only provenance headers.