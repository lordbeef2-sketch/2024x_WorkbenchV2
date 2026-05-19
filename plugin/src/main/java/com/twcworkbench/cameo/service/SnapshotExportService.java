package com.twcworkbench.cameo.service;

import com.nomagic.magicdraw.core.Project;
import com.nomagic.magicdraw.core.ProjectUtilities;
import com.nomagic.magicdraw.export.image.ImageExporter;
import com.nomagic.magicdraw.esi.EsiUtils;
import com.nomagic.magicdraw.uml.symbols.DiagramPresentationElement;
import com.nomagic.uml2.ext.jmi.helpers.ModelHelper;
import com.nomagic.uml2.ext.jmi.helpers.StereotypesHelper;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Diagram;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.Element;
import com.nomagic.uml2.ext.magicdraw.classes.mdkernel.NamedElement;
import com.nomagic.uml2.ext.magicdraw.mdprofiles.Stereotype;
import com.twcworkbench.cameo.config.PluginConfig;
import com.twcworkbench.cameo.model.BranchSnapshotPayload;
import com.twcworkbench.cameo.model.ElementRecord;
import com.twcworkbench.cameo.model.ModelRecord;
import org.eclipse.emf.common.util.URI;
import org.eclipse.emf.ecore.EStructuralFeature;

import java.net.URISyntaxException;
import java.nio.file.Files;
import java.time.OffsetDateTime;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collection;
import java.util.Deque;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.function.Consumer;

public class SnapshotExportService {
    private static final Pattern WORKSPACE_RESOURCE_PATTERN = Pattern.compile("/workspaces/([^/]+)/resources/([^/]+)");
    private final SnapshotHashService snapshotHashService = new SnapshotHashService();

    public BranchSnapshotPayload capture(Project project, PluginConfig config) {
        return capture(project, config, null);
    }

    public BranchSnapshotPayload capture(Project project, PluginConfig config, Consumer<String> progress) {
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

        Element primaryModel = project.getPrimaryModel();
        if (primaryModel != null) {
            report(progress, "Preparing primary model snapshot...");
            ModelRecord modelRecord = mapModel(primaryModel);
            payload.models.add(modelRecord);
            payload.elements.addAll(traverseElements(project, primaryModel, modelRecord.modelId, progress));
        }
        payload.snapshotHash = snapshotHashService.ensureSnapshotHash(payload);
        report(progress, "Computed snapshot fingerprint " + payload.snapshotHash + ".");
        report(progress, "Snapshot capture complete.");
        return payload;
    }

    private List<ElementRecord> traverseElements(Project project, Element primaryModel, String modelId, Consumer<String> progress) {
        Map<String, ElementRecord> recordsById = new LinkedHashMap<>();
        Deque<Element> queue = new ArrayDeque<>();
        queue.add(primaryModel);
        int visitedCount = 0;
        report(progress, "Traversing owned elements recursively...");

        while (!queue.isEmpty()) {
            Element current = queue.removeFirst();
            String currentId = safeId(current);
            if (currentId == null || recordsById.containsKey(currentId)) {
                continue;
            }

            ElementRecord record = mapElement(project, current, modelId);
            recordsById.put(currentId, record);
            visitedCount += 1;
            if (visitedCount == 1 || visitedCount % 250 == 0) {
                report(progress, "Captured " + visitedCount + " elements so far...");
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

    private ModelRecord mapModel(Element model) {
        ModelRecord record = new ModelRecord();
        record.modelId = safeId(model);
        record.humanName = safeString(model.getHumanName());
        record.ownerId = model.getOwner() != null ? safeId(model.getOwner()) : null;
        if (model instanceof NamedElement) {
            NamedElement namedModel = (NamedElement) model;
            record.name = safeString(namedModel.getName());
            record.qualifiedName = firstNonBlank(namedModel.getQualifiedName(), record.name, record.humanName);
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

    private ElementRecord mapElement(Project project, Element element, String modelId) {
        ElementRecord record = new ElementRecord();
        record.elementId = safeId(element);
        record.modelId = modelId;
        record.localId = safeInvokeString(element, "getLocalID");
        record.ownerId = element.getOwner() != null ? safeId(element.getOwner()) : null;
        record.humanName = safeString(element.getHumanName());
        record.humanType = firstNonBlank(element.getHumanType(), "element");
        record.metaclass = firstNonBlank(element.eClass().getName(), "Element");
        record.documentation = safeString(ModelHelper.getComment(element));

        if (element instanceof NamedElement) {
            NamedElement namedElement = (NamedElement) element;
            record.name = safeString(namedElement.getName());
            record.qualifiedName = firstNonBlank(namedElement.getQualifiedName(), record.name, record.humanName, record.elementId);
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

        extractFeatureData(element, record);
        if (element instanceof Diagram) {
            populateDiagramPreview(project, (Diagram) element, record);
        }
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

    private void extractFeatureData(Element element, ElementRecord record) {
        for (EStructuralFeature feature : element.eClass().getEAllStructuralFeatures()) {
            if (feature.isTransient() || !element.eIsSet(feature)) {
                continue;
            }
            Object value = element.eGet(feature, false);
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
        if (value instanceof String || value instanceof Number || value instanceof Boolean) {
            return value;
        }
        if (value instanceof Enum<?>) {
            return ((Enum<?>) value).name();
        }
        return String.valueOf(value);
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

    private String safeString(String value) {
        return value == null ? "" : value;
    }

    private String firstNonBlank(String... values) {
        for (String value : values) {
            if (value != null && !value.isBlank()) {
                return value;
            }
        }
        return "";
    }
}
