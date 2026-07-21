package com.twcworkbench.cameo.service;

import com.nomagic.magicdraw.core.Project;
import com.nomagic.magicdraw.core.ProjectUtilities;
import com.nomagic.uml2.ext.jmi.UML2MetamodelConstants;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Element;
import com.nomagic.uml2.impl.PropertyNames;
import com.nomagic.uml2.transaction.TransactionCommitListener;
import com.twcworkbench.cameo.config.PluginConfig;
import com.twcworkbench.cameo.model.BranchDeltaPayload;
import com.twcworkbench.cameo.model.BranchSnapshotPayload;
import com.twcworkbench.cameo.model.ElementRecord;
import com.twcworkbench.cameo.model.ModelRecord;

import java.beans.PropertyChangeEvent;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.Comparator;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Consumer;

public class DirtyTrackingService {
    private static final Set<String> IGNORED_PROPERTY_NAMES = Set.of(
            UML2MetamodelConstants.ID,
            PropertyNames.PACKAGED_ELEMENT,
            PropertyNames.NESTED_CLASSIFIER
    );
    private static final int MAX_DIRTY_EVENT_COUNT = 5000;
    private static final int MAX_DIRTY_ELEMENT_COUNT = 12000;

    private final SnapshotExportService snapshotExportService;
    private final DeltaExportService deltaExportService;
    private final SnapshotHashService snapshotHashService = new SnapshotHashService();
    private final Map<String, DirtyState> states = new ConcurrentHashMap<>();
    private final Map<String, TransactionCommitListener> listeners = new ConcurrentHashMap<>();

    public DirtyTrackingService(
            SnapshotExportService snapshotExportService,
            DeltaExportService deltaExportService
    ) {
        this.snapshotExportService = snapshotExportService;
        this.deltaExportService = deltaExportService;
    }

    public void register(Project project) {
        String projectKey = projectKey(project);
        listeners.computeIfAbsent(projectKey, ignored -> {
            TransactionCommitListener listener = events -> {
                recordCommittedChanges(project, events);
                return null;
            };
            project.getRepository().getTransactionManager().addTransactionCommitListener(listener);
            return listener;
        });
        states.computeIfAbsent(projectKey, ignored -> new DirtyState());
    }

    public void unregister(Project project) {
        String projectKey = projectKey(project);
        TransactionCommitListener listener = listeners.remove(projectKey);
        if (listener != null) {
            project.getRepository().getTransactionManager().removeTransactionCommitListener(listener);
        }
        states.remove(projectKey);
    }

    public void clear(Project project) {
        states.remove(projectKey(project));
    }

    public DirtyPublishPlan preparePublish(
            Project project,
            PluginConfig config,
            BranchSnapshotPayload previous,
            Consumer<String> progress
    ) {
        if (previous == null) {
            return DirtyPublishPlan.fullSnapshot("No local baseline exists yet.");
        }
        DirtyState state = states.get(projectKey(project));
        if (state == null || state.isEmpty()) {
            return DirtyPublishPlan.noChanges("No tracked model changes were recorded in this session.");
        }
        if (state.requiresFullSnapshot
                || state.eventCount > MAX_DIRTY_EVENT_COUNT
                || state.totalTrackedIds() > MAX_DIRTY_ELEMENT_COUNT) {
            return DirtyPublishPlan.fullSnapshot("Tracked changes are too broad for a safe scoped delta publish.");
        }

        Map<String, ElementRecord> previousElements = mapElements(previous);
        LinkedHashSet<String> removedElementIds = expandRemovedElementIds(state.deletedElementIds, previousElements);
        LinkedHashSet<String> captureScopeIds = collectCaptureScopeIds(project, previousElements, state, removedElementIds);
        if (captureScopeIds.isEmpty() && removedElementIds.isEmpty()) {
            return DirtyPublishPlan.noChanges("No remaining live model scope needed to be published.");
        }

        report(progress, "Preparing scoped delta publish set from tracked model changes...");
        BranchSnapshotPayload scopedSnapshot = snapshotExportService.captureScoped(project, config, captureScopeIds, progress);
        BranchSnapshotPayload mergedSnapshot = mergeSnapshots(previous, scopedSnapshot, removedElementIds);
        snapshotHashService.ensureSnapshotHash(mergedSnapshot);
        BranchDeltaPayload delta = deltaExportService.createScopedDelta(previous, mergedSnapshot, scopedSnapshot, removedElementIds);
        if (!delta.hasChanges()) {
            return DirtyPublishPlan.noChanges("Tracked changes resolved to the current stored baseline without publishable differences.");
        }
        return DirtyPublishPlan.scopedDelta(
                "Prepared scoped delta from "
                        + captureScopeIds.size()
                        + " live element(s) and "
                        + removedElementIds.size()
                        + " removed element(s).",
                mergedSnapshot,
                delta
        );
    }

