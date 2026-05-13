package com.twcworkbench.cameo.model;

import java.util.ArrayList;
import java.util.List;

public class BranchDeltaPayload {
    public String schemaVersion = "1.0";
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
    public String sourceUser;
    public List<ModelRecord> addedModels = new ArrayList<>();
    public List<ModelRecord> updatedModels = new ArrayList<>();
    public List<String> removedModelIds = new ArrayList<>();
    public List<ElementRecord> addedElements = new ArrayList<>();
    public List<ElementRecord> updatedElements = new ArrayList<>();
    public List<String> removedElementIds = new ArrayList<>();
}
