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