    private void recordCommittedChanges(Project project, Collection<PropertyChangeEvent> events) {
        if (events == null || events.isEmpty()) {
            return;
        }
        DirtyState state = states.computeIfAbsent(projectKey(project), ignored -> new DirtyState());
        for (PropertyChangeEvent event : events) {
            state.eventCount += 1;
            if (state.eventCount > MAX_DIRTY_EVENT_COUNT * 2) {
                state.requiresFullSnapshot = true;
            }
            String propertyName = event.getPropertyName();
            if (propertyName == null || propertyName.startsWith("_") || IGNORED_PROPERTY_NAMES.contains(propertyName)) {
                continue;
            }
            Object source = event.getSource();
            if (!(source instanceof Element)) {
                continue;
            }
            Element sourceElement = (Element) source;
            if (ProjectUtilities.isElementInAttachedProject(sourceElement)) {
                continue;
            }
            String sourceId = safeId(sourceElement);
            if (sourceId == null) {
                state.requiresFullSnapshot = true;
                continue;
            }

            if (UML2MetamodelConstants.INSTANCE_DELETED.equals(propertyName)) {
                state.deletedElementIds.add(sourceId);
                state.changedElementIds.remove(sourceId);
                state.subtreeRootIds.add(sourceId);
            }
            else {
                state.changedElementIds.add(sourceId);
                if (shouldExpandSubtree(sourceElement, propertyName)) {
                    state.subtreeRootIds.add(sourceId);
                }
            }

            Element owner = sourceElement.getOwner();
            if (owner != null) {
                addContextId(state, owner);
            }
            if (event.getOldValue() instanceof Element) {
                addContextId(state, (Element) event.getOldValue());
            }
            if (event.getNewValue() instanceof Element) {
                addContextId(state, (Element) event.getNewValue());
            }
        }
    }

    private boolean shouldExpandSubtree(Element sourceElement, String propertyName) {
        if (sourceElement == null || sourceElement.getOwnedElement().isEmpty()) {
            return false;
        }
        if (UML2MetamodelConstants.INSTANCE_CREATED.equals(propertyName)
                || UML2MetamodelConstants.INSTANCE_DELETED.equals(propertyName)) {
            return true;
        }
        String lowered = propertyName.toLowerCase(Locale.ROOT);
        return lowered.contains("name")
                || lowered.contains("owner")
                || lowered.contains("package")
                || lowered.contains("nested")
                || lowered.contains("qualified")
                || lowered.contains("stereotype")
                || lowered.contains("import")
                || lowered.contains("diagram");
    }

    private void addContextId(DirtyState state, Element element) {
        String id = safeId(element);
        if (id != null) {
            state.contextElementIds.add(id);
        }
    }

