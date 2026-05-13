package com.twcworkbench.cameo.service;

import com.twcworkbench.cameo.model.BranchDeltaPayload;
import com.twcworkbench.cameo.model.BranchSnapshotPayload;
import com.twcworkbench.cameo.model.ElementRecord;
import com.twcworkbench.cameo.model.ModelRecord;

import java.time.OffsetDateTime;
import java.util.LinkedHashMap;
import java.util.Map;

public class DeltaExportService {
    public BranchDeltaPayload createDelta(BranchSnapshotPayload previous, BranchSnapshotPayload current) {
        BranchDeltaPayload delta = new BranchDeltaPayload();
        delta.exportedAt = OffsetDateTime.now().toString();
        delta.serverId = current.serverId;
        delta.serverUrl = current.serverUrl;
        delta.workspaceId = current.workspaceId;
        delta.resourceId = current.resourceId;
        delta.projectId = current.projectId;
        delta.projectName = current.projectName;
        delta.branchId = current.branchId;
        delta.branchName = current.branchName;
        delta.fromRevisionId = previous.revisionId;
        delta.toRevisionId = current.revisionId;
        delta.sourceUser = current.sourceUser;

        Map<String, ModelRecord> previousModels = mapModels(previous);
        Map<String, ModelRecord> currentModels = mapModels(current);
        collectModelChanges(previousModels, currentModels, delta);

        Map<String, ElementRecord> previousElements = mapElements(previous);
        Map<String, ElementRecord> currentElements = mapElements(current);
        collectElementChanges(previousElements, currentElements, delta);

        return delta;
    }

    private void collectModelChanges(Map<String, ModelRecord> previousModels, Map<String, ModelRecord> currentModels, BranchDeltaPayload delta) {
        for (Map.Entry<String, ModelRecord> entry : currentModels.entrySet()) {
            ModelRecord previous = previousModels.remove(entry.getKey());
            if (previous == null) {
                delta.addedModels.add(entry.getValue());
            }
            else if (!previous.comparisonKey().equals(entry.getValue().comparisonKey())) {
                delta.updatedModels.add(entry.getValue());
            }
        }
        delta.removedModelIds.addAll(previousModels.keySet());
    }

    private void collectElementChanges(Map<String, ElementRecord> previousElements, Map<String, ElementRecord> currentElements, BranchDeltaPayload delta) {
        for (Map.Entry<String, ElementRecord> entry : currentElements.entrySet()) {
            ElementRecord previous = previousElements.remove(entry.getKey());
            if (previous == null) {
                delta.addedElements.add(entry.getValue());
            }
            else if (!previous.comparisonKey().equals(entry.getValue().comparisonKey())) {
                delta.updatedElements.add(entry.getValue());
            }
        }
        delta.removedElementIds.addAll(previousElements.keySet());
    }

    private Map<String, ModelRecord> mapModels(BranchSnapshotPayload payload) {
        Map<String, ModelRecord> models = new LinkedHashMap<>();
        for (ModelRecord model : payload.models) {
            models.put(model.modelId, model);
        }
        return models;
    }

    private Map<String, ElementRecord> mapElements(BranchSnapshotPayload payload) {
        Map<String, ElementRecord> elements = new LinkedHashMap<>();
        for (ElementRecord element : payload.elements) {
            elements.put(element.elementId, element);
        }
        return elements;
    }
}
