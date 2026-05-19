package com.twcworkbench.cameo.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.twcworkbench.cameo.model.BranchSnapshotPayload;
import com.twcworkbench.cameo.model.ElementRecord;
import com.twcworkbench.cameo.model.ModelRecord;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

public class SnapshotHashService {
    private final ObjectMapper objectMapper;

    public SnapshotHashService() {
        this.objectMapper = new ObjectMapper();
        this.objectMapper.configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);
    }

    public String ensureSnapshotHash(BranchSnapshotPayload payload) {
        String snapshotHash = computeSnapshotHash(payload);
        payload.snapshotHash = snapshotHash;
        return snapshotHash;
    }

    public String computeSnapshotHash(BranchSnapshotPayload payload) {
        Map<String, Object> document = new LinkedHashMap<>();
        List<Map<String, Object>> models = new ArrayList<>();
        for (ModelRecord model : payload.models) {
            models.add(canonicalModel(model));
        }
        models.sort(Comparator.comparing(item -> String.valueOf(item.getOrDefault("model_id", ""))));
        List<Map<String, Object>> elements = new ArrayList<>();
        for (ElementRecord element : payload.elements) {
            elements.add(canonicalElement(element));
        }
        elements.sort(Comparator.comparing(item -> String.valueOf(item.getOrDefault("element_id", ""))));
        document.put("models", models);
        document.put("elements", elements);
        try {
            byte[] encoded = objectMapper.writeValueAsBytes(document);
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return toHex(digest.digest(encoded));
        }
        catch (JsonProcessingException | NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Failed to compute snapshot hash.", exception);
        }
    }

    private Map<String, Object> canonicalModel(ModelRecord model) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("model_id", safe(model.modelId));
        entry.put("name", safe(model.name));
        entry.put("human_name", safe(model.humanName));
        entry.put("qualified_name", safe(model.qualifiedName));
        entry.put("owner_id", safe(model.ownerId));
        entry.put("root_element_ids", new ArrayList<>(model.rootElementIds));
        return entry;
    }

    private Map<String, Object> canonicalElement(ElementRecord element) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("element_id", safe(element.elementId));
        entry.put("model_id", safe(element.modelId));
        entry.put("local_id", safe(element.localId));
        entry.put("owner_id", safe(element.ownerId));
        entry.put("name", safe(element.name));
        entry.put("human_name", safe(element.humanName));
        entry.put("qualified_name", safe(element.qualifiedName));
        entry.put("human_type", safe(element.humanType));
        entry.put("metaclass", safe(element.metaclass));
        entry.put("documentation", safe(element.documentation));
        entry.put("diagram_type", safe(element.diagramType));
        entry.put("diagram_preview_format", safe(element.diagramPreviewFormat));
        entry.put("diagram_preview_base64", safe(element.diagramPreviewBase64));
        entry.put("owned_element_ids", new ArrayList<>(element.ownedElementIds));
        entry.put("applied_stereotype_ids", new ArrayList<>(element.appliedStereotypeIds));
        entry.put("diagram_element_ids", new ArrayList<>(element.diagramElementIds));
        entry.put("attributes", normalizeValue(element.attributes));
        entry.put("references", normalizeValue(element.references));
        return entry;
    }

    private Object normalizeValue(Object value) {
        if (value == null || value instanceof String || value instanceof Number || value instanceof Boolean) {
            return value;
        }
        if (value instanceof Map<?, ?>) {
            Map<?, ?> map = (Map<?, ?>) value;
            Map<String, Object> normalized = new LinkedHashMap<>();
            map.entrySet().stream()
                    .sorted(Comparator.comparing(entry -> String.valueOf(entry.getKey())))
                    .forEach(entry -> normalized.put(String.valueOf(entry.getKey()), normalizeValue(entry.getValue())));
            return normalized;
        }
        if (value instanceof Collection<?>) {
            Collection<?> collection = (Collection<?>) value;
            List<Object> normalized = new ArrayList<>();
            for (Object item : collection) {
                normalized.add(normalizeValue(item));
            }
            return normalized;
        }
        return String.valueOf(value);
    }

    private String safe(String value) {
        return value == null ? "" : value;
    }

    private String toHex(byte[] bytes) {
        StringBuilder builder = new StringBuilder(bytes.length * 2);
        for (byte current : bytes) {
            builder.append(String.format("%02x", current));
        }
        return builder.toString();
    }
}