    private LinkedHashSet<String> collectCaptureScopeIds(
            Project project,
            Map<String, ElementRecord> previousElements,
            DirtyState state,
            Set<String> removedElementIds
    ) {
        LinkedHashSet<String> captureScopeIds = new LinkedHashSet<>();
        for (String elementId : state.changedElementIds) {
            if (removedElementIds.contains(elementId)) {
                continue;
            }
            Element current = resolveElement(project, elementId);
            if (current == null) {
                removedElementIds.addAll(expandRemovedElementIds(Collections.singleton(elementId), previousElements));
                captureCurrentOwnerChain(project, previousElements.get(elementId), captureScopeIds);
                continue;
            }
            addWithOwnerChain(current, captureScopeIds);
            if (state.subtreeRootIds.contains(elementId)) {
                addDescendants(current, captureScopeIds);
            }
        }
        for (String contextId : state.contextElementIds) {
            if (removedElementIds.contains(contextId)) {
                continue;
            }
            Element current = resolveElement(project, contextId);
            if (current != null) {
                addWithOwnerChain(current, captureScopeIds);
            }
        }
        for (String removedId : removedElementIds) {
            captureCurrentOwnerChain(project, previousElements.get(removedId), captureScopeIds);
        }
        return captureScopeIds;
    }

    private void captureCurrentOwnerChain(Project project, ElementRecord previousRecord, LinkedHashSet<String> captureScopeIds) {
        if (previousRecord == null || previousRecord.ownerId == null || previousRecord.ownerId.isBlank()) {
            return;
        }
        Element currentOwner = resolveElement(project, previousRecord.ownerId);
        if (currentOwner != null) {
            addWithOwnerChain(currentOwner, captureScopeIds);
        }
    }

    private void addWithOwnerChain(Element element, LinkedHashSet<String> captureScopeIds) {
        Element current = element;
        while (current != null) {
            String id = safeId(current);
            if (id != null) {
                captureScopeIds.add(id);
            }
            current = current.getOwner();
        }
    }

    private void addDescendants(Element element, LinkedHashSet<String> captureScopeIds) {
        Deque<Element> queue = new ArrayDeque<>();
        queue.add(element);
        while (!queue.isEmpty()) {
            Element current = queue.removeFirst();
            String id = safeId(current);
            if (id != null) {
                captureScopeIds.add(id);
            }
            for (Element child : current.getOwnedElement()) {
                queue.addLast(child);
            }
        }
    }

    private LinkedHashSet<String> expandRemovedElementIds(Collection<String> removedRoots, Map<String, ElementRecord> previousElements) {
        LinkedHashSet<String> removedIds = new LinkedHashSet<>();
        Deque<String> queue = new ArrayDeque<>(removedRoots);
        while (!queue.isEmpty()) {
            String currentId = queue.removeFirst();
            if (currentId == null || currentId.isBlank() || !removedIds.add(currentId)) {
                continue;
            }
            ElementRecord previous = previousElements.get(currentId);
            if (previous == null) {
                continue;
            }
            for (String childId : previous.ownedElementIds) {
                if (childId != null && !childId.isBlank()) {
                    queue.addLast(childId);
                }
            }
        }
        return removedIds;
    }

    private BranchSnapshotPayload mergeSnapshots(
            BranchSnapshotPayload previous,
            BranchSnapshotPayload scopedSnapshot,
            Set<String> removedElementIds
    ) {
        BranchSnapshotPayload merged = copySnapshot(previous);
        merged.exportedAt = scopedSnapshot.exportedAt;
        merged.exportReason = scopedSnapshot.exportReason;
        merged.serverId = scopedSnapshot.serverId;
        merged.serverUrl = scopedSnapshot.serverUrl;
        merged.workspaceId = scopedSnapshot.workspaceId;
        merged.resourceId = scopedSnapshot.resourceId;
        merged.projectId = scopedSnapshot.projectId;
        merged.projectName = scopedSnapshot.projectName;
        merged.branchId = scopedSnapshot.branchId;
        merged.branchName = scopedSnapshot.branchName;
        merged.revisionId = scopedSnapshot.revisionId;
        merged.sourceUser = scopedSnapshot.sourceUser;

        Map<String, ModelRecord> mergedModels = mapModels(merged);
        for (ModelRecord scopedModel : scopedSnapshot.models) {
            mergedModels.put(scopedModel.modelId, copyModel(scopedModel));
        }
        merged.models = new ArrayList<>(mergedModels.values());
        merged.models.sort(Comparator.comparing(model -> safe(model.modelId)));

        Map<String, ElementRecord> mergedElements = mapElements(merged);
        for (String removedId : removedElementIds) {
            mergedElements.remove(removedId);
        }
        for (ElementRecord scopedElement : scopedSnapshot.elements) {
            mergedElements.put(scopedElement.elementId, copyElement(scopedElement));
        }
        merged.elements = new ArrayList<>(mergedElements.values());
        merged.elements.sort(Comparator.comparing(element -> safe(element.elementId)));
        return merged;
    }

