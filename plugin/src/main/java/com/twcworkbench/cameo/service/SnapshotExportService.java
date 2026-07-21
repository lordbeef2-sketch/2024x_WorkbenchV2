package com.twcworkbench.cameo.service;

import com.nomagic.magicdraw.core.Project;
import com.nomagic.magicdraw.core.ProjectUtilities;
import com.nomagic.magicdraw.export.image.ImageExporter;
import com.nomagic.magicdraw.esi.EsiUtils;
import com.nomagic.magicdraw.uml.symbols.DiagramPresentationElement;
import com.nomagic.uml2.ext.jmi.helpers.ModelHelper;
import com.nomagic.uml2.ext.jmi.helpers.StereotypesHelper;
import com.nomagic.uml2.ext.jmi.helpers.TagsHelper;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Diagram;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Element;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.NamedElement;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Property;
import com.nomagic.uml2.ext.magicdraw.mdprofiles.Stereotype;
import com.twcworkbench.cameo.config.PluginConfig;
import com.twcworkbench.cameo.model.BranchSnapshotPayload;
import com.twcworkbench.cameo.model.ElementRecord;
import com.twcworkbench.cameo.model.ModelRecord;
import com.twcworkbench.cameo.model.PermissionManifest;
import com.twcworkbench.cameo.model.PermissionManifestEntry;
import org.eclipse.emf.common.util.URI;
import org.eclipse.emf.ecore.EAttribute;
import org.eclipse.emf.ecore.EReference;
import org.eclipse.emf.ecore.EStructuralFeature;

import java.net.URISyntaxException;
import java.nio.file.Files;
import java.time.OffsetDateTime;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collection;
import java.util.Deque;
import java.util.HashSet;
import java.util.IdentityHashMap;
import java.util.LinkedHashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.function.Consumer;
import java.util.function.Supplier;

public class SnapshotExportService {
    private static final Pattern WORKSPACE_RESOURCE_PATTERN = Pattern.compile("/workspaces/([^/]+)/resources/([^/]+)");
    private static final long FEATURE_DISABLE_THRESHOLD_NANOS = 250_000_000L;
    private static final List<String> NAVIGATION_HINTS = List.of("navigation", "hyperlink", "link", "url", "uri", "target");
    private static final List<String> TAG_HINTS = List.of("tag", "tagged", "stereotype", "profile", "author", "created", "creation", "modified", "diagraminfo");
    private static final List<String> CONSTRAINT_HINTS = List.of("constraint", "constrained", "guard", "condition", "rule", "expression");
    private static final List<String> TRACEABILITY_HINTS = List.of("trace", "traced", "traceability", "satisf", "verify", "refine", "realiz", "specif");
    private static final List<String> ALLOCATION_HINTS = List.of("allocat");
    private static final List<String> PROPERTY_HINTS = List.of(
            "representation",
            "visibility",
            "namespace",
            "context",
            "diagramtype",
            "ownerofdiagram",
            "activehyperlink",
            "elementid",
            "elementserverid",
            "nameexpression",
            "clientdependency",
            "supplierdependency",
            "image",
            "todo"
    );
    private final SnapshotHashService snapshotHashService = new SnapshotHashService();

    public BranchSnapshotPayload capture(Project project, PluginConfig config) {
        return capture(project, config, null);
    }

    public BranchSnapshotPayload capture(Project project, PluginConfig config, Consumer<String> progress) {
        CaptureContext captureContext = new CaptureContext(progress);
        BranchSnapshotPayload payload = createPayloadMetadata(project, config, progress);

        List<Element> modelRoots = modelRoots(project);
        if (!modelRoots.isEmpty()) {
            report(progress, "Preparing " + modelRoots.size() + " project model root(s), including loaded modules...");
        }
        for (Element modelRoot : modelRoots) {
            ModelRecord modelRecord = mapModel(project, modelRoot, captureContext);
            payload.models.add(modelRecord);
            payload.elements.addAll(traverseElements(project, modelRoot, modelRecord.modelId, captureContext));
        }
        payload.snapshotHash = snapshotHashService.ensureSnapshotHash(payload);
        report(progress, "Computed snapshot fingerprint " + payload.snapshotHash + ".");
        report(progress, "Snapshot capture complete.");
        return payload;
    }

    public BranchSnapshotPayload captureScoped(
            Project project,
            PluginConfig config,
            Collection<String> elementIds,
            Consumer<String> progress
    ) {
        CaptureContext captureContext = new CaptureContext(progress);
        BranchSnapshotPayload payload = createPayloadMetadata(project, config, progress);
        List<Element> modelRoots = modelRoots(project);
        if (modelRoots.isEmpty()) {
            report(progress, "No project model roots are available for scoped snapshot capture.");
            return payload;
        }

        report(progress, "Preparing scoped model snapshot from tracked changes...");
        Map<String, ModelRecord> modelRecordsById = new LinkedHashMap<>();
        for (Element modelRoot : modelRoots) {
            ModelRecord modelRecord = mapModel(project, modelRoot, captureContext);
            payload.models.add(modelRecord);
            modelRecordsById.put(modelRecord.modelId, modelRecord);
        }

        LinkedHashSet<String> requestedIds = new LinkedHashSet<>();
        if (elementIds != null) {
            for (String elementId : elementIds) {
                if (elementId != null && !elementId.isBlank()) {
                    requestedIds.add(elementId);
                }
            }
        }

        int captured = 0;
        for (String elementId : requestedIds) {
            Object resolved = project.getElementByID(elementId);
            if (!(resolved instanceof Element)) {
                continue;
            }
            Element element = (Element) resolved;
            payload.elements.add(mapElement(project, element, modelIdForElement(element, modelRecordsById), captureContext));
            captured += 1;
            if (captured == 1 || captured % 250 == 0) {
                report(progress, "Captured " + captured + " scoped element(s) so far...");
            }
        }
        report(progress, "Scoped snapshot capture complete.");
        return payload;
    }

