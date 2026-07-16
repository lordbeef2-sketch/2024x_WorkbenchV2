package com.twcworkbench.cameo.model;

import java.util.ArrayList;
import java.util.List;

public class ModelRecord {
    public String modelId;
    public String name;
    public String humanName;
    public String qualifiedName;
    public String ownerId;
    public boolean primary;
    public String usageType;
    public String resourceUri;
    public List<String> rootElementIds = new ArrayList<>();

    public String comparisonKey() {
        return String.join("|",
                safe(modelId),
                safe(name),
                safe(humanName),
                safe(qualifiedName),
                safe(ownerId),
                String.valueOf(primary),
                safe(usageType),
                safe(resourceUri),
                String.join(",", rootElementIds));
    }

    private static String safe(String value) {
        return value == null ? "" : value;
    }
}