    private Map<String, ModelRecord> mapModels(BranchSnapshotPayload payload) {
        Map<String, ModelRecord> models = new LinkedHashMap<>();
        for (ModelRecord model : payload.models) {
            models.put(model.modelId, copyModel(model));
        }
        return models;
    }

    private Map<String, ElementRecord> mapElements(BranchSnapshotPayload payload) {
        Map<String, ElementRecord> elements = new LinkedHashMap<>();
        for (ElementRecord element : payload.elements) {
            elements.put(element.elementId, copyElement(element));
        }
        return elements;
    }

    private BranchSnapshotPayload copySnapshot(BranchSnapshotPayload payload) {
        BranchSnapshotPayload copy = new BranchSnapshotPayload();
        copy.schemaVersion = payload.schemaVersion;
        copy.source = payload.source;
        copy.exportedAt = payload.exportedAt;
        copy.exportReason = payload.exportReason;
        copy.serverId = payload.serverId;
        copy.serverUrl = payload.serverUrl;
        copy.workspaceId = payload.workspaceId;
        copy.resourceId = payload.resourceId;
        copy.projectId = payload.projectId;
        copy.projectName = payload.projectName;
        copy.branchId = payload.branchId;
        copy.branchName = payload.branchName;
        copy.revisionId = payload.revisionId;
        copy.snapshotHash = payload.snapshotHash;
        copy.sourceUser = payload.sourceUser;
        copy.permissionManifest = payload.permissionManifest;
        for (ModelRecord model : payload.models) {
            copy.models.add(copyModel(model));
        }
        for (ElementRecord element : payload.elements) {
            copy.elements.add(copyElement(element));
        }
        return copy;
    }

    private ModelRecord copyModel(ModelRecord model) {
        ModelRecord copy = new ModelRecord();
        copy.modelId = model.modelId;
        copy.name = model.name;
        copy.humanName = model.humanName;
        copy.qualifiedName = model.qualifiedName;
        copy.ownerId = model.ownerId;
        copy.rootElementIds = new ArrayList<>(model.rootElementIds);
        return copy;
    }

    private ElementRecord copyElement(ElementRecord element) {
        ElementRecord copy = new ElementRecord();
        copy.elementId = element.elementId;
        copy.modelId = element.modelId;
        copy.localId = element.localId;
        copy.ownerId = element.ownerId;
        copy.name = element.name;
        copy.humanName = element.humanName;
        copy.qualifiedName = element.qualifiedName;
        copy.humanType = element.humanType;
        copy.metaclass = element.metaclass;
        copy.documentation = element.documentation;
        copy.diagramType = element.diagramType;
        copy.diagramPreviewFormat = element.diagramPreviewFormat;
        copy.diagramPreviewBase64 = element.diagramPreviewBase64;
        copy.ownedElementIds = new ArrayList<>(element.ownedElementIds);
        copy.appliedStereotypeIds = new ArrayList<>(element.appliedStereotypeIds);
        copy.diagramElementIds = new ArrayList<>(element.diagramElementIds);
        copy.attributes = copyObjectMap(element.attributes);
        copy.references = copyReferenceMap(element.references);
        copy.specSections = copyObjectMap(element.specSections);
        return copy;
    }