    private List<Element> modelRoots(Project project) {
        List<Element> roots = new ArrayList<>();
        for (Element model : project.getModels()) {
            String modelId = safeId(model);
            if (modelId != null && roots.stream().noneMatch(existing -> modelId.equals(safeId(existing)))) {
                roots.add(model);
            }
        }
        Element primaryModel = project.getPrimaryModel();
        if (primaryModel != null) {
            String primaryId = safeId(primaryModel);
            if (primaryId != null) {
                roots.removeIf(existing -> primaryId.equals(safeId(existing)));
                roots.add(0, primaryModel);
            }
        }
        return roots;
    }

    private String modelIdForElement(Element element, Map<String, ModelRecord> modelRecordsById) {
        Element current = element;
        Set<String> visited = new HashSet<>();
        while (current != null) {
            String currentId = safeId(current);
            if (currentId == null || !visited.add(currentId)) {
                break;
            }
            if (modelRecordsById.containsKey(currentId)) {
                return currentId;
            }
            current = current.getOwner();
        }
        return modelRecordsById.keySet().iterator().next();
    }

    private List<ElementRecord> traverseElements(Project project, Element primaryModel, String modelId, CaptureContext captureContext) {
        Map<String, ElementRecord> recordsById = new LinkedHashMap<>();
        Deque<Element> queue = new ArrayDeque<>();
        queue.add(primaryModel);
        int visitedCount = 0;
        report(captureContext.progress, "Traversing owned elements recursively...");

        while (!queue.isEmpty()) {
            Element current = queue.removeFirst();
            String currentId = safeId(current);
            if (currentId == null || recordsById.containsKey(currentId)) {
                continue;
            }

            ElementRecord record = mapElement(project, current, modelId, captureContext);
            recordsById.put(currentId, record);
            visitedCount += 1;
            if (visitedCount == 1 || visitedCount % 250 == 0) {
                report(captureContext.progress, "Captured " + visitedCount + " elements so far...");
            }

            for (Element child : current.getOwnedElement()) {
                String childId = safeId(child);
                if (childId != null) {
                    record.ownedElementIds.add(childId);
                }
                queue.addLast(child);
            }
        }
        return new ArrayList<>(recordsById.values());
    }

    private void report(Consumer<String> progress, String message) {
        if (progress != null) {
            progress.accept(message);
        }
    }

    private BranchSnapshotPayload createPayloadMetadata(Project project, PluginConfig config, Consumer<String> progress) {
        BranchSnapshotPayload payload = new BranchSnapshotPayload();
        report(progress, "Resolving project and branch identity...");
        String resourceId = resolveResourceId(project);

        payload.exportedAt = OffsetDateTime.now().toString();
        payload.projectName = project.getName();
        payload.projectId = resolveProjectId(project, resourceId);
        payload.sourceUser = resolveSourceUser(project);
        payload.serverUrl = resolveServerUrl(project);
        payload.serverId = config.serverIdOverride != null ? config.serverIdOverride : payload.serverUrl;
        payload.resourceId = resourceId;
        payload.workspaceId = resolveWorkspaceId(project);
        payload.branchName = "trunk";
        payload.branchId = "master";
        payload.revisionId = resolveRevisionId(project);

        if (project.isRemote()) {
            EsiUtils.EsiBranchInfo branchInfo = EsiUtils.getCurrentBranch(project.getPrimaryProject());
            if (branchInfo != null) {
                payload.branchName = branchInfo.getName() == null ? "trunk" : branchInfo.getName();
                payload.branchId = "trunk".equals(payload.branchName) ? "master" : String.valueOf(branchInfo.getID());
            }
        }
        payload.permissionManifest = capturePermissionManifest(project, payload.sourceUser, payload.branchId, progress);
        return payload;
    }

    private PermissionManifest capturePermissionManifest(
            Project project,
            String sourceUser,
            String branchId,
            Consumer<String> progress
    ) {
        PermissionManifest manifest = new PermissionManifest();
        manifest.capturedAt = OffsetDateTime.now().toString();
        manifest.capturedBy = sourceUser;
        manifest.complete = false;

        PermissionManifestEntry publisher = new PermissionManifestEntry();
        publisher.scopeId = branchId;
        publisher.scopeType = "project-branch";
        publisher.principalName = sourceUser;
        publisher.principalType = "user";
        publisher.roleName = "Snapshot Publisher";
        publisher.accessible = true;
        publisher.editable = safeInvokeBoolean(project, "isEditable", false);
        manifest.entries.add(publisher);

        try {
            Class<?> permissionServiceClass = Class.forName(
                    "com.nomagic.magicdraw.esi.persistence.security.PermissionService"
            );
            Object primaryProject = project.getPrimaryProject();
            Object permissionService = primaryProject.getClass()
                    .getMethod("getService", Class.class)
                    .invoke(primaryProject, permissionServiceClass);
            Object projectPermissions = permissionServiceClass
                    .getMethod("getProjectPermissions")
                    .invoke(permissionService);
            if (projectPermissions instanceof Map<?, ?>) {
                for (Map.Entry<?, ?> scopedPermissions : ((Map<?, ?>) projectPermissions).entrySet()) {
                    Object packagePermissions = scopedPermissions.getValue();
                    if (packagePermissions == null) {
                        continue;
                    }
                    boolean inherited = safeInvokeBoolean(packagePermissions, "isUseParentPermissions", false);
                    Object accessPermissions = safeInvoke(packagePermissions, "getAccessPermissions");
                    if (!(accessPermissions instanceof Iterable<?>)) {
                        continue;
                    }
                    for (Object accessPermission : (Iterable<?>) accessPermissions) {
                        if (accessPermission == null) {
                            continue;
                        }
                        Object principal = safeInvoke(accessPermission, "getPrincipal");
                        String action = safeObjectString(safeInvoke(accessPermission, "getAction"));
                        PermissionManifestEntry entry = new PermissionManifestEntry();
                        entry.scopeId = String.valueOf(scopedPermissions.getKey());
                        entry.scopeType = "package";
                        entry.principalId = firstNonBlank(
                                safeInvokeString(principal, "esiID"),
                                safeInvokeString(principal, "getID")
                        );
                        entry.principalName = firstNonBlank(
                                safeInvokeString(principal, "getName"),
                                entry.principalId,
                                safeObjectString(principal)
                        );
                        entry.principalType = principal == null ? "" : principal.getClass().getSimpleName();
                        entry.action = action;
                        entry.application = safeObjectString(safeInvoke(accessPermission, "getApplication"));
                        entry.inherited = inherited;
                        entry.accessible = action.toLowerCase(Locale.ROOT).contains("read");
                        entry.editable = action.toLowerCase(Locale.ROOT).contains("write");
                        manifest.entries.add(entry);
                    }
                }
            }
            report(progress, "Attached " + manifest.entries.size() + " project/package permission entries to the snapshot.");
        }
        catch (Exception exception) {
            manifest.warnings.add("Cameo package permissions were unavailable: " + exception.getClass().getSimpleName());
            report(progress, "Package permission capture was unavailable; Workbench will use the live TWC REST comparison at login.");
        }
        manifest.warnings.add(
                "Cameo package permissions do not replace Teamwork Cloud resource roles; Workbench refreshes those through TWC REST at login."
        );
        return manifest;
    }

