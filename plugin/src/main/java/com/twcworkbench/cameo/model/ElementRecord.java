package com.twcworkbench.cameo.model;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class ElementRecord {
    public String elementId;
    public String modelId;
    public String localId;
    public String ownerId;
    public String name;
    public String humanName;
    public String qualifiedName;
    public String humanType;
    public String metaclass;
    public String documentation;
    public List<String> ownedElementIds = new ArrayList<>();
    public List<String> appliedStereotypeIds = new ArrayList<>();
    public Map<String, Object> attributes = new LinkedHashMap<>();
    public Map<String, List<String>> references = new LinkedHashMap<>();

    public String comparisonKey() {
        return String.join("|",
                safe(elementId),
                safe(modelId),
                safe(localId),
                safe(ownerId),
                safe(name),
                safe(humanName),
                safe(qualifiedName),
                safe(humanType),
                safe(metaclass),
                safe(documentation),
                ownedElementIds.toString(),
                appliedStereotypeIds.toString(),
                attributes.toString(),
                references.toString());
    }

    private static String safe(String value) {
        return value == null ? "" : value;
    }
}
