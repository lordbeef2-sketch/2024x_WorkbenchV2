package com.twcworkbench.cameo.model;

import java.util.ArrayList;
import java.util.List;

public class BranchSnapshotPayload {
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
    public String revisionId;
    public String sourceUser;
    public List<ModelRecord> models = new ArrayList<>();
    public List<ElementRecord> elements = new ArrayList<>();
}