    private ModelRecord mapModel(Project project, Element model, CaptureContext captureContext) {
        ModelRecord record = new ModelRecord();
        record.modelId = safeId(model);
        record.primary = safeId(project.getPrimaryModel()) != null
                && safeId(project.getPrimaryModel()).equals(record.modelId);
        record.usageType = record.primary ? "primary" : "attached";
        try {
            record.resourceUri = model.eResource() != null && model.eResource().getURI() != null
                    ? model.eResource().getURI().toString()
                    : null;
        }
        catch (Exception ignored) {
            record.resourceUri = null;
        }
        record.humanName = safeAccessorString(captureContext, "model.getHumanName", model::getHumanName);
        record.ownerId = model.getOwner() != null ? safeId(model.getOwner()) : null;
        if (model instanceof NamedElement) {
            NamedElement namedModel = (NamedElement) model;
            record.name = safeAccessorString(captureContext, "model.getName", namedModel::getName);
            record.qualifiedName = firstNonBlank(
                    safeAccessorString(captureContext, "model.getQualifiedName", namedModel::getQualifiedName),
                    record.name,
                    record.humanName
            );
        }
        else {
            record.name = record.humanName;
            record.qualifiedName = firstNonBlank(record.humanName, record.modelId);
        }
        for (Element child : model.getOwnedElement()) {
            String childId = safeId(child);
            if (childId != null && !childId.isBlank() && !childId.equals(record.modelId) && !record.rootElementIds.contains(childId)) {
                record.rootElementIds.add(childId);
            }
        }
        return record;
    }

    private ElementRecord mapElement(Project project, Element element, String modelId, CaptureContext captureContext) {
        ElementRecord record = new ElementRecord();
        record.elementId = safeId(element);
        record.modelId = modelId;
        record.localId = safeInvokeString(element, "getLocalID");
        record.ownerId = element.getOwner() != null ? safeId(element.getOwner()) : null;
        record.humanName = safeAccessorString(captureContext, "element.getHumanName", element::getHumanName);
        record.humanType = firstNonBlank(
                safeAccessorString(captureContext, "element.getHumanType", element::getHumanType),
                "element"
        );
        record.metaclass = firstNonBlank(element.eClass().getName(), "Element");
        record.documentation = safeAccessorString(captureContext, "element.getComment", () -> ModelHelper.getComment(element));

        if (element instanceof NamedElement) {
            NamedElement namedElement = (NamedElement) element;
            record.name = safeAccessorString(captureContext, "element.getName", namedElement::getName);
            record.qualifiedName = firstNonBlank(
                    safeAccessorString(captureContext, "element.getQualifiedName", namedElement::getQualifiedName),
                    record.name,
                    record.humanName,
                    record.elementId
            );
        }
        else {
            record.name = record.humanName;
            record.qualifiedName = firstNonBlank(record.humanName, record.elementId);
        }

        for (Stereotype stereotype : StereotypesHelper.getStereotypes(element)) {
            String stereotypeId = safeId(stereotype);
            if (stereotypeId != null) {
                record.appliedStereotypeIds.add(stereotypeId);
            }
        }

        extractFeatureData(element, record, captureContext);
        record.specSections = buildNativeSpecification(element, record, captureContext);
        if (element instanceof Diagram) {
            populateDiagramPreview(project, (Diagram) element, record);
        }
        mergeCompatibilitySpecificationSections(record);
        return record;
    }

    private void populateDiagramPreview(Project project, Diagram diagram, ElementRecord record) {
        try {
            DiagramPresentationElement presentationElement = project.getDiagram(diagram);
            if (presentationElement == null) {
                return;
            }
            presentationElement.ensureLoaded();
            if (presentationElement.getDiagramType() != null) {
                record.diagramType = safeString(presentationElement.getDiagramType().getType());
            }
            for (Element usedElement : presentationElement.getUsedModelElements(true)) {
                String usedId = safeId(usedElement);
                if (usedId != null && !usedId.isBlank() && !record.diagramElementIds.contains(usedId)) {
                    record.diagramElementIds.add(usedId);
                }
            }

            java.io.File previewFile = java.io.File.createTempFile("twc-workbench-diagram-", ".png");
            try {
                ImageExporter.export(presentationElement, ImageExporter.PNG, previewFile, false, 144, 100);
                byte[] bytes = Files.readAllBytes(previewFile.toPath());
                if (bytes.length > 0) {
                    record.diagramPreviewFormat = "image/png";
                    record.diagramPreviewBase64 = Base64.getEncoder().encodeToString(bytes);
                }
            }
            finally {
                Files.deleteIfExists(previewFile.toPath());
            }
        }
        catch (Exception ignored) {
            // Diagram previews are best-effort; the semantic snapshot should still publish.
        }
    }