    private Map<String, Object> copyObjectMap(Map<String, Object> values) {
        Map<String, Object> copied = new LinkedHashMap<>();
        for (Map.Entry<String, Object> entry : values.entrySet()) {
            copied.put(entry.getKey(), copyNestedValue(entry.getValue()));
        }
        return copied;
    }

    private Map<String, List<String>> copyReferenceMap(Map<String, List<String>> values) {
        Map<String, List<String>> copied = new LinkedHashMap<>();
        for (Map.Entry<String, List<String>> entry : values.entrySet()) {
            copied.put(entry.getKey(), new ArrayList<>(entry.getValue()));
        }
        return copied;
    }

    private Object copyNestedValue(Object value) {
        if (value instanceof Map<?, ?>) {
            Map<String, Object> copied = new LinkedHashMap<>();
            Map<?, ?> map = (Map<?, ?>) value;
            for (Map.Entry<?, ?> entry : map.entrySet()) {
                copied.put(String.valueOf(entry.getKey()), copyNestedValue(entry.getValue()));
            }
            return copied;
        }
        if (value instanceof Collection<?>) {
            List<Object> copied = new ArrayList<>();
            for (Object item : (Collection<?>) value) {
                copied.add(copyNestedValue(item));
            }
            return copied;
        }
        return value;
    }

    private Element resolveElement(Project project, String elementId) {
        if (project == null || elementId == null || elementId.isBlank()) {
            return null;
        }
        try {
            Object resolved = project.getElementByID(elementId);
            return resolved instanceof Element ? (Element) resolved : null;
        }
        catch (Exception ignored) {
            return null;
        }
    }

    private String safeId(Element element) {
        return element == null ? null : element.getID();
    }

    private String safe(String value) {
        return value == null ? "" : value;
    }

    private void report(Consumer<String> progress, String message) {
        if (progress != null) {
            progress.accept(message);
        }
    }

    private String projectKey(Project project) {
        return project.getID();
    }

    private static final class DirtyState {
        private final LinkedHashSet<String> changedElementIds = new LinkedHashSet<>();
        private final LinkedHashSet<String> deletedElementIds = new LinkedHashSet<>();
        private final LinkedHashSet<String> subtreeRootIds = new LinkedHashSet<>();
        private final LinkedHashSet<String> contextElementIds = new LinkedHashSet<>();
        private int eventCount;
        private boolean requiresFullSnapshot;

        private boolean isEmpty() {
            return changedElementIds.isEmpty() && deletedElementIds.isEmpty() && contextElementIds.isEmpty();
        }

        private int totalTrackedIds() {
            return changedElementIds.size() + deletedElementIds.size() + contextElementIds.size() + subtreeRootIds.size();
        }
    }

    public static final class DirtyPublishPlan {
        public final String mode;
        public final String message;
        public final BranchSnapshotPayload currentSnapshot;
        public final BranchDeltaPayload deltaPayload;

        private DirtyPublishPlan(String mode, String message, BranchSnapshotPayload currentSnapshot, BranchDeltaPayload deltaPayload) {
            this.mode = mode;
            this.message = message;
            this.currentSnapshot = currentSnapshot;
            this.deltaPayload = deltaPayload;
        }

        public static DirtyPublishPlan noChanges(String message) {
            return new DirtyPublishPlan("no-changes", message, null, null);
        }

        public static DirtyPublishPlan fullSnapshot(String message) {
            return new DirtyPublishPlan("full-snapshot", message, null, null);
        }

        public static DirtyPublishPlan scopedDelta(String message, BranchSnapshotPayload currentSnapshot, BranchDeltaPayload deltaPayload) {
            return new DirtyPublishPlan("scoped-delta", message, currentSnapshot, deltaPayload);
        }
    }
}
