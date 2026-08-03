// Created by: Raymond Reeves Engineering Tech 4 2026
package com.twcworkbench.cameo.model;

import java.util.ArrayList;
import java.util.List;

public class PermissionManifest {
    public String schemaVersion = "1.0";
    public String capturedAt;
    public String capturedBy;
    public String source = "cameo-package-permissions";
    public boolean complete;
    public List<PermissionManifestEntry> entries = new ArrayList<>();
    public List<String> warnings = new ArrayList<>();
}

// Fully-commented edition notes:
// - File path: plugin/src/main/java/com/twcworkbench/cameo/model/PermissionManifest.java
// - This branch intentionally carries extra explanatory comments for handoff, review, and training.
// - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
// - The normal main branch keeps the production-readable version with only provenance headers.