    private void extractFeatureData(Element element, ElementRecord record, CaptureContext captureContext) {
        for (EStructuralFeature feature : element.eClass().getEAllStructuralFeatures()) {
            if (shouldSkipFeature(feature, captureContext)) {
                continue;
            }
            Object value = readFeatureValue(element, feature, captureContext);
            if (value == null) {
                continue;
            }
            if (value instanceof Collection<?>) {
                handleCollectionFeature(feature.getName(), (Collection<?>) value, record);
            }
            else {
                handleSingleFeature(feature.getName(), value, record);
            }
        }
    }

    private boolean shouldSkipFeature(EStructuralFeature feature, CaptureContext captureContext) {
        if (feature == null) {
            return true;
        }
        if (feature.isTransient() || feature.isDerived() || feature.isVolatile()) {
            return true;
        }
        String featureName = feature.getName();
        return featureName != null && captureContext.disabledFeatures.contains(featureName);
    }

    private Object readFeatureValue(Element element, EStructuralFeature feature, CaptureContext captureContext) {
        String featureName = feature.getName();
        long startedAt = System.nanoTime();
        try {
            if (!element.eIsSet(feature)) {
                return null;
            }
            Object value = element.eGet(feature, false);
            markSlowFeatureIfNeeded(captureContext, featureName, startedAt);
            return value;
        }
        catch (Throwable throwable) {
            captureContext.disableFeature(featureName, "Expression or derived evaluation failed while reading " + featureName + ". Skipping it for the rest of this capture.");
            return null;
        }
    }

    private void handleCollectionFeature(String featureName, Collection<?> values, ElementRecord record) {
        List<String> referenceIds = new ArrayList<>();
        List<Object> attributeValues = new ArrayList<>();
        for (Object value : values) {
            if (value instanceof Element) {
                String id = safeId((Element) value);
                if (id != null) {
                    referenceIds.add(id);
                }
            }
            else {
                Object normalized = normalizeAttributeValue(value);
                if (normalized != null) {
                    attributeValues.add(normalized);
                }
            }
        }
        if (!referenceIds.isEmpty()) {
            record.references.put(featureName, referenceIds);
        }
        if (!attributeValues.isEmpty()) {
            record.attributes.put(featureName, attributeValues);
        }
    }

    private void handleSingleFeature(String featureName, Object value, ElementRecord record) {
        if (value instanceof Element) {
            String id = safeId((Element) value);
            if (id != null) {
                record.references.put(featureName, List.of(id));
            }
            return;
        }
        Object normalized = normalizeAttributeValue(value);
        if (normalized != null) {
            record.attributes.put(featureName, normalized);
        }
    }

