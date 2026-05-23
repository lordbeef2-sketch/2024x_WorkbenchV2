package com.twcworkbench.cameo.model;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public class BranchIngestState {
    @JsonAlias("server_id")
    public String serverId;
    @JsonAlias("project_id")
    public String projectId;
    @JsonAlias("branch_id")
    public String branchId;
    @JsonAlias("workspace_id")
    public String workspaceId;
    public boolean exists;
    @JsonAlias("project_name")
    public String projectName;
    @JsonAlias("branch_name")
    public String branchName;
    @JsonAlias("latest_revision")
    public String latestRevision;
    @JsonAlias("snapshot_hash")
    public String snapshotHash;
    @JsonAlias("model_count")
    public int modelCount;
    @JsonAlias("element_count")
    public int elementCount;
    @JsonAlias("source_kind")
    public String sourceKind;
    @JsonAlias("source_user")
    public String sourceUser;
    @JsonAlias("updated_at")
    public String updatedAt;
}