    private Object normalizeAttributeValue(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof CharSequence || value instanceof Number || value instanceof Boolean) {
            return String.valueOf(value);
        }
        if (value instanceof Character) {
            return value;
        }
        if (value instanceof Enum<?>) {
            return ((Enum<?>) value).name();
        }
        String namedValue = firstNonBlank(
                safeInvokeString(value, "getName"),
                safeInvokeString(value, "getHumanName"),
                safeInvokeString(value, "getQualifiedName")
        );
        if (!namedValue.isBlank()) {
            return namedValue;
        }
        if (isSafeJavaValue(value)) {
            return String.valueOf(value);
        }
        return value.getClass().getSimpleName();
    }

    /**
     * Builds the headless equivalent of Cameo's Specification window data. The
     * SpecificationDialogManager is a UI manager and does not expose its page
     * contents as an export model, so Workbench publishes the authoritative
     * sources used by those pages: every metamodel feature plus ordered applied
     * stereotype properties, including inherited and calculated values.
     */
    private Map<String, Object> buildNativeSpecification(
            Element element,
            ElementRecord record,
            CaptureContext captureContext
    ) {
        Map<String, Object> sections = new LinkedHashMap<>();
        sections.put("schemaVersion", "2.0");
        sections.put("source", "cameo-native-model");
        sections.put("metaclass", record.metaclass);
        sections.put("metamodel", buildMetamodelSpecification(element, captureContext));
        sections.put("stereotypes", buildStereotypeSpecification(element, captureContext));
        return sections;
    }

    private Map<String, Object> buildMetamodelSpecification(Element element, CaptureContext captureContext) {
        Map<String, Object> section = new LinkedHashMap<>();
        List<Map<String, Object>> entries = new ArrayList<>();
        for (EStructuralFeature feature : element.eClass().getEAllStructuralFeatures()) {
            Map<String, Object> entry = new LinkedHashMap<>();
            String featureName = safeString(feature.getName());
            boolean isSet = false;
            Object value = null;
            String error = null;
            long startedAt = System.nanoTime();
            try {
                isSet = element.eIsSet(feature);
                value = element.eGet(feature, true);
                markSlowFeatureIfNeeded(captureContext, element.eClass().getName() + "." + featureName, startedAt);
            }
            catch (Throwable throwable) {
                error = throwable.getClass().getSimpleName() + ": " + safeString(throwable.getMessage());
            }

            entry.put("id", featureName);
            entry.put("name", humanizeFeatureName(featureName));
            entry.put("category", "Properties");
            entry.put("source", "metamodel");
            entry.put("declaringType", feature.getEContainingClass() == null ? "" : feature.getEContainingClass().getName());
            entry.put("valueType", feature.getEType() == null ? "" : feature.getEType().getName());
            entry.put("kind", feature instanceof EReference ? "reference" : feature instanceof EAttribute ? "attribute" : "feature");
            entry.put("many", feature.isMany());
            entry.put("ordered", feature.isOrdered());
            entry.put("unique", feature.isUnique());
            entry.put("lowerBound", feature.getLowerBound());
            entry.put("upperBound", feature.getUpperBound());
            entry.put("changeable", feature.isChangeable());
            entry.put("derived", feature.isDerived());
            entry.put("transient", feature.isTransient());
            entry.put("volatile", feature.isVolatile());
            entry.put("unsettable", feature.isUnsettable());
            entry.put("set", isSet);
            entry.put("defaultValue", normalizeSpecificationValue(feature.getDefaultValue(), 0, newIdentitySet()));
            entry.put("value", normalizeSpecificationValue(value, 0, newIdentitySet()));
            if (error != null && !error.isBlank()) {
                entry.put("error", error);
            }
            entries.add(entry);
        }
        section.put("name", "Properties");
        section.put("entries", entries);
        return section;
    }

    private List<Map<String, Object>> buildStereotypeSpecification(Element element, CaptureContext captureContext) {
        List<Map<String, Object>> stereotypeSections = new ArrayList<>();
        for (Stereotype stereotype : StereotypesHelper.getStereotypes(element)) {
            Map<String, Object> section = new LinkedHashMap<>();
            section.put("id", safeId(stereotype));
            section.put("name", safeAccessorString(captureContext, "stereotype.getName", stereotype::getName));
            section.put("qualifiedName", safeAccessorString(captureContext, "stereotype.getQualifiedName", stereotype::getQualifiedName));
            section.put("profile", stereotype.getOwner() instanceof NamedElement
                    ? safeAccessorString(captureContext, "stereotype.owner.getQualifiedName", ((NamedElement) stereotype.getOwner())::getQualifiedName)
                    : "");

            List<Map<String, Object>> entries = new ArrayList<>();
            List<Property> properties;
            try {
                properties = TagsHelper.getPropertiesWithDerivedOrdered(stereotype);
            }
            catch (Throwable throwable) {
                properties = new ArrayList<>();
                section.put("error", throwable.getClass().getSimpleName() + ": " + safeString(throwable.getMessage()));
            }
            for (Property property : properties) {
                Map<String, Object> entry = new LinkedHashMap<>();
                String propertyName = safeAccessorString(captureContext, "stereotype.property.getName", property::getName);
                Object values = null;
                String error = null;
                boolean explicitlySet = false;
                try {
                    explicitlySet = TagsHelper.getTaggedValue(element, property) != null;
                    values = TagsHelper.getStereotypePropertyValue(element, property, true);
                }
                catch (Throwable throwable) {
                    error = throwable.getClass().getSimpleName() + ": " + safeString(throwable.getMessage());
                }
                entry.put("id", safeId(property));
                entry.put("name", propertyName);
                entry.put("qualifiedName", safeAccessorString(captureContext, "stereotype.property.getQualifiedName", property::getQualifiedName));
                entry.put("category", firstNonBlank(
                        safeAccessorString(captureContext, "stereotype.getName", stereotype::getName),
                        "Stereotype"
                ));
                entry.put("source", "stereotype");
                entry.put("stereotypeId", safeId(stereotype));
                entry.put("stereotypeName", safeAccessorString(captureContext, "stereotype.getName", stereotype::getName));
                entry.put("valueType", property.getType() == null ? "" : firstNonBlank(property.getType().getQualifiedName(), property.getType().getName()));
                entry.put("lowerBound", property.getLower());
                entry.put("upperBound", property.getUpper());
                entry.put("ordered", property.isOrdered());
                entry.put("unique", property.isUnique());
                entry.put("readOnly", property.isReadOnly());
                entry.put("derived", property.isDerived());
                entry.put("set", explicitlySet);
                entry.put("defaultValue", normalizeSpecificationValue(property.getDefaultValue(), 0, newIdentitySet()));
                entry.put("value", normalizeSpecificationValue(values, 0, newIdentitySet()));
                if (error != null && !error.isBlank()) {
                    entry.put("error", error);
                }
                entries.add(entry);
            }
            section.put("entries", entries);
            stereotypeSections.add(section);
        }
        return stereotypeSections;
    }

    private Set<Object> newIdentitySet() {
        return java.util.Collections.newSetFromMap(new IdentityHashMap<>());
    }

    private Object normalizeSpecificationValue(Object value, int depth, Set<Object> visited) {
        if (value == null) {
            return null;
        }
        if (value instanceof CharSequence || value instanceof Number || value instanceof Boolean || value instanceof Character) {
            return value;
        }
        if (value instanceof Enum<?>) {
            return ((Enum<?>) value).name();
        }
        if (value instanceof Element) {
            Element referenced = (Element) value;
            Map<String, Object> reference = new LinkedHashMap<>();
            reference.put("id", safeId(referenced));
            reference.put("name", referenced instanceof NamedElement
                    ? safeString(safeInvokeString(referenced, "getName"))
                    : safeString(safeInvokeString(referenced, "getHumanName")));
            reference.put("qualifiedName", referenced instanceof NamedElement ? safeString(safeInvokeString(referenced, "getQualifiedName")) : "");
            reference.put("metaclass", referenced.eClass() == null ? "Element" : referenced.eClass().getName());
            return reference;
        }
        if (depth >= 4 || !visited.add(value)) {
            return String.valueOf(value);
        }
        if (value instanceof Collection<?>) {
            List<Object> normalized = new ArrayList<>();
            for (Object item : (Collection<?>) value) {
                normalized.add(normalizeSpecificationValue(item, depth + 1, visited));
            }
            return normalized;
        }
        if (value instanceof Map<?, ?>) {
            Map<String, Object> normalized = new LinkedHashMap<>();
            for (Map.Entry<?, ?> entry : ((Map<?, ?>) value).entrySet()) {
                normalized.put(String.valueOf(entry.getKey()), normalizeSpecificationValue(entry.getValue(), depth + 1, visited));
            }
            return normalized;
        }
        String display = firstNonBlank(
                safeInvokeString(value, "getName"),
                safeInvokeString(value, "getHumanName"),
                safeInvokeString(value, "getQualifiedName"),
                safeInvokeString(value, "stringValue"),
                safeInvokeString(value, "getValue"),
                String.valueOf(value)
        );
        Map<String, Object> normalized = new LinkedHashMap<>();
        normalized.put("display", display);
        normalized.put("javaType", value.getClass().getName());
        return normalized;
    }

    private void mergeCompatibilitySpecificationSections(ElementRecord record) {
        Map<String, Object> compatibilitySections = buildSpecSections(record);
        for (Map.Entry<String, Object> entry : compatibilitySections.entrySet()) {
            record.specSections.putIfAbsent(entry.getKey(), entry.getValue());
        }
    }

    private Map<String, Object> buildSpecSections(ElementRecord record) {
        Map<String, Object> sections = new LinkedHashMap<>();
        sections.put("properties", buildPropertiesSection(record));
        sections.put("documentation", buildDocumentationSection(record));
        sections.put("navigation", buildHintSection(record, NAVIGATION_HINTS));
        sections.put("usageDiagrams", buildUsageDiagramsSection(record));
        sections.put("innerElements", buildInnerElementsSection(record));
        sections.put("relations", buildRelationsSection(record));
        sections.put("tags", buildTagsSection(record));
        sections.put("constraints", buildConstraintsSection(record));
        sections.put("traceability", buildTraceabilitySection(record));
        sections.put("allocations", buildAllocationsSection(record));
        return sections;
    }

    private Map<String, Object> buildPropertiesSection(ElementRecord record) {
        List<Map<String, Object>> entries = new ArrayList<>();
        addEntry(entries, "Documentation", record.documentation);
        addEntry(entries, "Human Name", record.humanName);
        addEntry(entries, "Human Type", record.humanType);
        addEntry(entries, "ID", record.elementId);
        addEntry(entries, "Local ID", record.localId);
        addEntry(entries, "Metaclass", record.metaclass);
        addEntry(entries, "Name", record.name);
        addEntry(entries, "Qualified Name", record.qualifiedName);
        addEntry(entries, "Type", record.humanType);
        addEntry(entries, "Representation", attributeValue(record.attributes.get("representation")));
        addEntry(entries, "Visibility", attributeValue(record.attributes.get("visibility")));
        addEntry(entries, "Model ID", record.modelId);
        addEntry(entries, "Owner ID", record.ownerId);
        addEntry(entries, "Diagram Type", record.diagramType);

        for (Map.Entry<String, Object> entry : record.attributes.entrySet()) {
            if (matchesHints(entry.getKey(), PROPERTY_HINTS) || matchesHints(entry.getKey(), CONSTRAINT_HINTS)) {
                addEntry(entries, humanizeFeatureName(entry.getKey()), entry.getValue());
            }
        }
        for (Map.Entry<String, List<String>> entry : record.references.entrySet()) {
            if (matchesHints(entry.getKey(), PROPERTY_HINTS) || matchesHints(entry.getKey(), CONSTRAINT_HINTS)) {
                addEntry(entries, humanizeFeatureName(entry.getKey()), entry.getValue());
            }
        }
        return sectionWithEntries(entries);
    }

    private Map<String, Object> buildDocumentationSection(ElementRecord record) {
        Map<String, Object> section = new LinkedHashMap<>();
        List<String> documentation = new ArrayList<>();
        if (!safeString(record.documentation).isBlank()) {
            documentation.add(record.documentation);
        }
        List<String> comments = new ArrayList<>();
        collectTextValues(record.attributes.get("comment"), comments);
        collectTextValues(record.attributes.get("comments"), comments);
        collectTextValues(record.attributes.get("ownedComment"), comments);
        collectTextValues(record.attributes.get("ownedComments"), comments);
        section.put("documentation", documentation);
        section.put("comments", uniqueStrings(comments));
        return section;
    }

    private Map<String, Object> buildUsageDiagramsSection(ElementRecord record) {
        List<Map<String, Object>> entries = new ArrayList<>();
        for (String diagramElementId : record.diagramElementIds) {
            entries.add(referenceEntry("Diagram Symbol", "Diagram Element", diagramElementId));
        }
        appendReferenceHintEntries(entries, record.references, List.of("diagram", "symbol", "usage"), "Usage");
        return sectionWithEntries(entries);
    }

    private Map<String, Object> buildInnerElementsSection(ElementRecord record) {
        List<Map<String, Object>> entries = new ArrayList<>();
        for (String ownedElementId : record.ownedElementIds) {
            entries.add(referenceEntry("Owned Element", "Owned Element", ownedElementId));
        }
        if (!record.diagramElementIds.isEmpty()) {
            for (String diagramElementId : record.diagramElementIds) {
                entries.add(referenceEntry("Diagram Element", "Diagram Element", diagramElementId));
            }
        }
        return sectionWithEntries(entries);
    }

    private Map<String, Object> buildRelationsSection(ElementRecord record) {
        List<Map<String, Object>> entries = new ArrayList<>();
        if (record.ownerId != null && !record.ownerId.isBlank()) {
            entries.add(relationshipEntry("Owner", record.elementId, "Parent", record.ownerId));
        }
        for (String ownedElementId : record.ownedElementIds) {
            entries.add(relationshipEntry("Owned Element", record.elementId, "Contains", ownedElementId));
        }
        for (Map.Entry<String, List<String>> entry : record.references.entrySet()) {
            for (String referenceId : entry.getValue()) {
                entries.add(relationshipEntry(humanizeFeatureName(entry.getKey()), record.elementId, "Related", referenceId));
            }
        }
        return sectionWithEntries(entries);
    }

    private Map<String, Object> buildTagsSection(ElementRecord record) {
        List<Map<String, Object>> entries = new ArrayList<>();
        for (String stereotypeId : record.appliedStereotypeIds) {
            entries.add(valueEntry("Applied Stereotype", stereotypeId));
        }
        appendAttributeHintEntries(entries, record.attributes, TAG_HINTS);
        appendReferenceHintEntries(entries, record.references, TAG_HINTS, "Reference");
        return sectionWithEntries(entries);
    }

    private Map<String, Object> buildConstraintsSection(ElementRecord record) {
        return buildHintSection(record, CONSTRAINT_HINTS);
    }

    private Map<String, Object> buildTraceabilitySection(ElementRecord record) {
        return buildHintSection(record, TRACEABILITY_HINTS);
    }

    private Map<String, Object> buildAllocationsSection(ElementRecord record) {
        return buildHintSection(record, ALLOCATION_HINTS);
    }

    private Map<String, Object> buildHintSection(ElementRecord record, List<String> hints) {
        List<Map<String, Object>> entries = new ArrayList<>();
        appendAttributeHintEntries(entries, record.attributes, hints);
        appendReferenceHintEntries(entries, record.references, hints, "Reference");
        return sectionWithEntries(entries);
    }

    private void appendAttributeHintEntries(List<Map<String, Object>> entries, Map<String, Object> attributes, List<String> hints) {
        for (Map.Entry<String, Object> entry : attributes.entrySet()) {
            if (!matchesHints(entry.getKey(), hints)) {
                continue;
            }
            entries.add(valueEntry(humanizeFeatureName(entry.getKey()), entry.getValue()));
        }
    }

    private void appendReferenceHintEntries(List<Map<String, Object>> entries, Map<String, List<String>> references, List<String> hints, String defaultType) {
        for (Map.Entry<String, List<String>> entry : references.entrySet()) {
            if (!matchesHints(entry.getKey(), hints)) {
                continue;
            }
            String label = humanizeFeatureName(entry.getKey());
            for (String referenceId : entry.getValue()) {
                entries.add(referenceEntry(label, defaultType, referenceId));
            }
        }
    }

    private Map<String, Object> sectionWithEntries(List<Map<String, Object>> entries) {
        Map<String, Object> section = new LinkedHashMap<>();
        section.put("entries", entries);
        return section;
    }

    private void addEntry(List<Map<String, Object>> entries, String name, Object value) {
        if (value == null) {
            return;
        }
        if (value instanceof String && ((String) value).isBlank()) {
            return;
        }
        if (value instanceof Collection<?> && ((Collection<?>) value).isEmpty()) {
            return;
        }
        entries.add(valueEntry(name, value));
    }

    private Map<String, Object> valueEntry(String name, Object value) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", name);
        entry.put("value", value);
        return entry;
    }

    private Map<String, Object> referenceEntry(String name, String type, String value) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", name);
        entry.put("type", type);
        entry.put("value", value);
        return entry;
    }

    private Map<String, Object> relationshipEntry(String name, String elementId, String direction, String relatedElementId) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("name", name);
        entry.put("element", elementId);
        entry.put("direction", direction);
        entry.put("relatedElement", relatedElementId);
        return entry;
    }

    private boolean matchesHints(String key, List<String> hints) {
        String normalizedKey = normalizeFeatureKey(key);
        for (String hint : hints) {
            if (normalizedKey.contains(normalizeFeatureKey(hint))) {
                return true;
            }
        }
        return false;
    }

    private String normalizeFeatureKey(String value) {
        return value == null ? "" : value.replaceAll("[^A-Za-z0-9]", "").toLowerCase();
    }

    private String humanizeFeatureName(String featureName) {
        if (featureName == null || featureName.isBlank()) {
            return "";
        }
        String spaced = featureName
                .replaceAll("([a-z0-9])([A-Z])", "$1 $2")
                .replaceAll("[_:.\\-]+", " ")
                .replaceAll("\\s+", " ")
                .trim();
        StringBuilder humanized = new StringBuilder();
        for (String part : spaced.split(" ")) {
            if (part.isBlank()) {
                continue;
            }
            if (humanized.length() > 0) {
                humanized.append(' ');
            }
            humanized.append(Character.toUpperCase(part.charAt(0)));
            if (part.length() > 1) {
                humanized.append(part.substring(1));
            }
        }
        return humanized.toString();
    }

    private Object attributeValue(Object value) {
        if (value instanceof Collection<?>) {
            List<Object> collected = new ArrayList<>();
            for (Object item : (Collection<?>) value) {
                if (item != null) {
                    collected.add(item);
                }
            }
            return collected.isEmpty() ? null : collected;
        }
        return value;
    }

    private void collectTextValues(Object value, List<String> target) {
        if (value instanceof String) {
            String cleaned = ((String) value).trim();
            if (!cleaned.isBlank()) {
                target.add(cleaned);
            }
            return;
        }
        if (value instanceof Collection<?>) {
            for (Object item : (Collection<?>) value) {
                collectTextValues(item, target);
            }
        }
    }

    private List<String> uniqueStrings(List<String> values) {
        return new ArrayList<>(new LinkedHashSet<>(values));
    }

    private String resolveServerUrl(Project project) {
        URI locationUri = project.getPrimaryProject().getLocationURI();
        java.net.URI parsedUri = toJavaUri(locationUri);
        if (parsedUri == null || parsedUri.getScheme() == null || parsedUri.getHost() == null) {
            return null;
        }
        StringBuilder builder = new StringBuilder();
        builder.append(parsedUri.getScheme()).append("://").append(parsedUri.getHost());
        if (parsedUri.getPort() > 0) {
            builder.append(":").append(parsedUri.getPort());
        }
        return builder.toString();
    }

    private String resolveResourceId(Project project) {
        try {
            return ProjectUtilities.getResourceID(project.getPrimaryProject().getLocationURI());
        }
        catch (Exception ignored) {
            return project.getPrimaryProject().getProjectID();
        }
    }

    private String resolveWorkspaceId(Project project) {
        URI locationUri = project.getPrimaryProject().getLocationURI();
        java.net.URI parsedUri = toJavaUri(locationUri);
        if (parsedUri == null) {
            return null;
        }
        Matcher matcher = WORKSPACE_RESOURCE_PATTERN.matcher(parsedUri.getPath());
        return matcher.find() ? matcher.group(1) : null;
    }

    private String resolveProjectId(Project project, String resourceId) {
        if (resourceId != null && !resourceId.isBlank()) {
            return resourceId;
        }
        return project.getPrimaryProject().getProjectID();
    }

    private String resolveRevisionId(Project project) {
        try {
            return ProjectUtilities.getVersion(project.getPrimaryProject()).getName();
        }
        catch (Exception ignored) {
            return null;
        }
    }

    private String resolveSourceUser(Project project) {
        if (project.isRemote()) {
            String loggedUser = EsiUtils.getLoggedUserName();
            if (loggedUser != null && !loggedUser.isBlank()) {
                return loggedUser;
            }
        }
        String systemUser = System.getProperty("user.name");
        return (systemUser == null || systemUser.isBlank()) ? "unknown" : systemUser;
    }

    private java.net.URI toJavaUri(URI locationUri) {
        if (locationUri == null) {
            return null;
        }
        try {
            return new java.net.URI(locationUri.toString());
        }
        catch (URISyntaxException ignored) {
            return null;
        }
    }

    private String safeId(Element element) {
        return element == null ? null : element.getID();
    }

    private String safeInvokeString(Object target, String methodName) {
        try {
            Object value = target.getClass().getMethod(methodName).invoke(target);
            return value == null ? null : String.valueOf(value);
        }
        catch (Exception ignored) {
            return null;
        }
    }

    private Object safeInvoke(Object target, String methodName) {
        if (target == null) {
            return null;
        }
        try {
            return target.getClass().getMethod(methodName).invoke(target);
        }
        catch (Exception ignored) {
            return null;
        }
    }

    private boolean safeInvokeBoolean(Object target, String methodName, boolean fallback) {
        Object value = safeInvoke(target, methodName);
        return value instanceof Boolean ? (Boolean) value : fallback;
    }

    private String safeObjectString(Object value) {
        return value == null ? "" : String.valueOf(value);
    }

    private String safeString(String value) {
        return value == null ? "" : value;
    }

    private String safeAccessorString(CaptureContext captureContext, String accessorKey, Supplier<String> accessor) {
        if (captureContext.disabledAccessors.contains(accessorKey)) {
            return "";
        }
        long startedAt = System.nanoTime();
        try {
            String value = safeString(accessor.get());
            markSlowAccessorIfNeeded(captureContext, accessorKey, startedAt);
            return value;
        }
        catch (Throwable throwable) {
            captureContext.disableAccessor(accessorKey, "Expression or derived evaluation failed while reading " + accessorKey + ". Skipping it for the rest of this capture.");
            return "";
        }
    }

    private void markSlowFeatureIfNeeded(CaptureContext captureContext, String featureName, long startedAt) {
        if (featureName == null || featureName.isBlank()) {
            return;
        }
        long elapsed = System.nanoTime() - startedAt;
        if (elapsed >= FEATURE_DISABLE_THRESHOLD_NANOS) {
            captureContext.disableFeature(
                    featureName,
                    "Feature " + featureName + " took " + (elapsed / 1_000_000L) + "ms to evaluate. Skipping it for the rest of this capture to keep export moving."
            );
        }
    }

    private void markSlowAccessorIfNeeded(CaptureContext captureContext, String accessorKey, long startedAt) {
        if (accessorKey == null || accessorKey.isBlank()) {
            return;
        }
        long elapsed = System.nanoTime() - startedAt;
        if (elapsed >= FEATURE_DISABLE_THRESHOLD_NANOS) {
            captureContext.disableAccessor(
                    accessorKey,
                    "Accessor " + accessorKey + " took " + (elapsed / 1_000_000L) + "ms to evaluate. Skipping it for the rest of this capture to keep export moving."
            );
        }
    }

    private boolean isSafeJavaValue(Object value) {
        Package valuePackage = value.getClass().getPackage();
        String packageName = valuePackage == null ? "" : valuePackage.getName();
        return packageName.startsWith("java.")
                || packageName.startsWith("javax.")
                || packageName.startsWith("org.joda.time");
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return "";
    }

    private static final class CaptureContext {
        private final Consumer<String> progress;
        private final Set<String> disabledFeatures = new HashSet<>();
        private final Set<String> disabledAccessors = new HashSet<>();
        private final Set<String> reportedMessages = new HashSet<>();

        private CaptureContext(Consumer<String> progress) {
            this.progress = progress;
        }

        private void disableFeature(String featureName, String message) {
            if (featureName == null || featureName.isBlank()) {
                return;
            }
            disabledFeatures.add(featureName);
            reportOnce("feature:" + featureName, message);
        }

        private void disableAccessor(String accessorKey, String message) {
            if (accessorKey == null || accessorKey.isBlank()) {
                return;
            }
            disabledAccessors.add(accessorKey);
            reportOnce("accessor:" + accessorKey, message);
        }

        private void reportOnce(String key, String message) {
            if (progress == null || !reportedMessages.add(key)) {
                return;
            }
            progress.accept("[WARN] " + message);
        }
    }
}
