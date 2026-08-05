// Created by: Raymond Reeves Engineering Tech 4 2026
import { type MouseEvent as ReactMouseEvent, type ReactNode, type SyntheticEvent, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  AppBar,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  CircularProgress,
  Divider,
  FormControlLabel,
  IconButton,
  List,
  ListItemButton,
  ListItemText,
  Menu,
  MenuItem,
  Paper,
  Slider,
  Stack,
  Tab,
  Tabs,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Toolbar,
  Tooltip,
  Typography,
} from "@mui/material";
import Grid from "@mui/material/GridLegacy";
import CompareArrowsRoundedIcon from "@mui/icons-material/CompareArrowsRounded";
import ExpandMoreRoundedIcon from "@mui/icons-material/ExpandMoreRounded";
import KeyboardArrowDownRoundedIcon from "@mui/icons-material/KeyboardArrowDownRounded";
import LogoutRoundedIcon from "@mui/icons-material/LogoutRounded";
import RefreshRoundedIcon from "@mui/icons-material/RefreshRounded";
import SaveRoundedIcon from "@mui/icons-material/SaveRounded";
import SettingsRoundedIcon from "@mui/icons-material/SettingsRounded";
import AccountCircleRoundedIcon from "@mui/icons-material/AccountCircleRounded";

import CapabilityBadges from "../components/CapabilityBadges";
import ProjectTree from "../components/ProjectTree";
import WorkbenchBrandMark from "../components/WorkbenchBrandMark";
import {
  BranchAccessManifestStatus,
  BranchTombstoneRecord,
  CacheElementSearchResponse,
  CacheApiKeyScope,
  CacheApiKeySummary,
  CachedElementRecord,
  ItemDetailViewMode,
  ItemReference,
  OpenWebUIModelEntry,
  ItemDetails,
  JobRecord,
  ProjectSummary,
  ProjectTombstoneRecord,
  ProjectUsageResponse,
  ServerProfile,
  ServerProfileInput,
  ServerPermissionInventoryDetails,
  ServerPermissionInventoryStatus,
  SessionPreferences,
  StereotypeElementSearchResponse,
  SwaggerContractManifest,
  SwaggerExecuteResponse,
  SwaggerOperationSpec,
  SwaggerParameterSpec,
  TreeNode,
  ThemeMode,
  WorkbenchAgentChatMessage,
  WorkbenchAgentKnowledgeStatus,
  WorkbenchAuthSettings,
  WorkbenchGroupCreateRequest,
  WorkbenchGroupSummary,
  WorkbenchGroupUpdateRequest,
  WorkbenchProjectAccessAssignmentRequest,
  WorkbenchUserCreateRequest,
  WorkbenchUserUpdateRequest,
} from "../models/api";
import { api } from "../services/api";
import { useSession } from "../state/SessionProvider";

type WorkspaceTab = "dashboard" | "projects" | "models" | "search" | "diagram-viewer" | "compare" | "agent" | "developer" | "api" | "settings";
type WorkspaceMenuGroup = "views" | "diagrams" | "api";
type ElementSearchMode = "query" | "stereotype";
type CompareMode = "branch" | "item";
type SettingsSubtab = "users" | "groups" | "servers" | "auth" | "api-keys" | "debug";

function createServerProfileDraft(overrides: Partial<ServerProfileInput> = {}): ServerProfileInput {
  return {
    id: "",
    name: "",
    base_url: "",
    version: "2024x",
    verify_tls: true,
    ca_bundle_path: null,
    enabled: true,
    display_order: 0,
    auth_discovery_url: null,
    auth_authorize_url: null,
    auth_token_url: null,
    auth_login_path: null,
    auth_login_port: null,
    auth_token_path: null,
    auth_client_id: null,
    auth_client_secret: null,
    auth_scope: "openid",
    auth_return_url_parameter: "redirect_uri",
    oslc_base_url: null,
    oslc_consumer_key: null,
    oslc_consumer_secret: null,
    oslc_callback_url: null,
    ...overrides,
  };
}

const WORKSPACE_TABS: WorkspaceTab[] = ["dashboard", "projects", "models", "search", "diagram-viewer", "compare", "agent", "developer", "api", "settings"];
const ITEM_DETAIL_VIEW_MODES: ItemDetailViewMode[] = ["standard", "expert", "all"];
const ITEM_DETAIL_VIEW_LABELS: Record<ItemDetailViewMode, string> = {
  standard: "Standard",
  expert: "Expert",
  all: "All",
};
type SpecificationSectionId =
  | "properties"
  | "documentation"
  | "navigation"
  | "usage-diagrams"
  | "usage-in"
  | "constraints"
  | "ports-interfaces"
  | "element-properties"
  | "attributes"
  | "ports"
  | "operations"
  | "receptions"
  | "behaviors"
  | "relations"
  | "tags"
  | "traceability"
  | "allocations"
  | "inner-elements"
  | "template-parameters"
  | "instances";

const SPECIFICATION_SECTION_LABELS: Record<SpecificationSectionId, string> = {
  properties: "Properties",
  documentation: "Documentation/Comments",
  navigation: "Navigation/Hyperlinks",
  "usage-diagrams": "Usage in Diagrams",
  "usage-in": "Usage In",
  "ports-interfaces": "Ports/Interfaces",
  "element-properties": "Properties",
  attributes: "Attributes",
  ports: "Ports",
  operations: "Operations",
  receptions: "Receptions",
  behaviors: "Behaviors",
  "inner-elements": "Inner Elements",
  relations: "Relations",
  tags: "Tags",
  constraints: "Constraints",
  traceability: "Traceability",
  allocations: "Allocations",
  "template-parameters": "Template Parameters",
  instances: "Instances",
};

const SPECIFICATION_CHILD_SECTIONS: SpecificationSectionId[] = [
  "documentation",
  "navigation",
  "usage-diagrams",
  "usage-in",
  "constraints",
  "ports-interfaces",
  "element-properties",
  "attributes",
  "ports",
  "operations",
  "receptions",
  "behaviors",
  "relations",
  "tags",
  "traceability",
  "allocations",
  "inner-elements",
  "template-parameters",
  "instances",
];

const PACKAGE_SPECIFICATION_CHILD_SECTIONS: SpecificationSectionId[] = [
  "traceability",
  "documentation",
  "navigation",
  "usage-diagrams",
  "template-parameters",
  "inner-elements",
  "relations",
  "tags",
  "constraints",
  "allocations",
];

const CAMEO_SPECIFICATION_PROPERTY_LABEL_ORDER = [
  "Name",
  "Used As Type",
  "Sync Element",
  "General",
  "Element ID",
  "Specific Classifier",
  "Verifies",
  "Participates In Interaction",
  "Allocated To",
  "Specifying Component",
  "All Specifying Elements",
  "Realizing Element",
  "Refines",
  "Participates In Activity",
  "Traced From",
  "All Realizing Elements",
  "Allocated From",
  "Specifying Use Case",
  "All Specific Classifiers",
  "Owner",
  "Qualified Name",
  "Is Encapsulated",
  "Realizing Component",
  "Satisfies",
  "Specifying Element",
  "All General Classifiers",
  "Applied Stereotype",
  "Is Active",
  "Is Abstract",
  "Use Case",
  "Template Parameter",
  "Owned Comment",
  "Owned Element",
  "Super Class",
  "Tagged Value",
  "Owning Package",
  "Name Expression",
  "Namespace",
  "Owned Template Signature",
  "Template Binding",
  "Client Dependency",
  "Supplier Dependency",
  "Owned Connector",
  "Role",
  "Part",
  "Owned Attribute",
  "Owned Diagram",
  "Imported Member",
  "Member",
  "Owned Member",
  "Owned Rule",
];

const CAMEO_SPECIFICATION_PROPERTY_LABEL_INDEX = new Map(
  CAMEO_SPECIFICATION_PROPERTY_LABEL_ORDER.map((label, index) => [normalizedFieldKey(label), index]),
);

const CAMEO_PACKAGE_SPECIFICATION_PROPERTY_LABEL_ORDER = [
  "Name",
  "Qualified Name",
  "Owner",
  "Applied Stereotype",
  "Visibility",
  "Active Hyperlink",
  "Name Expression",
  "Client Dependency",
  "Supplier Dependency",
  "Template Parameter",
  "Tagged Value",
  "Owned Comment",
  "Owned Element",
  "Namespace",
  "Owned Template Signature",
  "Template Binding",
  "Owned Diagram",
  "Imported Member",
  "Member",
  "Owned Member",
  "Owned Rule",
  "Package Import",
  "Element Import",
  "Owning Package",
  "Nesting Package",
  "Nested Package",
  "Owned Type",
  "Package Merge",
  "Applied Profile",
  "Image",
  "URI",
  "To Do",
  "Element ID",
  "Owned Stereotype",
  "Owning Template Parameter",
  "Packaged Element",
  "Profile Application",
  "All Realizing Elements",
  "All Specifying Elements",
  "Realizing Element",
  "Specifying Element",
  "Allocated From",
  "Allocated To",
  "Author",
  "Documentation",
  "Mounted Package",
];

const CAMEO_PACKAGE_SPECIFICATION_PROPERTY_LABEL_INDEX = new Map(
  CAMEO_PACKAGE_SPECIFICATION_PROPERTY_LABEL_ORDER.map((label, index) => [normalizedFieldKey(label), index]),
);

function parseWorkspaceTab(value: string | null): WorkspaceTab {
  const fallback: WorkspaceTab = "dashboard";
  if (value === "details" || value === "diagram-details") {
    return "models";
  }
  if (!value || !WORKSPACE_TABS.includes(value as WorkspaceTab)) {
    return fallback;
  }
  return value as WorkspaceTab;
}

function parseItemDetailViewMode(value: string | null | undefined): ItemDetailViewMode {
  if (!value || !ITEM_DETAIL_VIEW_MODES.includes(value as ItemDetailViewMode)) {
    return "standard";
  }
  return value as ItemDetailViewMode;
}

function parseElementSearchMode(value: string | null | undefined): ElementSearchMode {
  return value === "stereotype" ? "stereotype" : "query";
}

function errorMessage(caught: unknown): string {
  return caught instanceof Error ? caught.message : "The request failed.";
}

function inventoryTextValue(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) {
      return value;
    }
    if (typeof value === "number" || typeof value === "boolean") {
      return String(value);
    }
  }
  return "";
}

function inventoryRecordTitle(record: Record<string, unknown>, fallback: string): string {
  return inventoryTextValue(record, ["displayName", "name", "qualifiedName", "title", "key", "ID", "id", "roleName", "groupName"]) || fallback;
}

function inventoryRecordSubtitle(record: Record<string, unknown>): string {
  return inventoryTextValue(record, ["description", "qualifiedName", "ID", "id", "key", "resourceID", "resourceId"]);
}

function inventoryRecordSearchText(record: Record<string, unknown>): string {
  return JSON.stringify(record).toLowerCase();
}

function inventoryMemberCount(record: Record<string, unknown>): number | null {
  for (const key of ["users", "groupUsers", "usergroups", "members", "children"]) {
    const value = record[key];
    if (Array.isArray(value)) {
      return value.length;
    }
  }
  return null;
}

function flattenTree(nodes: TreeNode[]): TreeNode[] {
  const flattened: TreeNode[] = [];
  const stack = [...nodes].reverse();
  while (stack.length) {
    const node = stack.pop();
    if (!node) {
      continue;
    }
    flattened.push(node);
    for (let index = node.children.length - 1; index >= 0; index -= 1) {
      stack.push(node.children[index]);
    }
  }
  return flattened;
}

function expandableTreeNodeIds(nodes: TreeNode[]): string[] {
  const expanded: string[] = [];
  const walk = (candidates: TreeNode[]) => {
    for (const node of candidates) {
      if (node.children.length) {
        expanded.push(node.id);
        walk(node.children);
      }
    }
  };
  walk(nodes);
  return expanded;
}

function clampNumber(value: number, minimum: number, maximum: number): number {
  return Math.min(Math.max(value, minimum), maximum);
}

function paneMaxWidthForViewport(viewportWidth: number, fraction: number, minimum: number, maximum: number): number {
  return clampNumber(Math.floor(viewportWidth * fraction), minimum, maximum);
}

function readStoredNumber(key: string, fallback: number, minimum: number, maximum: number): number {
  if (typeof window === "undefined") {
    return fallback;
  }
  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return fallback;
  }
  const parsed = Number.parseInt(raw, 10);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return clampNumber(parsed, minimum, maximum);
}

function readStoredStringArray(key: string): string[] {
  if (typeof window === "undefined") {
    return [];
  }
  const raw = window.localStorage.getItem(key);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((value) => typeof value === "string") : [];
  } catch {
    return [];
  }
}

function persistStoredValue(key: string, value: number | string[] | null): void {
  if (typeof window === "undefined") {
    return;
  }
  if (value === null) {
    window.localStorage.removeItem(key);
    return;
  }
  if (typeof value === "number") {
    window.localStorage.setItem(key, String(value));
    return;
  }
  window.localStorage.setItem(key, JSON.stringify(value));
}

function findNodeTrail(nodes: TreeNode[], targetId: string): TreeNode[] {
  const trail: TreeNode[] = [];
  const walk = (candidates: TreeNode[]): boolean => {
    for (const node of candidates) {
      trail.push(node);
      if (node.id === targetId) {
        return true;
      }
      if (walk(node.children)) {
        return true;
      }
      trail.pop();
    }
    return false;
  };
  return walk(nodes) ? [...trail] : [];
}

function findNodeById(nodes: TreeNode[], targetId: string): TreeNode | null {
  const trail = findNodeTrail(nodes, targetId);
  return trail.length ? trail[trail.length - 1] : null;
}

function resizeHandleStyles() {
  return {
    display: { xs: "none", lg: "block" },
    width: 12,
    borderRadius: 2,
    cursor: "col-resize",
    position: "relative",
    "&::before": {
      content: '""',
      position: "absolute",
      top: 8,
      bottom: 8,
      left: "50%",
      width: 4,
      transform: "translateX(-50%)",
      borderRadius: 999,
      bgcolor: "divider",
      transition: "background-color 150ms ease",
    },
    "&:hover::before": {
      bgcolor: "text.secondary",
    },
  } as const;
}

function replaceNodeChildren(nodes: TreeNode[], targetId: string, children: TreeNode[]): TreeNode[] {
  let changed = false;
  const nextNodes = nodes.map((node) => {
    if (node.id === targetId) {
      changed = true;
      return {
        ...node,
        children,
        metadata: {
          ...node.metadata,
          children_loaded: true,
          child_count: children.length,
        },
      };
    }
    if (!node.children.length) {
      return node;
    }
    const nextChildren = replaceNodeChildren(node.children, targetId, children);
    if (nextChildren !== node.children) {
      changed = true;
      return { ...node, children: nextChildren };
    }
    return node;
  });
  return changed ? nextNodes : nodes;
}

function mergeTreeNodesPreservingLoadedChildren(baseNodes: TreeNode[], currentNodes: TreeNode[]): TreeNode[] {
  const collectNodesById = (nodes: TreeNode[], lookup = new Map<string, TreeNode>()): Map<string, TreeNode> => {
    for (const node of nodes) {
      lookup.set(node.id, node);
      collectNodesById(node.children, lookup);
    }
    return lookup;
  };
  const baseById = collectNodesById(baseNodes);
  const currentById = collectNodesById(currentNodes);
  const mergeNode = (baseNode: TreeNode): TreeNode => {
    const currentNode = currentById.get(baseNode.id);
    if (!currentNode) {
      return baseNode;
    }
    const hasLoadedChildren = currentNode.children.length > 0 || currentNode.metadata.children_loaded === true;
    const nextChildren = hasLoadedChildren
      ? currentNode.children.map((child) => mergeNode(baseById.get(child.id) ?? child))
      : baseNode.children.map((child) => mergeNode(child));
    return {
      ...baseNode,
      children: nextChildren,
      metadata: {
        ...currentNode.metadata,
        ...baseNode.metadata,
      },
    };
  };
  return baseNodes.map((node) => mergeNode(node));
}

function valueText(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return value;
  }
  return JSON.stringify(value, null, 2);
}

function branchLabel(branches: ProjectSummary["branches"], branchId: string): string {
  if (!branchId) {
    return "Default branch context";
  }
  return branches.find((branch) => branch.id === branchId)?.name ?? "Selected branch";
}

function normalizeLookupKey(value: string): string {
  return value.trim().toLowerCase();
}

function isRevisionValue(value: string): boolean {
  return /^\d+$/.test(value.trim());
}

function isOpaqueIdentifier(value: string): boolean {
  const cleaned = value.trim();
  if (!cleaned) {
    return false;
  }
  return (
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(cleaned) ||
    /^[0-9a-f]{24,32}$/i.test(cleaned)
  );
}

function humanizeFieldLabel(value: string): string {
  return value
    .replace(/^kerml:/i, "")
    .replace(/^dcterms:/i, "")
    .replace(/^models:/i, "")
    .replace(/^esi\./i, "ESI ")
    .replace(/[_:.-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function normalizeContainmentKind(value: unknown): string {
  return String(value ?? "")
    .replace(/[_:.-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .toLowerCase();
}

function isHiddenContainmentPackage(node: TreeNode): boolean {
  const nodeType = normalizeContainmentKind(node.node_type);
  const metaclass = normalizeContainmentKind(node.metadata.metaclass);
  return nodeType === "package import" || nodeType === "element import" || metaclass === "package import" || metaclass === "element import";
}

function isAuxiliaryResourceNode(node: TreeNode): boolean {
  const label = normalizeContainmentKind(node.label);
  const path = normalizeContainmentKind(node.path);
  const nodeType = normalizeContainmentKind(node.node_type);
  const metaclass = normalizeContainmentKind(node.metadata.metaclass);
  const rawLabel = String(node.label ?? "").trim();
  const rawPath = String(node.path ?? "").trim();
  const combined = `${label} ${path} ${nodeType} ${metaclass}`;
  if (isHiddenContainmentPackage(node)) {
    return true;
  }
  if (/\[[^\]]+\.mdzip\]/i.test(rawLabel) || /\[[^\]]+\.mdzip\]/i.test(rawPath)) {
    return true;
  }
  return (
    label === "author" ||
    label.startsWith("author ") ||
    label === "additional elements" ||
    label === "derived properties" ||
    label === "iso 80000" ||
    label.startsWith("iso 80000 ") ||
    label.startsWith("md customization ") ||
    label === "uml standard profile" ||
    label === "sysml" ||
    label === "sysml profile" ||
    label === "si valuetype library" ||
    label === "sidefinitions" ||
    label === "qudv" ||
    combined.includes("auxiliary resource") ||
    combined.includes("applied project") ||
    combined.includes("resource usage") ||
    combined.includes("used project")
  );
}

function isAppliedStereotypeNode(node: TreeNode): boolean {
  const label = normalizeContainmentKind(node.label);
  const path = normalizeContainmentKind(node.path);
  const nodeType = normalizeContainmentKind(node.node_type);
  const metaclass = normalizeContainmentKind(node.metadata.metaclass);
  const combined = `${label} ${path} ${nodeType} ${metaclass}`;
  return (
    combined.includes("stereotype") ||
    combined.includes("tagged value") ||
    combined.includes("profile application") ||
    combined.includes("extension") ||
    combined.includes("diagraminfo")
  );
}

interface ContainmentTreeVisibility {
  showAuxiliaryResources: boolean;
  showAppliedStereotypes: boolean;
}

function filterContainmentTree(nodes: TreeNode[], visibility: ContainmentTreeVisibility): TreeNode[] {
  return nodes
    .filter((node) => visibility.showAuxiliaryResources || !isAuxiliaryResourceNode(node))
    .filter((node) => visibility.showAppliedStereotypes || !isAppliedStereotypeNode(node))
    .map((node) => ({
      ...node,
      children: filterContainmentTree(node.children, visibility),
    }));
}

function projectSummaryText(project: ProjectSummary): string {
  return project.description || "Project available for model exploration.";
}

function compareDisplayValues(left: string, right: string): number {
  return left.localeCompare(right, undefined, { sensitivity: "base", numeric: true });
}

function resolvedNameForId(value: string, lookup: Record<string, string>): string | null {
  const normalized = normalizeLookupKey(value);
  const resolved = lookup[normalized]?.trim();
  if (!resolved) {
    return null;
  }
  return normalizeLookupKey(resolved) === normalized ? null : resolved;
}

function friendlyPath(path: string, lookup: Record<string, string>): string {
  const cleaned = path.trim();
  if (!cleaned) {
    return "";
  }
  return cleaned
    .split("/")
    .map((segment) => {
      const trimmed = segment.trim();
      return resolvedNameForId(trimmed, lookup) ?? (isOpaqueIdentifier(trimmed) ? "Unnamed item" : trimmed);
    })
    .join(" / ");
}

function finalPathSegment(path: string, lookup: Record<string, string>): string {
  const formattedPath = friendlyPath(path, lookup);
  if (!formattedPath) {
    return "";
  }
  const segments = formattedPath
    .split(" / ")
    .map((segment) => segment.trim())
    .filter(Boolean);
  return segments[segments.length - 1] ?? "";
}

function humanReadableReference(value: string, lookup: Record<string, string>): string {
  const cleaned = value.trim();
  if (!cleaned) {
    return "";
  }
  const resolved = resolvedNameForId(cleaned, lookup);
  if (resolved) {
    return resolved;
  }
  if (isRevisionValue(cleaned)) {
    return `Revision ${cleaned}`;
  }
  const resolvedPath = cleaned.includes("/") ? friendlyPath(cleaned, lookup) : "";
  if (resolvedPath && resolvedPath !== cleaned) {
    return resolvedPath;
  }
  return isOpaqueIdentifier(cleaned) ? "Referenced item" : cleaned;
}

function displayEntityName(name: string, id: string, itemType: string, lookup: Record<string, string>, path = ""): string {
  const pathTail = finalPathSegment(path, lookup).split("::").pop()?.trim() ?? "";
  if (pathTail && normalizeLookupKey(pathTail) !== normalizeLookupKey(id)) {
    return pathTail;
  }
  const cleanedName = (name.trim().split("::").pop() ?? "").trim();
  if (cleanedName && normalizeLookupKey(cleanedName) !== normalizeLookupKey(id)) {
    return cleanedName;
  }
  return resolvedNameForId(id, lookup) ?? `Unnamed ${humanizeFieldLabel(itemType || "item")}`;
}

function itemReferenceDisplayName(reference: ItemReference, lookup: Record<string, string>): string {
  return displayEntityName(reference.name, reference.id, reference.item_type, lookup, reference.path);
}

function itemReferenceSecondaryText(reference: ItemReference, lookup: Record<string, string>): string {
  const path = friendlyPath(reference.path, lookup);
  if (path) {
    return path;
  }
  if (reference.relationship_type) {
    return humanizeFieldLabel(reference.relationship_type);
  }
  return humanizeFieldLabel(reference.item_type);
}

function itemReferenceTypeLabel(reference: ItemReference): string {
  return humanizeFieldLabel(reference.relationship_type || reference.item_type || "item");
}

function humanizeFieldPath(path: string): string {
  return path
    .split(".")
    .map((segment) =>
      segment
        .replace(/\[(\d+)\]/g, " $1")
        .trim(),
    )
    .map((segment) => humanizeFieldLabel(segment || "Value"))
    .join(" / ");
}

function resolveDisplayValue(value: unknown, lookup: Record<string, string>): unknown {
  if (typeof value === "string") {
    return humanReadableReference(value, lookup);
  }
  if (Array.isArray(value)) {
    return value.map((item) => resolveDisplayValue(item, lookup));
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    const displayName = [record.human_name, record.humanName, record.name, record.label, record.title, record.qualifiedName, record.qualified_name, record.id]
      .map((candidate) => (typeof candidate === "string" ? candidate.trim() : ""))
      .find(Boolean);
    const displayId = typeof record.id === "string" && record.id.trim() ? record.id.trim() : "";
    if (displayName && Object.keys(record).some((key) => ["id", "name", "human_name", "humanName", "qualifiedName", "qualified_name", "metaclass"].includes(key))) {
      const resolved = displayId ? resolvedNameForId(displayId, lookup) : null;
      return resolved ?? humanReadableReference(displayName, lookup);
    }
    return Object.fromEntries(
      Object.entries(record).map(([key, nestedValue]) => [key, resolveDisplayValue(nestedValue, lookup)]),
    );
  }
  return value;
}

function humanReadableValue(value: unknown, lookup: Record<string, string>): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "string") {
    return humanReadableReference(value, lookup);
  }
  const resolved = resolveDisplayValue(value, lookup);
  if (typeof resolved === "string") {
    return resolved;
  }
  return JSON.stringify(resolved, null, 2);
}

function hasMeaningfulValue(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    return value.trim().length > 0;
  }
  if (Array.isArray(value)) {
    return value.length > 0;
  }
  if (typeof value === "object") {
    return Object.keys(value as Record<string, unknown>).length > 0;
  }
  return true;
}

interface InspectorRow {
  key: string;
  label: string;
  value: string;
  rawValue?: unknown;
}

interface DataTableRow {
  key: string;
  cells: Array<string | ReactNode>;
  targetIds?: Record<number, string>;
  indentCells?: Record<number, number>;
}

const SPECIFICATION_FIELD_HINTS = ["specification", "expression", "formula", "guard", "condition", "language", "body", "constraint"];
const CONSTRAINT_FIELD_HINTS = ["constraint", "constrained", "guard", "condition", "rule", "expression"];
const NAVIGATION_FIELD_HINTS = ["navigation", "hyperlink", "link", "url", "uri", "target"];
const TAG_FIELD_HINTS = ["tag", "tagged", "stereotype", "profile", "author", "created", "creation", "modified", "diagraminfo"];
const TRACEABILITY_FIELD_HINTS = ["trace", "traced", "traceability", "satisf", "verify", "refine", "realiz", "specif"];
const ALLOCATION_FIELD_HINTS = ["allocat"];
const PROPERTY_FIELD_HINTS = [
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
  "todo",
];

function normalizedFieldKey(value: string): string {
  return value.replace(/[^a-z0-9]/gi, "").toLowerCase();
}

function keyMatchesHints(key: string, hints: string[]): boolean {
  const normalized = normalizedFieldKey(key);
  return hints.some((hint) => normalized.includes(normalizedFieldKey(hint)));
}

function isPackageLikeItemType(itemType?: string | null): boolean {
  return normalizedFieldKey(String(itemType ?? "")).includes("package");
}

function specificationChildSectionsForItem(item: Pick<ItemDetails, "item_type">): SpecificationSectionId[] {
  return isPackageLikeItemType(item.item_type) ? PACKAGE_SPECIFICATION_CHILD_SECTIONS : SPECIFICATION_CHILD_SECTIONS;
}

function dedupeInspectorRows(rows: InspectorRow[]): InspectorRow[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const key = `${row.label}::${row.value}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function dedupeInspectorRowsByLabel(rows: InspectorRow[]): InspectorRow[] {
  const seen = new Set<string>();
  return rows.filter((row) => {
    const key = normalizedFieldKey(row.label);
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function cameoOrderedInspectorRows(rows: InspectorRow[], itemType?: string | null): InspectorRow[] {
  const orderIndex = isPackageLikeItemType(itemType) ? CAMEO_PACKAGE_SPECIFICATION_PROPERTY_LABEL_INDEX : CAMEO_SPECIFICATION_PROPERTY_LABEL_INDEX;
  return rows
    .map((row, originalIndex) => ({ row, originalIndex }))
    .sort((left, right) => {
      const leftOrder = orderIndex.get(normalizedFieldKey(left.row.label));
      const rightOrder = orderIndex.get(normalizedFieldKey(right.row.label));
      if (leftOrder !== undefined || rightOrder !== undefined) {
        return (leftOrder ?? Number.MAX_SAFE_INTEGER) - (rightOrder ?? Number.MAX_SAFE_INTEGER) || left.originalIndex - right.originalIndex;
      }
      return left.originalIndex - right.originalIndex;
    })
    .map(({ row }) => row);
}

function mapToInspectorRows(source: Record<string, unknown>, lookup: Record<string, string>): InspectorRow[] {
  return Object.entries(source)
    .filter(([, value]) => hasMeaningfulValue(value))
    .sort(([leftKey], [rightKey]) => compareDisplayValues(humanizeFieldLabel(leftKey), humanizeFieldLabel(rightKey)))
    .map(([key, value]) => ({
      key,
      label: humanizeFieldLabel(key),
      value: humanReadableValue(value, lookup),
    }));
}

function isInlineDisplayValue(value: unknown): boolean {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return true;
  }
  if (Array.isArray(value)) {
    return value.length > 0 && value.length <= 4 && value.every((entry) => typeof entry === "string" || typeof entry === "number" || typeof entry === "boolean");
  }
  return false;
}

function humanReadableInlineValue(value: unknown, lookup: Record<string, string>): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (Array.isArray(value)) {
    return value.map((entry) => humanReadableReference(String(entry), lookup)).join(", ");
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "number") {
    return String(value);
  }
  return humanReadableReference(String(value), lookup);
}

function mapInlineInspectorRows(source: Record<string, unknown>, lookup: Record<string, string>): InspectorRow[] {
  return Object.entries(source)
    .filter(([, value]) => hasMeaningfulValue(value) && isInlineDisplayValue(value))
    .sort(([leftKey], [rightKey]) => compareDisplayValues(humanizeFieldLabel(leftKey), humanizeFieldLabel(rightKey)))
    .map(([key, value]) => ({
      key,
      label: humanizeFieldLabel(key),
      value: humanReadableInlineValue(value, lookup),
    }));
}

function payloadAttributes(item: ItemDetails): Record<string, unknown> {
  const sourcePayload = item.source_payload ?? {};
  return sourcePayload.attributes && typeof sourcePayload.attributes === "object" && !Array.isArray(sourcePayload.attributes)
    ? (sourcePayload.attributes as Record<string, unknown>)
    : {};
}

function payloadReferences(item: ItemDetails): Record<string, unknown> {
  const sourcePayload = item.source_payload ?? {};
  return sourcePayload.references && typeof sourcePayload.references === "object" && !Array.isArray(sourcePayload.references)
    ? (sourcePayload.references as Record<string, unknown>)
    : {};
}

const SPECIFICATION_SECTION_SOURCE_KEYS: Record<SpecificationSectionId, string[]> = {
  properties: ["properties"],
  documentation: ["documentation"],
  navigation: ["navigation"],
  "usage-diagrams": ["usageDiagrams", "usage_diagrams"],
  "usage-in": ["usageIn", "usage_in"],
  "ports-interfaces": ["portsInterfaces", "ports_interfaces"],
  "element-properties": ["properties", "metamodel"],
  attributes: ["attributes"],
  ports: ["ports"],
  operations: ["operations"],
  receptions: ["receptions"],
  behaviors: ["behaviors"],
  "inner-elements": ["innerElements", "inner_elements"],
  relations: ["relations"],
  tags: ["tags"],
  constraints: ["constraints"],
  traceability: ["traceability"],
  allocations: ["allocations"],
  "template-parameters": ["templateParameters", "template_parameters"],
  instances: ["instances"],
};

function payloadSpecSections(item: ItemDetails): Record<string, unknown> {
  const sourcePayload = item.source_payload ?? {};
  const candidate = sourcePayload.spec_sections ?? sourcePayload.specSections;
  return candidate && typeof candidate === "object" && !Array.isArray(candidate) ? (candidate as Record<string, unknown>) : {};
}

function payloadNativeMetamodelEntries(item: ItemDetails): Array<Record<string, unknown>> {
  const metamodel = payloadSpecSections(item).metamodel;
  if (!metamodel || typeof metamodel !== "object" || Array.isArray(metamodel)) {
    return [];
  }
  const entries = (metamodel as Record<string, unknown>).entries;
  return Array.isArray(entries)
    ? entries.filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object" && !Array.isArray(entry))
    : [];
}

function payloadNativeStereotypeSections(item: ItemDetails): Array<Record<string, unknown>> {
  const sections = payloadSpecSections(item).stereotypes;
  return Array.isArray(sections)
    ? sections.filter((section): section is Record<string, unknown> => Boolean(section) && typeof section === "object" && !Array.isArray(section))
    : [];
}

function nativeSpecificationState(entry: Record<string, unknown>): string {
  const flags = [
    entry.set === true ? "set" : "default/unset",
    entry.derived === true ? "derived" : "",
    entry.readOnly === true || entry.changeable === false ? "read-only" : "",
    entry.transient === true ? "transient" : "",
    entry.volatile === true ? "volatile" : "",
  ].filter(Boolean);
  return flags.join(", ");
}

function nativeEntryDisplayValue(entry: Record<string, unknown>, lookup: Record<string, string>): string {
  return humanReadableValue(hasMeaningfulValue(entry.value) ? entry.value : entry.defaultValue, lookup);
}

function payloadNativeMetamodelEntryIndex(item: ItemDetails): Map<string, Record<string, unknown>> {
  const index = new Map<string, Record<string, unknown>>();
  for (const entry of payloadNativeMetamodelEntries(item)) {
    for (const candidate of [entry.id, entry.name]) {
      if (typeof candidate === "string" && candidate.trim()) {
        index.set(normalizedFieldKey(candidate), entry);
      }
    }
  }
  return index;
}

function nativeEntryValue(entry: Record<string, unknown> | undefined): unknown {
  if (!entry) {
    return undefined;
  }
  return hasMeaningfulValue(entry.value) ? entry.value : entry.defaultValue;
}

function firstReferencedElementId(value: unknown): string {
  if (Array.isArray(value)) {
    for (const entry of value) {
      const id = firstReferencedElementId(entry);
      if (id) {
        return id;
      }
    }
    return "";
  }
  if (value && typeof value === "object") {
    const id = (value as Record<string, unknown>).id;
    return typeof id === "string" && id.trim() ? id.trim() : "";
  }
  if (typeof value === "string" && isOpaqueIdentifier(value.trim())) {
    return value.trim();
  }
  return "";
}

function nativeReferenceRowsForHints(
  item: ItemDetails,
  lookup: Record<string, string>,
  hints: string[],
  options?: { includeUnset?: boolean; defaultType?: string },
): DataTableRow[] {
  return payloadNativeMetamodelEntries(item)
    .filter((entry) => {
      const kind = typeof entry.kind === "string" ? entry.kind.toLowerCase() : "";
      const entryName = String(entry.name ?? entry.id ?? "");
      const value = hasMeaningfulValue(entry.value) ? entry.value : entry.defaultValue;
      if (!options?.includeUnset && !hasMeaningfulValue(value)) {
        return false;
      }
      return kind === "reference" && keyMatchesHints(entryName, hints);
    })
    .map((entry, index) => {
      const value = hasMeaningfulValue(entry.value) ? entry.value : entry.defaultValue;
      const targetId = firstReferencedElementId(value);
      return {
        key: `native-reference-${String(entry.id ?? index)}`,
        targetIds: targetId ? { 1: targetId } : undefined,
        cells: [
          String(entry.name ?? entry.id ?? options?.defaultType ?? "Reference"),
          nativeEntryDisplayValue(entry, lookup),
          String(entry.valueType ?? entry.kind ?? options?.defaultType ?? ""),
        ],
      };
    });
}

function nativeStereotypeTagRows(item: ItemDetails, lookup: Record<string, string>): DataTableRow[] {
  return payloadNativeStereotypeSections(item).flatMap((section, sectionIndex) => {
    const entries = Array.isArray(section.entries)
      ? section.entries.filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object" && !Array.isArray(entry))
      : [];
    const sectionName = String(section.name ?? section.qualifiedName ?? `Stereotype ${sectionIndex + 1}`);
    const headerRows: DataTableRow[] = [
      {
        key: `native-stereotype-section-${String(section.id ?? sectionIndex)}`,
        cells: ["Applied Stereotype", humanReadableValue(sectionName, lookup)],
      },
    ];
    const propertyRows = entries
      .filter((entry) => hasMeaningfulValue(entry.value) || hasMeaningfulValue(entry.defaultValue) || entry.set === true)
      .map((entry, entryIndex) => ({
        key: `native-stereotype-tag-${String(section.id ?? sectionIndex)}-${String(entry.id ?? entryIndex)}`,
        cells: [
          `${sectionName} / ${String(entry.name ?? entry.id ?? "Property")}`,
          nativeEntryDisplayValue(entry, lookup),
        ],
      }));
    return [...headerRows, ...propertyRows];
  });
}

function payloadSpecSection(item: ItemDetails, section: SpecificationSectionId): Record<string, unknown> {
  const sections = payloadSpecSections(item);
  for (const key of SPECIFICATION_SECTION_SOURCE_KEYS[section]) {
    const candidate = sections[key];
    if (candidate && typeof candidate === "object" && !Array.isArray(candidate)) {
      return candidate as Record<string, unknown>;
    }
  }
  return {};
}

function payloadSpecSectionEntries(item: ItemDetails, section: SpecificationSectionId): Array<Record<string, unknown>> {
  const candidate = payloadSpecSection(item, section).entries;
  if (!Array.isArray(candidate)) {
    return [];
  }
  return candidate.filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object" && !Array.isArray(entry));
}

function payloadSpecSectionStrings(item: ItemDetails, section: SpecificationSectionId, fieldName: string): string[] {
  const sectionPayload = payloadSpecSection(item, section);
  const candidate = sectionPayload[fieldName];
  if (typeof candidate === "string" && candidate.trim()) {
    return [candidate.trim()];
  }
  if (!Array.isArray(candidate)) {
    return [];
  }
  return candidate
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim())
    .filter(Boolean);
}

function structuredEntryValue(entry: Record<string, unknown>, keys: string[], lookup: Record<string, string>): string {
  for (const key of keys) {
    if (!hasMeaningfulValue(entry[key])) {
      continue;
    }
    return humanReadableValue(entry[key], lookup);
  }
  return "";
}

function structuredEntryName(entry: Record<string, unknown>, fallback = "Value"): string {
  const candidate = entry.name;
  return typeof candidate === "string" && candidate.trim() ? candidate.trim() : fallback;
}

function payloadExtraSections(item: ItemDetails): Array<[string, unknown]> {
  const sourcePayload = item.source_payload ?? {};
  return Object.entries(sourcePayload).filter(([key, value]) => {
    if (
      [
        "element_id",
        "model_id",
        "local_id",
        "owner_id",
        "name",
        "human_name",
        "qualified_name",
        "human_type",
        "metaclass",
        "documentation",
        "diagram_type",
        "diagram_preview_format",
        "diagram_preview_base64",
        "owned_element_ids",
        "applied_stereotype_ids",
        "diagram_element_ids",
        "attributes",
        "references",
        "spec_sections",
        "specSections",
      ].includes(key)
    ) {
      return false;
    }
    return hasMeaningfulValue(value);
  });
}

function diagramPreviewDataUrl(item: ItemDetails): string | null {
  const sourcePayload = item.source_payload ?? {};
  const format = typeof sourcePayload.diagram_preview_format === "string" ? sourcePayload.diagram_preview_format.trim() : "";
  const encoded = typeof sourcePayload.diagram_preview_base64 === "string" ? sourcePayload.diagram_preview_base64.trim() : "";
  if (!format || !encoded) {
    return null;
  }
  return `data:${format};base64,${encoded}`;
}

function isDiagramLikeItem(item: ItemDetails | null | undefined): boolean {
  if (!item) {
    return false;
  }
  const sourcePayload = item.source_payload ?? {};
  const candidates = [
    item.item_type,
    item.name,
    item.description,
    typeof sourcePayload.human_type === "string" ? sourcePayload.human_type : "",
    typeof sourcePayload.metaclass === "string" ? sourcePayload.metaclass : "",
    typeof sourcePayload.diagram_type === "string" ? sourcePayload.diagram_type : "",
  ];
  return candidates.some((candidate) => String(candidate ?? "").toLowerCase().includes("diagram"));
}

function itemDetailsFromTreeNode(node: TreeNode, projectId: string, branchId: string): ItemDetails {
  const metaclass = typeof node.metadata.metaclass === "string" ? node.metadata.metaclass : "";
  const modelId = typeof node.metadata.model_id === "string" ? node.metadata.model_id : "";
  const qualifiedName = typeof node.metadata.qualified_name === "string" ? node.metadata.qualified_name : "";
  const childCount = typeof node.metadata.child_count === "number" ? node.metadata.child_count : 0;
  const stereotypes = Array.isArray(node.metadata.stereotypes)
    ? node.metadata.stereotypes.filter((value): value is string => typeof value === "string" && Boolean(value.trim()))
    : [];
  return {
    id: node.id,
    name: node.label || node.id,
    item_type: node.node_type || metaclass || "element",
    path: qualifiedName || node.path || node.id,
    project_id: projectId,
    branch_id: branchId,
    description: "",
    documentation_markdown: "",
    raw_types: [node.node_type, metaclass].filter((value): value is string => Boolean(value)),
    stereotypes,
    owner: null,
    type_references: [],
    contained_elements: [],
    related_items: [],
    metadata: {
      ...node.metadata,
      child_count: childCount,
      model_id: modelId,
      tree_node_fallback: true,
    },
    relationships: [],
    version: "",
    editable: false,
    attachment_supported: false,
    collaborators: [],
    source_payload: {
      element_id: node.id,
      name: node.label || node.id,
      human_name: node.label || node.id,
      human_type: node.node_type || metaclass || "element",
      metaclass,
      model_id: modelId,
      qualified_name: qualifiedName || node.path || "",
      child_count: childCount,
      tree_node_fallback: true,
    },
  };
}

function pythonLiteral(value: string): string {
  return JSON.stringify(value);
}

function workbenchManifestPythonScript(workbenchBaseUrl: string): string {
  return `from __future__ import annotations

import json

import requests

WORKBENCH_BASE_URL = ${pythonLiteral(workbenchBaseUrl)}
API_KEY = "replace-with-your-api-key"
VERIFY_TLS = True


def main() -> None:
    response = requests.get(
        f"{WORKBENCH_BASE_URL}/api/cache",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=60,
        verify=VERIFY_TLS,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    main()
`;
}

function workbenchListElementsPythonScript(
  workbenchBaseUrl: string,
  serverId: string,
  projectId: string,
  branchId: string,
): string {
  return `from __future__ import annotations

import json
from urllib.parse import urlencode

import requests

WORKBENCH_BASE_URL = ${pythonLiteral(workbenchBaseUrl)}
API_KEY = "replace-with-your-api-key"
SERVER_ID = ${pythonLiteral(serverId)}
PROJECT_ID = ${pythonLiteral(projectId)}
BRANCH_ID = ${pythonLiteral(branchId)}
VERIFY_TLS = True


def main() -> None:
    query = urlencode({"allResults": "true"})
    response = requests.get(
        f"{WORKBENCH_BASE_URL}/api/cache/servers/{SERVER_ID}/projects/{PROJECT_ID}/branches/{BRANCH_ID}/elements?{query}",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=120,
        verify=VERIFY_TLS,
    )
    response.raise_for_status()
    payload = response.json()
    print(json.dumps(payload, indent=2))
    print(f"Returned {len(payload.get('items', []))} stored elements.")


if __name__ == "__main__":
    main()
`;
}

function workbenchFullTreePythonScript(
  workbenchBaseUrl: string,
  serverId: string,
  projectId: string,
  branchId: string,
): string {
  return `from __future__ import annotations

import json
from urllib.parse import urlencode

import requests

WORKBENCH_BASE_URL = ${pythonLiteral(workbenchBaseUrl)}
API_KEY = "replace-with-your-api-key"
SERVER_ID = ${pythonLiteral(serverId)}
PROJECT_ID = ${pythonLiteral(projectId)}
BRANCH_ID = ${pythonLiteral(branchId)}
VERIFY_TLS = True


def main() -> None:
    # Omit depth to return the complete accessible containment tree.
    query = urlencode({"includeOrphans": "true"})
    response = requests.get(
        f"{WORKBENCH_BASE_URL}/api/cache/servers/{SERVER_ID}/projects/{PROJECT_ID}/branches/{BRANCH_ID}/tree?{query}",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=300,
        verify=VERIFY_TLS,
    )
    response.raise_for_status()
    payload = response.json()
    print(json.dumps(payload, indent=2))
    print(f"Returned {payload.get('total_nodes', 0)} accessible model-tree nodes.")


if __name__ == "__main__":
    main()
`;
}

function workbenchStereotypeSearchPythonScript(
  workbenchBaseUrl: string,
  serverId: string,
  projectId: string,
  branchId: string,
): string {
  return `from __future__ import annotations

import json
from urllib.parse import urlencode

import requests

WORKBENCH_BASE_URL = ${pythonLiteral(workbenchBaseUrl)}
API_KEY = "replace-with-your-api-key"
SERVER_ID = ${pythonLiteral(serverId)}
PROJECT_ID = ${pythonLiteral(projectId)}
BRANCH_ID = ${pythonLiteral(branchId)}
STEREOTYPE_NAME = "Block"
INCLUDE_DETAILS = True
VERIFY_TLS = True


def main() -> None:
    query = urlencode(
        {
            "stereotype": STEREOTYPE_NAME,
            "includeDetails": str(INCLUDE_DETAILS).lower(),
            "limit": 500,
            "offset": 0,
        }
    )
    response = requests.get(
        f"{WORKBENCH_BASE_URL}/api/cache/servers/{SERVER_ID}/projects/{PROJECT_ID}/branches/{BRANCH_ID}/elements/by-stereotype?{query}",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=120,
        verify=VERIFY_TLS,
    )
    response.raise_for_status()
    payload = response.json()
    print(json.dumps(payload, indent=2))
    print(f"Matched {payload.get('total', 0)} elements for stereotype {STEREOTYPE_NAME!r}.")


if __name__ == "__main__":
    main()
`;
}

function workbenchNativeSpecificationPythonScript(
  workbenchBaseUrl: string,
  serverId: string,
  projectId: string,
  branchId: string,
  elementId: string,
): string {
  return `from __future__ import annotations

import json
from urllib.parse import quote

import requests

WORKBENCH_BASE_URL = ${pythonLiteral(workbenchBaseUrl)}
API_KEY = "replace-with-your-api-key"
SERVER_ID = ${pythonLiteral(serverId)}
PROJECT_ID = ${pythonLiteral(projectId)}
BRANCH_ID = ${pythonLiteral(branchId)}
ELEMENT_ID = ${pythonLiteral(elementId)}
VERIFY_TLS = True


def main() -> None:
    response = requests.get(
        f"{WORKBENCH_BASE_URL}/api/cache/servers/{SERVER_ID}/projects/{PROJECT_ID}/branches/{BRANCH_ID}/elements/{quote(ELEMENT_ID, safe='')}/details",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=120,
        verify=VERIFY_TLS,
    )
    response.raise_for_status()
    source = response.json().get("source_payload") or {}
    specification = source.get("spec_sections") or source.get("specSections") or {}
    print(json.dumps(specification, indent=2))


if __name__ == "__main__":
    main()
`;
}

function workbenchSpecDiagnosticPythonScript(
  workbenchBaseUrl: string,
  serverId: string,
  projectId: string,
  branchId: string,
  elementId: string,
): string {
  return `from __future__ import annotations

import json
from urllib.parse import urlencode

import requests

WORKBENCH_BASE_URL = ${pythonLiteral(workbenchBaseUrl)}
API_KEY = "replace-with-your-api-key"
SERVER_ID = ${pythonLiteral(serverId)}
PROJECT_ID = ${pythonLiteral(projectId)}
BRANCH_ID = ${pythonLiteral(branchId)}
ELEMENT_ID = ${pythonLiteral(elementId)}
VERIFY_TLS = True


def main() -> None:
    # Workbench-only diagnostic: no live Teamwork Cloud/API call.
    # Use one or more elementId query values for exact elements, or remove
    # elementId to return the first LIMIT accessible cached branch elements.
    query = urlencode(
        {
            "elementId": ELEMENT_ID,
            "limit": 25,
            "includeRawPayload": "true",
            "includeDetails": "true",
        }
    )
    response = requests.get(
        f"{WORKBENCH_BASE_URL}/api/cache/servers/{SERVER_ID}/projects/{PROJECT_ID}/branches/{BRANCH_ID}/spec-diagnostic?{query}",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=180,
        verify=VERIFY_TLS,
    )
    response.raise_for_status()
    payload = response.json()
    print(json.dumps(payload, indent=2))
    print("Use payload['cameo_spec_page_inputs'] and payload['elements'][*] to build the Cameo-to-Workbench mapping table.")


if __name__ == "__main__":
    main()
`;
}

function workbenchProjectDumpPythonScript(
  workbenchBaseUrl: string,
  serverId: string,
  projectId: string,
): string {
  return `from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlencode

import requests

WORKBENCH_BASE_URL = ${pythonLiteral(workbenchBaseUrl)}
API_KEY = "replace-with-your-api-key"
SERVER_ID = ${pythonLiteral(serverId)}
PROJECT_ID = ${pythonLiteral(projectId)}
BRANCH_ID = "trunk"
OUTPUT_FILE = Path("workbench_project_trunk_dump.json")
VERIFY_TLS = True


def main() -> None:
    # One Workbench API call. This reads the stored Cameo plugin snapshot and
    # does not try to reconstruct model content from Teamwork Cloud REST.
    query = urlencode(
        {
            "branchId": BRANCH_ID,
            "includeTree": "true",
            "includeElements": "true",
            "includeDetails": "true",
            "includeRawPayload": "true",
            "includePermissions": "true",
        }
    )
    response = requests.get(
        f"{WORKBENCH_BASE_URL}/api/cache/servers/{SERVER_ID}/projects/{PROJECT_ID}/dump?{query}",
        headers={"Authorization": f"Bearer {API_KEY}"},
        timeout=600,
        verify=VERIFY_TLS,
    )
    response.raise_for_status()
    payload = response.json()
    OUTPUT_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    selection = payload.get("selection", {})
    resolved = payload.get("resolved", {})
    print(f"Saved {OUTPUT_FILE.resolve()}")
    print(
        "Dumped "
        f"{selection.get('visible_model_count', 0)} models and "
        f"{selection.get('visible_element_count', 0)} elements from "
        f"{resolved.get('project_id')} / {resolved.get('branch_name') or resolved.get('branch_id')}."
    )


if __name__ == "__main__":
    main()
`;
}

function workbenchEditElementPythonScript(
  workbenchBaseUrl: string,
  serverId: string,
  projectId: string,
  branchId: string,
  elementId: string,
): string {
  return `from __future__ import annotations

import json

import requests

WORKBENCH_BASE_URL = ${pythonLiteral(workbenchBaseUrl)}
API_KEY = "replace-with-your-api-key"
SERVER_ID = ${pythonLiteral(serverId)}
PROJECT_ID = ${pythonLiteral(projectId)}
BRANCH_ID = ${pythonLiteral(branchId)}
ELEMENT_ID = ${pythonLiteral(elementId)}
VERIFY_TLS = True


def main() -> None:
    payload = {
        "documentation": "Updated from a full Python example in the Workbench Developer API tab."
    }
    response = requests.patch(
        f"{WORKBENCH_BASE_URL}/api/cache/servers/{SERVER_ID}/projects/{PROJECT_ID}/branches/{BRANCH_ID}/elements/{ELEMENT_ID}",
        headers={
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=120,
        verify=VERIFY_TLS,
    )
    response.raise_for_status()
    print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    main()
`;
}

function identityRows(item: ItemDetails, lookup: Record<string, string>): InspectorRow[] {
  const sourcePayload = item.source_payload ?? {};
  const fields: Record<string, unknown> = {
    id: item.id,
    type: item.item_type,
    path: friendlyPath(item.path, lookup),
    qualified_name: sourcePayload.qualified_name,
    metaclass: sourcePayload.metaclass,
    model_id: sourcePayload.model_id,
    local_id: sourcePayload.local_id,
    owner_id: sourcePayload.owner_id,
    version: item.version,
  };
  return mapToInspectorRows(fields, lookup);
}

function overviewRows(item: ItemDetails, lookup: Record<string, string>): InspectorRow[] {
  const fields: Record<string, unknown> = {
    name: item.name,
    description: item.description,
    stereotypes: item.stereotypes,
    raw_types: item.raw_types,
  };
  return mapToInspectorRows(fields, lookup);
}

function cameoPropertySpecificationRows(item: ItemDetails, lookup: Record<string, string>): InspectorRow[] {
  const metadata = item.metadata ?? {};
  const sourcePayload = item.source_payload ?? {};
  const metaclass = String(sourcePayload.metaclass ?? item.item_type ?? "").replace(/[^a-z0-9]/gi, "").toLowerCase();
  if (metaclass !== "property" && metaclass !== "port") {
    return [];
  }
  const rows: InspectorRow[] = [];
  const push = (key: string, label: string, value: unknown) => {
    if (!hasMeaningfulValue(value)) {
      return;
    }
    rows.push({
      key,
      label,
      value: humanReadableValue(value, lookup),
    });
  };
  push("cameo.signature", "Signature", metadata.cameo_signature);
  push("cameo.name", "Name", metadata.cameo_name);
  push("cameo.type", "Type", metadata.cameo_type || item.type_references[0]?.path || item.type_references[0]?.name);
  push("cameo.multiplicity", "Multiplicity", metadata.multiplicity);
  push("cameo.visibility", "Visibility", metadata.visibility);
  push("cameo.owner", "Owner", item.owner ? itemReferenceDisplayName(item.owner, lookup) : "");
  push("cameo.stereotype", "Applied Stereotypes", item.stereotypes);
  return rows;
}

function specificationRows(item: ItemDetails, lookup: Record<string, string>): InspectorRow[] {
  const structuredRows = payloadSpecSectionEntries(item, "properties").map((entry, index) => ({
    key: `spec.properties.${index}.${structuredEntryName(entry)}`,
    label: structuredEntryName(entry),
    value: structuredEntryValue(entry, ["value"], lookup),
    rawValue: entry.value,
  }));
  const sourcePayload = item.source_payload ?? {};
  const attributes = payloadAttributes(item);
  const references = payloadReferences(item);
  const rows: InspectorRow[] = [...cameoPropertySpecificationRows(item, lookup), ...structuredRows];

  const pushRows = (source: Record<string, unknown>, sectionPrefix = "") => {
    for (const [key, value] of Object.entries(source)) {
      if (!keyMatchesHints(key, SPECIFICATION_FIELD_HINTS) || !hasMeaningfulValue(value)) {
        continue;
      }
      rows.push({
        key: `${sectionPrefix}${key}`,
        label: humanizeFieldLabel(key),
        value: humanReadableValue(value, lookup),
      });
    }
  };

  pushRows(sourcePayload, "payload.");
  pushRows(attributes, "attributes.");
  pushRows(references, "references.");

  if (!rows.length && hasMeaningfulValue(item.documentation_markdown) && keyMatchesHints(item.item_type, ["constraint"])) {
    rows.push({
      key: "documentation_markdown",
      label: "Constraint Documentation",
      value: item.documentation_markdown,
    });
  }

  return cameoOrderedInspectorRows(dedupeInspectorRowsByLabel(dedupeInspectorRows(rows)), item.item_type);
}

function constraintRows(item: ItemDetails, lookup: Record<string, string>): InspectorRow[] {
  const attributes = payloadAttributes(item);
  const references = payloadReferences(item);
  const rows: InspectorRow[] = payloadSpecSectionEntries(item, "constraints").map((entry, index) => ({
    key: `spec.constraints.${index}.${structuredEntryName(entry)}`,
    label: structuredEntryName(entry),
    value: structuredEntryValue(entry, ["specification", "value"], lookup),
  }));

  const pushRows = (source: Record<string, unknown>, sectionPrefix = "") => {
    for (const [key, value] of Object.entries(source)) {
      if (!keyMatchesHints(key, CONSTRAINT_FIELD_HINTS) || !hasMeaningfulValue(value)) {
        continue;
      }
      rows.push({
        key: `${sectionPrefix}${key}`,
        label: humanizeFieldLabel(key),
        value: humanReadableValue(value, lookup),
      });
    }
  };

  pushRows(attributes, "attributes.");
  pushRows(references, "references.");

  return dedupeInspectorRows(
    rows.sort((left, right) => compareDisplayValues(left.label, right.label)),
  );
}

function constraintReferenceItems(item: ItemDetails): ItemReference[] {
  const seen = new Set<string>();
  const matchesConstraint = (reference: ItemReference) =>
    keyMatchesHints(reference.item_type, ["constraint"]) ||
    keyMatchesHints(reference.relationship_type, CONSTRAINT_FIELD_HINTS) ||
    keyMatchesHints(reference.name, ["constraint"]);

  return [...item.type_references, ...item.related_items, ...item.contained_elements].filter((reference) => {
    if (!matchesConstraint(reference)) {
      return false;
    }
    const key = `${reference.relationship_type}:${reference.id}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function collectHintRows(
  item: ItemDetails,
  lookup: Record<string, string>,
  hints: string[],
  options?: {
    includeSourcePayload?: boolean;
    includeAttributes?: boolean;
    includeReferences?: boolean;
    includeMetadata?: boolean;
    inlineOnly?: boolean;
  },
): InspectorRow[] {
  const resolved = {
    includeSourcePayload: options?.includeSourcePayload ?? true,
    includeAttributes: options?.includeAttributes ?? true,
    includeReferences: options?.includeReferences ?? true,
    includeMetadata: options?.includeMetadata ?? false,
    inlineOnly: options?.inlineOnly ?? false,
  };
  const rows: InspectorRow[] = [];
  const sourcePayload = item.source_payload ?? {};
  const sources: Array<[string, Record<string, unknown>]> = [];
  if (resolved.includeSourcePayload) {
    sources.push(["payload.", sourcePayload]);
  }
  if (resolved.includeAttributes) {
    sources.push(["attributes.", payloadAttributes(item)]);
  }
  if (resolved.includeReferences) {
    sources.push(["references.", payloadReferences(item)]);
  }
  if (resolved.includeMetadata) {
    sources.push(["metadata.", item.metadata ?? {}]);
  }
  for (const [prefix, source] of sources) {
    for (const [key, value] of Object.entries(source)) {
      if (!keyMatchesHints(key, hints) || !hasMeaningfulValue(value)) {
        continue;
      }
      if (resolved.inlineOnly && !isInlineDisplayValue(value)) {
        continue;
      }
      rows.push({
        key: `${prefix}${key}`,
        label: humanizeFieldLabel(key),
        value: resolved.inlineOnly ? humanReadableInlineValue(value, lookup) : humanReadableValue(value, lookup),
      });
    }
  }
  return dedupeInspectorRows(rows.sort((left, right) => compareDisplayValues(left.label, right.label)));
}

function uniqueItemReferences(references: ItemReference[]): ItemReference[] {
  const seen = new Set<string>();
  return references.filter((reference) => {
    const key = `${reference.relationship_type}:${reference.id}`;
    if (seen.has(key)) {
      return false;
    }
    seen.add(key);
    return true;
  });
}

function collectReferenceMatches(item: ItemDetails, hints: string[]): ItemReference[] {
  return uniqueItemReferences(
    [...item.type_references, ...item.related_items, ...item.contained_elements].filter((reference) => {
      return (
        keyMatchesHints(reference.relationship_type, hints) ||
        keyMatchesHints(reference.item_type, hints) ||
        keyMatchesHints(reference.name, hints) ||
        keyMatchesHints(reference.path, hints)
      );
    }),
  );
}

function extractCommentBlocks(item: ItemDetails): string[] {
  const sourcePayload = item.source_payload ?? {};
  const candidates = [
    item.documentation_markdown,
    item.description,
    sourcePayload.documentation,
    sourcePayload.comments,
    sourcePayload.comment,
    sourcePayload.owned_comments,
    sourcePayload.ownedComments,
  ];
  const blocks: string[] = [];
  for (const candidate of candidates) {
    if (typeof candidate === "string" && candidate.trim()) {
      blocks.push(candidate.trim());
    } else if (Array.isArray(candidate)) {
      for (const entry of candidate) {
        if (typeof entry === "string" && entry.trim()) {
          blocks.push(entry.trim());
        }
      }
    }
  }
  return Array.from(new Set(blocks));
}

function extractDocumentationSections(item: ItemDetails): { documentation: string[]; comments: string[] } {
  const structuredDocumentation = payloadSpecSectionStrings(item, "documentation", "documentation");
  const structuredComments = payloadSpecSectionStrings(item, "documentation", "comments");
  if (structuredDocumentation.length || structuredComments.length) {
    return {
      documentation: structuredDocumentation,
      comments: structuredComments,
    };
  }
  const sourcePayload = item.source_payload ?? {};
  const documentation = new Set<string>();
  const comments = new Set<string>();

  const addStrings = (target: Set<string>, value: unknown) => {
    if (typeof value === "string" && value.trim()) {
      target.add(value.trim());
      return;
    }
    if (Array.isArray(value)) {
      for (const entry of value) {
        if (typeof entry === "string" && entry.trim()) {
          target.add(entry.trim());
        }
      }
    }
  };

  addStrings(documentation, sourcePayload.documentation);
  addStrings(documentation, item.description);
  addStrings(documentation, item.documentation_markdown);

  addStrings(comments, sourcePayload.comments);
  addStrings(comments, sourcePayload.comment);
  addStrings(comments, sourcePayload.owned_comments);
  addStrings(comments, sourcePayload.ownedComments);

  if (!documentation.size && !comments.size) {
    for (const block of extractCommentBlocks(item)) {
      documentation.add(block);
    }
  }

  return {
    documentation: Array.from(documentation),
    comments: Array.from(comments),
  };
}

function hintRowsToTableRows(rows: InspectorRow[]): DataTableRow[] {
  return rows.map((row) => ({
    key: row.key,
    cells: [row.label, row.value || ""],
  }));
}

function referenceRowsToTableRows(references: ItemReference[], lookup: Record<string, string>, typeSelector?: (reference: ItemReference) => string): DataTableRow[] {
  return references.map((reference) => ({
    key: `${reference.relationship_type}:${reference.id}`,
    targetIds: { 0: reference.id },
    cells: [
      itemReferenceDisplayName(reference, lookup),
      typeSelector?.(reference) ?? itemReferenceTypeLabel(reference),
    ],
  }));
}

function relationshipTableRows(item: ItemDetails, lookup: Record<string, string>): DataTableRow[] {
  const rows: DataTableRow[] = [];
  const entityName = displayEntityName(item.name, item.id, item.item_type, lookup, item.path);

  if (item.owner) {
    rows.push({
      key: `owner:${item.owner.id}`,
      targetIds: { 3: item.owner.id },
      cells: ["Owner", entityName, "Parent", itemReferenceDisplayName(item.owner, lookup)],
    });
  }

  for (const reference of item.contained_elements) {
    rows.push({
      key: `contained:${reference.id}`,
      targetIds: { 3: reference.id },
      cells: ["Owned Element", entityName, "Contains", itemReferenceDisplayName(reference, lookup)],
    });
  }

  for (const reference of item.type_references) {
    rows.push({
      key: `typed:${reference.id}`,
      targetIds: { 3: reference.id },
      cells: [humanizeFieldLabel(reference.relationship_type), entityName, "References", itemReferenceDisplayName(reference, lookup)],
    });
  }

  for (const reference of item.related_items) {
    rows.push({
      key: `related:${reference.relationship_type}:${reference.id}`,
      targetIds: { 3: reference.id },
      cells: [humanizeFieldLabel(reference.relationship_type), entityName, "Related", itemReferenceDisplayName(reference, lookup)],
    });
  }

  item.relationships.forEach((relationship, index) => {
    const targetName =
      typeof relationship.target_name === "string" && relationship.target_name
        ? relationship.target_name
        : typeof relationship.target === "string"
          ? humanReadableReference(relationship.target, lookup)
          : humanReadableValue(relationship.target ?? relationship, lookup);
    if (!hasMeaningfulValue(targetName)) {
      return;
    }
    rows.push({
      key: `relationship:${index}`,
      targetIds: typeof relationship.target === "string" ? { 3: relationship.target } : undefined,
      cells: [
        humanizeFieldLabel(String(relationship.type ?? `Relationship ${index + 1}`)),
        entityName,
        "Outgoing",
        String(targetName),
      ],
    });
  });

  const deduped = new Set<string>();
  return rows.filter((row) => {
    const key = row.cells.map((cell) => String(cell)).join("::");
    if (deduped.has(key)) {
      return false;
    }
    deduped.add(key);
    return true;
  });
}

function specificationSectionIntro(section: SpecificationSectionId, item: ItemDetails): string {
  const typeLabel = humanizeFieldLabel(item.item_type || item.raw_types[0] || "item");
  switch (section) {
    case "properties":
      return `Review the published ${typeLabel} properties. Switch between Standard, Expert, and All to surface more fields.`;
    case "documentation":
      return `Review documentation and comments published for the selected ${typeLabel}.`;
    case "navigation":
      return `Review navigation targets and hyperlinks published for the selected ${typeLabel}.`;
    case "usage-diagrams":
      return `Review published diagram usage references for the selected ${typeLabel}.`;
    case "usage-in":
      return `Review where the selected ${typeLabel} is used as a type, member, classifier, or referenced element.`;
    case "ports-interfaces":
      return `Review ports, interfaces, provided/required ends, and interface-related references for the selected ${typeLabel}.`;
    case "element-properties":
      return `Review property and member features for the selected ${typeLabel}.`;
    case "attributes":
      return `Review attributes owned by or published on the selected ${typeLabel}.`;
    case "ports":
      return `Review ports owned by or published on the selected ${typeLabel}.`;
    case "operations":
      return `Review operations owned by or published on the selected ${typeLabel}.`;
    case "receptions":
      return `Review receptions owned by or published on the selected ${typeLabel}.`;
    case "behaviors":
      return `Review behaviors owned by or published on the selected ${typeLabel}.`;
    case "inner-elements":
      return `Review the contained elements published under the selected ${typeLabel}.`;
    case "relations":
      return `Review the relationships published for the selected ${typeLabel}.`;
    case "tags":
      return `Review published stereotypes, tags, and tagged values for the selected ${typeLabel}.`;
    case "constraints":
      return `Review constraints published for the selected ${typeLabel}.`;
    case "traceability":
      return `Review traceability references published for the selected ${typeLabel}.`;
    case "allocations":
      return `Review allocation references published for the selected ${typeLabel}.`;
    case "template-parameters":
      return `Review template parameters published for the selected ${typeLabel}.`;
    case "instances":
      return `Review instances and slots published for the selected ${typeLabel}.`;
    default:
      return "";
  }
}

function viewModeIncludes(viewMode: ItemDetailViewMode, target: "standard" | "expert" | "all"): boolean {
  if (viewMode === "all") {
    return true;
  }
  if (viewMode === "expert") {
    return target === "standard" || target === "expert";
  }
  return target === "standard";
}

function specificationWindowRows(
  item: ItemDetails,
  lookup: Record<string, string>,
  viewMode: ItemDetailViewMode,
): InspectorRow[] {
  const sourcePayload = item.source_payload ?? {};
  const attributes = payloadAttributes(item);
  const metadata = item.metadata ?? {};
  const references = payloadReferences(item);
  const nativeIndex = payloadNativeMetamodelEntryIndex(item);
  const rows: InspectorRow[] = [];
  const valueFromNative = (...keys: string[]): unknown => {
    for (const key of keys) {
      const value = nativeEntryValue(nativeIndex.get(normalizedFieldKey(key)));
      if (hasMeaningfulValue(value)) {
        return value;
      }
    }
    return undefined;
  };
  const valueFromReferences = (...keys: string[]): unknown => {
    for (const key of keys) {
      const value = references[key];
      if (hasMeaningfulValue(value)) {
        return value;
      }
      const normalized = normalizedFieldKey(key);
      for (const [referenceKey, referenceValue] of Object.entries(references)) {
        if (normalizedFieldKey(referenceKey) === normalized && hasMeaningfulValue(referenceValue)) {
          return referenceValue;
        }
      }
    }
    return undefined;
  };
  const firstMeaningful = (...values: unknown[]): unknown => values.find((value) => hasMeaningfulValue(value));
  const shouldShowEmptyCameoRows = viewMode === "all";
  const pushRow = (key: string, label: string, value: unknown, options?: { showWhenEmpty?: boolean }) => {
    const meaningful = hasMeaningfulValue(value);
    if (!meaningful && !options?.showWhenEmpty) {
      return;
    }
    rows.push({
      key,
      label,
      value: meaningful ? humanReadableValue(value, lookup) : label === "Is Encapsulated" ? "<undefined>" : "",
      rawValue: meaningful ? value : undefined,
    });
  };

  if (isPackageLikeItemType(item.item_type)) {
    pushRow("cameo.package.name", "Name", firstMeaningful(valueFromNative("name", "Name"), sourcePayload.human_name, item.name), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.qualified-name", "Qualified Name", firstMeaningful(valueFromNative("qualifiedName", "Qualified Name"), sourcePayload.qualified_name), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owner", "Owner", firstMeaningful(valueFromNative("owner", "Owner"), item.owner), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.applied-stereotype", "Applied Stereotype", firstMeaningful(valueFromNative("appliedStereotype", "Applied Stereotype"), item.stereotypes), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.visibility", "Visibility", firstMeaningful(valueFromNative("visibility", "Visibility"), "public"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.active-hyperlink", "Active Hyperlink", valueFromNative("activeHyperlink", "active hyperlink"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.name-expression", "Name Expression", valueFromNative("nameExpression", "name expression"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.client-dependency", "Client Dependency", valueFromNative("clientDependency", "client dependency"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.supplier-dependency", "Supplier Dependency", valueFromNative("supplierDependency", "supplier dependency"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.template-parameter", "Template Parameter", valueFromNative("templateParameter", "template parameter"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.tagged-value", "Tagged Value", valueFromNative("taggedValue", "tagged value"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owned-comment", "Owned Comment", valueFromNative("ownedComment", "owned comment"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owned-element", "Owned Element", valueFromNative("ownedElement", "owned element"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.namespace", "Namespace", valueFromNative("namespace", "Namespace"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owned-template-signature", "Owned Template Signature", valueFromNative("ownedTemplateSignature", "owned template signature"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.template-binding", "Template Binding", valueFromNative("templateBinding", "template binding"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owned-diagram", "Owned Diagram", valueFromNative("ownedDiagram", "owned diagram"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.imported-member", "Imported Member", valueFromNative("importedMember", "imported member"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.member", "Member", valueFromNative("member", "Member"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owned-member", "Owned Member", valueFromNative("ownedMember", "owned member"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owned-rule", "Owned Rule", valueFromNative("ownedRule", "owned rule"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.package-import", "Package Import", valueFromNative("packageImport", "package import"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.element-import", "Element Import", valueFromNative("elementImport", "element import"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owning-package", "Owning Package", firstMeaningful(valueFromNative("owningPackage", "owning package"), valueFromReferences("owningPackage")), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.nesting-package", "Nesting Package", valueFromNative("nestingPackage", "nesting package"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.nested-package", "Nested Package", valueFromNative("nestedPackage", "nested package"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owned-type", "Owned Type", valueFromNative("ownedType", "owned type"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.package-merge", "Package Merge", valueFromNative("packageMerge", "package merge"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.applied-profile", "Applied Profile", valueFromNative("appliedProfile", "applied profile"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.image", "Image", valueFromNative("image", "Image"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.uri", "URI", valueFromNative("URI", "uri"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.to-do", "To Do", valueFromNative("toDo", "to do", "todo"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.element-id", "Element ID", firstMeaningful(valueFromNative("ID", "elementId", "Element ID"), sourcePayload.local_id, item.id), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owned-stereotype", "Owned Stereotype", valueFromNative("ownedStereotype", "owned stereotype"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.owning-template-parameter", "Owning Template Parameter", valueFromNative("owningTemplateParameter", "owning template parameter"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.packaged-element", "Packaged Element", firstMeaningful(valueFromNative("packagedElement", "packaged element"), valueFromReferences("packagedElement")), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.profile-application", "Profile Application", valueFromNative("profileApplication", "profile application"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.all-realizing-elements", "All Realizing Elements", valueFromNative("allRealizingElements", "all realizing elements"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.all-specifying-elements", "All Specifying Elements", valueFromNative("allSpecifyingElements", "all specifying elements"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.realizing-element", "Realizing Element", valueFromNative("realizingElement", "realizing element"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.specifying-element", "Specifying Element", valueFromNative("specifyingElement", "specifying element"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.allocated-from", "Allocated From", firstMeaningful(valueFromReferences("allocatedFrom"), valueFromNative("allocatedFrom", "allocated from")), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.allocated-to", "Allocated To", firstMeaningful(valueFromReferences("allocatedTo"), valueFromNative("allocatedTo", "allocated to")), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.author", "Author", valueFromNative("author", "Author"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.documentation", "Documentation", firstMeaningful(valueFromNative("documentation", "Documentation"), sourcePayload.documentation), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.package.mounted-package", "Mounted Package", valueFromNative("mountedPackage", "mounted package"), { showWhenEmpty: shouldShowEmptyCameoRows });

    return cameoOrderedInspectorRows(dedupeInspectorRowsByLabel(dedupeInspectorRows(rows)), item.item_type);
  } else {
    pushRow("cameo.name", "Name", firstMeaningful(valueFromNative("name", "Name"), sourcePayload.human_name, item.name), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.used-as-type", "Used As Type", firstMeaningful(valueFromReferences("_typedElementOfType", "typedElementOfType"), valueFromNative("typedElement", "type")), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.sync-element", "Sync Element", valueFromNative("syncElement", "sync element"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.general", "General", valueFromNative("general", "General"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.element-id", "Element ID", firstMeaningful(valueFromNative("ID", "elementId", "Element ID"), item.id), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.specific-classifier", "Specific Classifier", valueFromNative("specificClassifier", "specific classifier"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.verifies", "Verifies", firstMeaningful(valueFromReferences("verify", "verifies"), valueFromNative("verifies", "verify")), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.participates-interaction", "Participates In Interaction", valueFromNative("participatesInInteraction", "participates in interaction"), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.allocated-to", "Allocated To", firstMeaningful(valueFromReferences("allocatedTo"), valueFromNative("allocatedTo", "allocated to")), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.specifying-component", "Specifying Component", valueFromNative("specifyingComponent", "specifying component"), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.all-specifying-elements", "All Specifying Elements", valueFromNative("allSpecifyingElements", "all specifying elements"), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.realizing-element", "Realizing Element", valueFromNative("realizingElement", "realizing element"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.refines", "Refines", firstMeaningful(valueFromReferences("refine", "refines"), valueFromNative("refines", "refine")), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.participates-activity", "Participates In Activity", valueFromNative("participatesInActivity", "participates in activity"), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.traced-from", "Traced From", firstMeaningful(valueFromReferences("tracedFrom", "trace"), valueFromNative("tracedFrom", "traced from")), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.all-realizing-elements", "All Realizing Elements", valueFromNative("allRealizingElements", "all realizing elements"), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.allocated-from", "Allocated From", firstMeaningful(valueFromReferences("allocatedFrom"), valueFromNative("allocatedFrom", "allocated from")), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.specifying-use-case", "Specifying Use Case", valueFromNative("specifyingUseCase", "specifying use case"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.all-specific-classifiers", "All Specific Classifiers", valueFromNative("allSpecificClassifiers", "all specific classifiers"), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.owner", "Owner", firstMeaningful(valueFromNative("owner", "Owner"), item.owner), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.qualified-name", "Qualified Name", firstMeaningful(valueFromNative("qualifiedName", "Qualified Name"), sourcePayload.qualified_name), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.is-encapsulated", "Is Encapsulated", valueFromNative("isEncapsulated", "is encapsulated"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.realizing-component", "Realizing Component", valueFromNative("realizingComponent", "realizing component"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.satisfies", "Satisfies", firstMeaningful(valueFromReferences("satisfy", "satisfies"), valueFromNative("satisfies", "satisfy")), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.specifying-element", "Specifying Element", valueFromNative("specifyingElement", "specifying element"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.all-general-classifiers", "All General Classifiers", firstMeaningful(valueFromNative("allGeneralClassifiers", "all general classifiers"), valueFromNative("general", "superClass")), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.applied-stereotype", "Applied Stereotype", firstMeaningful(valueFromNative("appliedStereotype", "Applied Stereotype"), item.stereotypes), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.is-active", "Is Active", valueFromNative("isActive", "is active"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.is-abstract", "Is Abstract", valueFromNative("isAbstract", "is abstract"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.use-case", "Use Case", valueFromNative("useCase", "use case"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.template-parameter", "Template Parameter", valueFromNative("templateParameter", "template parameter"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.owned-comment", "Owned Comment", valueFromNative("ownedComment", "owned comment"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.owned-element", "Owned Element", valueFromNative("ownedElement", "owned element"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.super-class", "Super Class", valueFromNative("superClass", "super class"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.tagged-value", "Tagged Value", valueFromNative("taggedValue", "tagged value"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.owning-package", "Owning Package", firstMeaningful(valueFromNative("owningPackage", "owning package"), valueFromReferences("owningPackage")), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.name-expression", "Name Expression", valueFromNative("nameExpression", "name expression"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.namespace", "Namespace", valueFromNative("namespace", "Namespace"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.owned-template-signature", "Owned Template Signature", valueFromNative("ownedTemplateSignature", "owned template signature"), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.template-binding", "Template Binding", valueFromNative("templateBinding", "template binding"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.client-dependency", "Client Dependency", valueFromNative("clientDependency", "client dependency"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.supplier-dependency", "Supplier Dependency", valueFromNative("supplierDependency", "supplier dependency"), {
      showWhenEmpty: shouldShowEmptyCameoRows,
    });
    pushRow("cameo.owned-connector", "Owned Connector", valueFromNative("ownedConnector", "owned connector"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.role", "Role", valueFromNative("role", "Role"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.part", "Part", valueFromNative("part", "Part"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.owned-attribute", "Owned Attribute", valueFromNative("ownedAttribute", "owned attribute"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.owned-diagram", "Owned Diagram", valueFromNative("ownedDiagram", "owned diagram"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.imported-member", "Imported Member", valueFromNative("importedMember", "imported member"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.member", "Member", valueFromNative("member", "Member"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.owned-member", "Owned Member", valueFromNative("ownedMember", "owned member"), { showWhenEmpty: shouldShowEmptyCameoRows });
    pushRow("cameo.owned-rule", "Owned Rule", valueFromNative("ownedRule", "owned rule"), { showWhenEmpty: shouldShowEmptyCameoRows });
  }

  rows.push(
    ...collectHintRows(item, lookup, PROPERTY_FIELD_HINTS, {
      includeSourcePayload: true,
      includeAttributes: true,
      includeReferences: false,
      includeMetadata: false,
      inlineOnly: true,
    }),
    ...collectHintRows(item, lookup, SPECIFICATION_FIELD_HINTS, {
      includeSourcePayload: true,
      includeAttributes: true,
      includeReferences: false,
      includeMetadata: false,
      inlineOnly: true,
    }),
  );

  if (viewModeIncludes(viewMode, "expert")) {
    rows.push(
      ...mapInlineInspectorRows(
        {
          model_id: sourcePayload.model_id,
          local_id: sourcePayload.local_id,
          owner_id: sourcePayload.owner_id,
          raw_types: item.raw_types.slice(0, 3),
        },
        lookup,
      ),
      ...mapInlineInspectorRows(metadata, lookup),
      ...collectHintRows(item, lookup, [...PROPERTY_FIELD_HINTS, ...SPECIFICATION_FIELD_HINTS, ...CONSTRAINT_FIELD_HINTS], {
        includeSourcePayload: false,
        includeAttributes: true,
        includeReferences: true,
        inlineOnly: true,
      }),
    );
  }

  if (viewMode === "all") {
    for (const [key, value] of payloadExtraSections(item)) {
      const label = humanizeFieldLabel(key);
      if (rows.some((row) => normalizedFieldKey(row.label) === normalizedFieldKey(label))) {
        continue;
      }
      rows.push({
        key: `extra.${key}`,
        label,
        value: humanReadableValue(value, lookup),
      });
    }
  }

  const nativeRows = payloadNativeMetamodelEntries(item)
    .filter((entry) => {
      const value = hasMeaningfulValue(entry.value) ? entry.value : entry.defaultValue;
      if (viewMode === "standard") {
        return entry.set === true && hasMeaningfulValue(entry.value);
      }
      if (viewMode === "expert") {
        return hasMeaningfulValue(value) || entry.set === true || entry.derived === true;
      }
      return true;
    })
    .map((entry, index) => ({
      key: `native.metamodel.${String(entry.id ?? index)}`,
      label: String(entry.name ?? entry.id ?? `Property ${index + 1}`),
      value: nativeEntryDisplayValue(entry, lookup) || "",
    }))
    .filter((row) => hasMeaningfulValue(row.value));
  const representedLabels = new Set(rows.map((row) => normalizedFieldKey(row.label)));
  representedLabels.add("id");
  representedLabels.add("elementid");
  rows.push(...nativeRows.filter((row) => !representedLabels.has(normalizedFieldKey(row.label))));

  return cameoOrderedInspectorRows(dedupeInspectorRowsByLabel(dedupeInspectorRows(rows)), item.item_type);
}

function defaultParameterValue(parameter: SwaggerParameterSpec): string {
  if (parameter.default === null || parameter.default === undefined) {
    return "";
  }
  return String(parameter.default);
}

function coerceParameterValue(parameter: SwaggerParameterSpec, value: string): unknown {
  if (value === "") {
    return "";
  }
  if (parameter.schema_type === "boolean") {
    return value === "true";
  }
  if (parameter.schema_type === "integer") {
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? value : parsed;
  }
  if (parameter.schema_type === "number") {
    const parsed = Number.parseFloat(value);
    return Number.isNaN(parsed) ? value : parsed;
  }
  if (parameter.schema_type === "array") {
    return value
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return value;
}

function collectParameterValues(parameters: SwaggerParameterSpec[], values: Record<string, string>) {
  return parameters.reduce<Record<string, unknown>>((collected, parameter) => {
    const value = values[parameter.name] ?? "";
    if (value !== "") {
      collected[parameter.name] = coerceParameterValue(parameter, value);
    } else if (parameter.location === "path" && parameter.required) {
      collected[parameter.name] = "";
    }
    return collected;
  }, {});
}

function requestBodyTemplate(operation: SwaggerOperationSpec | null, manifest: SwaggerContractManifest | null): string {
  if (!operation?.request_body) {
    return "";
  }
  const contentType = operation.request_body.content_types[0] ?? "";
  if (contentType === "text/plain") {
    return "";
  }
  const schemaName = Object.values(operation.request_body.schema_refs).find(Boolean);
  if (!schemaName || !manifest) {
    return "{}";
  }
  const schema = manifest.schemas.find((candidate) => candidate.name === schemaName);
  if (!schema || !schema.properties.length) {
    return "{}";
  }
  const sample = schema.properties.reduce<Record<string, unknown>>((collected, property) => {
    if (!property.required && schema.required.length) {
      return collected;
    }
    if (property.schema_type === "boolean") {
      collected[property.name] = false;
    } else if (property.schema_type === "integer" || property.schema_type === "number") {
      collected[property.name] = 0;
    } else if (property.schema_type === "array") {
      collected[property.name] = [];
    } else if (property.schema_type === "object") {
      collected[property.name] = {};
    } else {
      collected[property.name] = "";
    }
    return collected;
  }, {});
  return JSON.stringify(sample, null, 2);
}

function responseContent(response: SwaggerExecuteResponse): string {
  if (response.body !== null && response.body !== undefined) {
    return JSON.stringify(response.body, null, 2);
  }
  if (response.text) {
    return response.text;
  }
  if (response.body_base64) {
    return `Binary response: ${response.size_bytes} bytes, ${response.content_type || "unknown content type"}.`;
  }
  return "No response body.";
}

function downloadSwaggerResponse(response: SwaggerExecuteResponse) {
  if (!response.body_base64) {
    return;
  }
  const binary = atob(response.body_base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const blob = new Blob([bytes], { type: response.content_type || "application/octet-stream" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = response.filename ?? "twc-response.bin";
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export default function WorkspacePage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchParamsKey = searchParams.toString();
  const pendingSearchSyncRef = useRef<string | null>(null);
  const applyingSearchParamsRef = useRef(false);
  const queryClient = useQueryClient();
  const { session, refreshSession, setSessionSnapshot } = useSession();
  const defaultPreferences: SessionPreferences = {
    theme_mode: "system",
    font_scale: 1,
    request_timeout_seconds: 30,
    live_log_poll_interval_ms: 2500,
    presentation_font_scale: 1.2,
    compact_ui: true,
    show_hidden_packages_in_tree: false,
    show_auxiliary_resources_in_tree: false,
    show_applied_stereotypes_in_tree: false,
    show_full_types_in_tree: true,
    item_detail_view_mode: "standard",
  };
  const currentPreferences: SessionPreferences = {
    ...defaultPreferences,
    ...(session?.preferences ?? {}),
  };
  const csrfToken = session?.csrf_token ?? "";
  const capabilities = session?.capabilities?.capabilities ?? {};
  const canEdit = capabilities.edit?.state === "ready";
  const isTwcAuthenticated = session?.user?.auth_source === "twc";
  const hasVerifiedTwcPermissionConnection = Boolean(
    isTwcAuthenticated && capabilities.user_access?.state === "ready" && !session?.permission_snapshot_warning,
  );
  const isAdmin = Boolean(session?.can_manage_server_presets);
  const canManageGroups = isAdmin || Boolean(session?.can_manage_groups);
  const canOpenSettings = Boolean(session?.user?.preferred_username);
  const compactUi = currentPreferences.compact_ui ?? true;
  const [itemDetailViewMode, setItemDetailViewMode] = useState<ItemDetailViewMode>(() =>
    parseItemDetailViewMode(currentPreferences.item_detail_view_mode),
  );
  const cacheTimeMs = 1000 * 60 * 60 * 12;
  const sessionCacheKey = [session?.user?.preferred_username ?? "anonymous", session?.server?.id ?? "no-server"];
  const layoutStoragePrefix = `twc-workbench-layout:${sessionCacheKey.join(":")}`;
  const navPaneStorageKey = `${layoutStoragePrefix}:nav-pane-width`;
  const modelContainmentPaneStorageKey = `${layoutStoragePrefix}:model-containment-pane-width`;

  const toggleNewCacheApiKeyScope = (scope: CacheApiKeyScope, checked: boolean) => {
    setNewCacheApiKeyScopes((current) => {
      if (checked) {
        return current.includes(scope) ? current : [...current, scope];
      }
      return current.filter((value) => value !== scope);
    });
  };

  const [tab, setTab] = useState<WorkspaceTab>(() => parseWorkspaceTab(searchParams.get("tab")));
  const [settingsSubtab, setSettingsSubtab] = useState<SettingsSubtab>("users");
  const [workbenchUserSearch, setWorkbenchUserSearch] = useState("");
  const [twcGroupSearch, setTwcGroupSearch] = useState("");
  const settingsTabActive = tab === "settings";
  const [preferencesDraft, setPreferencesDraft] = useState<SessionPreferences>(currentPreferences);
  const [selectedProjectId, setSelectedProjectId] = useState(() => searchParams.get("project") ?? "");
  const [selectedBranchId, setSelectedBranchId] = useState(() => searchParams.get("branch") ?? "");
  const [treeFilter, setTreeFilter] = useState("");
  const [selectedItemId, setSelectedItemId] = useState(() => searchParams.get("item") ?? "");
  const [selectedSpecificationSection, setSelectedSpecificationSection] = useState<SpecificationSectionId>("properties");
  const [treeNodes, setTreeNodes] = useState<TreeNode[]>([]);
  const [loadingTreeNodeIds, setLoadingTreeNodeIds] = useState<string[]>([]);
  const [expandedTreeNodeIds, setExpandedTreeNodeIds] = useState<string[]>([]);
  const [expandedInnerElementNodeIds, setExpandedInnerElementNodeIds] = useState<string[]>([]);
  const [navPaneWidth, setNavPaneWidth] = useState(() => readStoredNumber(navPaneStorageKey, 280, 240, 420));
  const [modelContainmentPaneWidth, setModelContainmentPaneWidth] = useState(() =>
    readStoredNumber(modelContainmentPaneStorageKey, 320, 260, 460),
  );
  const [workspaceMenuGroup, setWorkspaceMenuGroup] = useState<WorkspaceMenuGroup | null>(null);
  const [workspaceMenuAnchorEl, setWorkspaceMenuAnchorEl] = useState<HTMLElement | null>(null);
  const [userMenuAnchorEl, setUserMenuAnchorEl] = useState<HTMLElement | null>(null);
  const [itemDraft, setItemDraft] = useState<ItemDetails | null>(null);
  const [compareLeft, setCompareLeft] = useState("");
  const [compareRight, setCompareRight] = useState("");
  const [compareLeftDisplay, setCompareLeftDisplay] = useState("");
  const [compareRightDisplay, setCompareRightDisplay] = useState("");
  const [compareMode, setCompareMode] = useState<CompareMode>("branch");
  const [compareLeftProjectId, setCompareLeftProjectId] = useState(() => searchParams.get("project") ?? "");
  const [compareLeftBranchId, setCompareLeftBranchId] = useState(() => searchParams.get("branch") ?? "");
  const [compareRightProjectId, setCompareRightProjectId] = useState(() => searchParams.get("project") ?? "");
  const [compareRightBranchId, setCompareRightBranchId] = useState(() => searchParams.get("branch") ?? "");
  const [selectedApiTag, setSelectedApiTag] = useState("");
  const [selectedOperationKey, setSelectedOperationKey] = useState("");
  const [apiSearch, setApiSearch] = useState("");
  const [elementSearchMode, setElementSearchMode] = useState<ElementSearchMode>(() => parseElementSearchMode(searchParams.get("searchMode")));
  const [elementSearchQuery, setElementSearchQuery] = useState(() => searchParams.get("searchQuery") ?? "");
  const [elementSearchStereotype, setElementSearchStereotype] = useState(() => searchParams.get("searchStereotype") ?? "");
  const [elementSearchItemType, setElementSearchItemType] = useState(() => searchParams.get("searchItemType") ?? "");
  const [elementSearchResponse, setElementSearchResponse] = useState<CacheElementSearchResponse | StereotypeElementSearchResponse | null>(null);
  const [elementSearchSummary, setElementSearchSummary] = useState("");
  const [apiPathParams, setApiPathParams] = useState<Record<string, string>>({});
  const [apiQueryParams, setApiQueryParams] = useState<Record<string, string>>({});
  const [apiBodyText, setApiBodyText] = useState("");
  const [apiContentType, setApiContentType] = useState("");
  const [apiUploadFile, setApiUploadFile] = useState<File | null>(null);
  const [manualCacheIngestToken, setManualCacheIngestToken] = useState("");
  const [revealedCacheIngestToken, setRevealedCacheIngestToken] = useState("");
  const [newCacheApiKeyLabel, setNewCacheApiKeyLabel] = useState("");
  const [revealedCacheApiKey, setRevealedCacheApiKey] = useState("");
  const [newCacheApiKeyScopes, setNewCacheApiKeyScopes] = useState<CacheApiKeyScope[]>(["read"]);
  const [authSettingsDraft, setAuthSettingsDraft] = useState<WorkbenchAuthSettings>({
    user_management_mode: "local",
    local_users_enabled: true,
    twc_redirect_enabled: false,
    twc_token_enabled: false,
  });
  const [newWorkbenchUser, setNewWorkbenchUser] = useState<WorkbenchUserCreateRequest>({
    username: "",
    password: "",
    role: "user",
    enabled: true,
    display_name: "",
  });
  const [workbenchPasswordResets, setWorkbenchPasswordResets] = useState<Record<string, string>>({});
  const [newWorkbenchGroup, setNewWorkbenchGroup] = useState<WorkbenchGroupCreateRequest>({
    name: "",
    description: "",
    users: [],
    enabled: true,
  });
  const [workbenchGroupUserDrafts, setWorkbenchGroupUserDrafts] = useState<Record<string, string>>({});
  const [workbenchAccessAssignment, setWorkbenchAccessAssignment] = useState<WorkbenchProjectAccessAssignmentRequest>({
    principal_type: "user",
    principal_name: "",
    project_id: "",
    branch_id: null,
    accessible: true,
    editable: false,
    admin_access: false,
  });
  const [debugProjectId, setDebugProjectId] = useState("");
  const [debugBranchId, setDebugBranchId] = useState("trunk");
  const [debugDumpDigest, setDebugDumpDigest] = useState<Record<string, unknown> | null>(null);
  const [newServerPreset, setNewServerPreset] = useState<ServerProfileInput>(createServerProfileDraft());
  const [serverPresetDrafts, setServerPresetDrafts] = useState<Record<string, ServerProfileInput>>({});
  const [agentBaseUrlDraft, setAgentBaseUrlDraft] = useState("");
  const [agentApiKeyDraft, setAgentApiKeyDraft] = useState("");
  const [agentSelectedModelId, setAgentSelectedModelId] = useState("");
  const [agentSelectedModelName, setAgentSelectedModelName] = useState("");
  const [agentChatInput, setAgentChatInput] = useState("");
  const [agentMessages, setAgentMessages] = useState<WorkbenchAgentChatMessage[]>([]);
  const [agentKnowledgeSyncProgress, setAgentKnowledgeSyncProgress] = useState("");
  const treeContextKey = `${selectedProjectId || "no-project"}:${selectedBranchId || "no-branch"}`;
  const treeContextRef = useRef<string>(treeContextKey);
  const treeNodesRef = useRef<TreeNode[]>([]);
  const [agentSyncKnowledgeBeforeChat, setAgentSyncKnowledgeBeforeChat] = useState(true);
  const [notice, setNotice] = useState<{ severity: "success" | "info" | "warning" | "error"; message: string } | null>(null);
  const projectContextActive = tab === "projects" || tab === "models" || tab === "search" || tab === "diagram-viewer" || tab === "compare";
  const treeExpandedStorageKey = `${layoutStoragePrefix}:tree-expanded:${selectedProjectId || "no-project"}:${selectedBranchId || "no-branch"}`;
  const workspaceOuterPadding = compactUi ? { xs: 1.5, md: 2 } : { xs: 2, md: 3 };
  const panelPadding = compactUi ? 2 : 3;
  const sectionSpacing = compactUi ? 1.5 : 2;
  const viewportPanelMaxHeight = compactUi ? "calc(100vh - 250px)" : "calc(100vh - 220px)";
  const previewMaxHeight = compactUi ? 460 : 520;

  const projectsQuery = useQuery({
    queryKey: ["workspace-projects", ...sessionCacheKey],
    queryFn: () => api.getProjects(),
    enabled: !settingsTabActive || settingsSubtab === "users" || settingsSubtab === "groups" || settingsSubtab === "debug",
    staleTime: 10_000,
    gcTime: cacheTimeMs,
    refetchInterval: settingsTabActive ? false : 30_000,
    refetchOnWindowFocus: true,
  });

  const contractQuery = useQuery({
    queryKey: ["workspace-contract", ...sessionCacheKey],
    queryFn: api.getContractManifest,
    enabled: isAdmin,
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });

  const cacheIngestTokenQuery = useQuery({
    queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey],
    queryFn: api.getCacheIngestTokenStatus,
    enabled: isAdmin,
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const authManagementStatusQuery = useQuery({
    queryKey: ["auth-management-status", ...sessionCacheKey],
    queryFn: api.getAuthManagementStatus,
    enabled: isAdmin,
    staleTime: 10_000,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const workbenchUsersQuery = useQuery({
    queryKey: ["workbench-users", ...sessionCacheKey],
    queryFn: api.listWorkbenchUsers,
    enabled: canManageGroups,
    staleTime: 10_000,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const workbenchGroupsQuery = useQuery({
    queryKey: ["workbench-groups", ...sessionCacheKey],
    queryFn: api.listWorkbenchGroups,
    enabled: canManageGroups,
    staleTime: 10_000,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const managedServersQuery = useQuery({
    queryKey: ["managed-servers", ...sessionCacheKey],
    queryFn: api.listManagedServers,
    enabled: isAdmin,
    staleTime: 10_000,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const permissionInventoryStatusQuery = useQuery({
    queryKey: ["workspace-permission-inventory-status", ...sessionCacheKey],
    queryFn: api.getPermissionInventoryStatus,
    enabled: Boolean(session?.server?.id) && isAdmin,
    staleTime: 5_000,
    gcTime: cacheTimeMs,
    refetchInterval: (query) =>
      query.state.data?.state === "refreshing" ? 5_000 : 30_000,
    refetchOnWindowFocus: true,
  });
  const permissionInventoryDetailsQuery = useQuery({
    queryKey: ["workspace-permission-inventory-details", ...sessionCacheKey],
    queryFn: api.getPermissionInventoryDetails,
    enabled: Boolean(session?.server?.id) && isAdmin && tab === "settings" && settingsSubtab === "groups",
    staleTime: 30_000,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const branchTombstonesQuery = useQuery({
    queryKey: ["workspace-branch-tombstones", ...sessionCacheKey],
    queryFn: api.listBranchTombstones,
    enabled: Boolean(session?.server?.id) && isAdmin,
    staleTime: 30_000,
    gcTime: cacheTimeMs,
  });
  const projectTombstonesQuery = useQuery({
    queryKey: ["workspace-project-tombstones", ...sessionCacheKey],
    queryFn: api.listProjectTombstones,
    enabled: Boolean(session?.server?.id) && isAdmin,
    staleTime: 30_000,
    gcTime: cacheTimeMs,
  });

  useEffect(() => {
    if (authManagementStatusQuery.data?.settings) {
      setAuthSettingsDraft(authManagementStatusQuery.data.settings);
    }
  }, [authManagementStatusQuery.data?.settings]);

  useEffect(() => {
    setPreferencesDraft(currentPreferences);
  }, [currentPreferences]);

  useEffect(() => {
    if (!isAdmin && (tab === "api" || tab === "developer")) {
      setTab(canOpenSettings ? "settings" : "dashboard");
    }
    if (!isAdmin && settingsSubtab !== "users" && settingsSubtab !== "groups") {
      setSettingsSubtab("users");
    }
  }, [canOpenSettings, isAdmin, settingsSubtab, tab]);

  useEffect(() => {
    if (!managedServersQuery.data) {
      return;
    }
    setServerPresetDrafts((current) => {
      const next: Record<string, ServerProfileInput> = {};
      for (const server of managedServersQuery.data) {
        next[server.id] = current[server.id] ?? createServerProfileDraft({
          name: server.name,
          base_url: server.base_url,
          version: server.version,
          verify_tls: server.verify_tls,
          ca_bundle_path: server.ca_bundle_path,
          enabled: server.enabled,
          display_order: server.display_order,
          auth_discovery_url: server.auth_discovery_url,
          auth_authorize_url: server.auth_authorize_url,
          auth_token_url: server.auth_token_url,
          auth_login_path: server.auth_login_path,
          auth_login_port: server.auth_login_port,
          auth_token_path: server.auth_token_path,
          auth_client_id: server.auth_client_id,
          auth_client_secret: null,
          auth_scope: server.auth_scope ?? "openid",
          auth_return_url_parameter: server.auth_return_url_parameter ?? "redirect_uri",
          oslc_base_url: server.oslc_base_url,
          oslc_consumer_key: server.oslc_consumer_key,
          oslc_consumer_secret: null,
          oslc_callback_url: server.oslc_callback_url,
        });
      }
      return next;
    });
  }, [managedServersQuery.data]);
  const cacheApiKeysQuery = useQuery({
    queryKey: ["workspace-cache-api-keys", ...sessionCacheKey],
    queryFn: api.listCacheApiKeys,
    enabled: Boolean(session?.user?.preferred_username),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const workbenchAgentStatusQuery = useQuery({
    queryKey: ["workspace-agent", ...sessionCacheKey],
    queryFn: api.getWorkbenchAgentStatus,
    enabled: Boolean(session?.user?.preferred_username),
    staleTime: 1000 * 60,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const workbenchAgentStatus = workbenchAgentStatusQuery.data ?? null;
  const workbenchAgentModelsQuery = useQuery({
    queryKey: [
      "workspace-agent-models",
      ...sessionCacheKey,
      workbenchAgentStatus?.base_url ?? "",
      workbenchAgentStatus?.updated_at ?? "",
    ],
    queryFn: api.listWorkbenchAgentModels,
    enabled: (tab === "agent" || (tab === "settings" && settingsSubtab === "auth")) && Boolean(workbenchAgentStatus?.configured && workbenchAgentStatus?.has_api_key),
    staleTime: 1000 * 60 * 5,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const workbenchAgentModels = workbenchAgentModelsQuery.data ?? [];

  const projects = useMemo(
    () =>
      [...(projectsQuery.data ?? [])].sort((left, right) => {
        const nameComparison = compareDisplayValues(left.name || left.id, right.name || right.id);
        if (nameComparison !== 0) {
          return nameComparison;
        }
        return compareDisplayValues(left.id, right.id);
      }),
    [projectsQuery.data],
  );
  const selectedProject = useMemo(
    () => projects.find((project) => project.id === selectedProjectId) ?? null,
    [projects, selectedProjectId],
  );
  useEffect(() => {
    if (!projectsQuery.isSuccess || !selectedProjectId || selectedProject) {
      return;
    }
    setSelectedProjectId("");
    setSelectedBranchId("");
    setSelectedItemId("");
    setItemDraft(null);
    setNotice({ severity: "warning", message: "The selected project is no longer in your authoritative permission snapshot and was closed." });
  }, [projectsQuery.isSuccess, selectedProject, selectedProjectId]);
  const compareLeftProject = useMemo(
    () => projects.find((project) => project.id === compareLeftProjectId) ?? null,
    [compareLeftProjectId, projects],
  );
  const compareRightProject = useMemo(
    () => projects.find((project) => project.id === compareRightProjectId) ?? null,
    [compareRightProjectId, projects],
  );
  const compareLeftBranchesQuery = useQuery({
    queryKey: ["workspace-branches", ...sessionCacheKey, compareLeftProjectId, compareLeftProject?.workspace_id],
    queryFn: () => api.getProjectBranches(compareLeftProjectId, compareLeftProject?.workspace_id || undefined),
    enabled: tab === "compare" && Boolean(compareLeftProjectId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const compareRightBranchesQuery = useQuery({
    queryKey: ["workspace-branches", ...sessionCacheKey, compareRightProjectId, compareRightProject?.workspace_id],
    queryFn: () => api.getProjectBranches(compareRightProjectId, compareRightProject?.workspace_id || undefined),
    enabled: tab === "compare" && Boolean(compareRightProjectId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const compareLeftBranches = useMemo(
    () =>
      [...(compareLeftBranchesQuery.data ?? [])].sort((left, right) =>
        compareDisplayValues(left.name || left.id, right.name || right.id),
      ),
    [compareLeftBranchesQuery.data],
  );
  const compareRightBranches = useMemo(
    () =>
      [...(compareRightBranchesQuery.data ?? [])].sort((left, right) =>
        compareDisplayValues(left.name || left.id, right.name || right.id),
      ),
    [compareRightBranchesQuery.data],
  );
  const branchesQuery = useQuery({
    queryKey: ["workspace-branches", ...sessionCacheKey, selectedProjectId, selectedProject?.workspace_id],
    queryFn: () => api.getProjectBranches(selectedProjectId, selectedProject?.workspace_id || undefined),
    enabled: Boolean(selectedProjectId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const selectedProjectBranches = useMemo(
    () =>
      [...(branchesQuery.data ?? [])].sort((left, right) => {
        const nameComparison = compareDisplayValues(left.name || left.id, right.name || right.id);
        if (nameComparison !== 0) {
          return nameComparison;
        }
        return compareDisplayValues(left.id, right.id);
      }),
    [branchesQuery.data],
  );
  const debugProject = useMemo(
    () => projects.find((project) => project.id === debugProjectId) ?? null,
    [debugProjectId, projects],
  );
  const debugBranchesQuery = useQuery({
    queryKey: ["workspace-branches", ...sessionCacheKey, debugProjectId, debugProject?.workspace_id, "settings-debug"],
    queryFn: () => api.getProjectBranches(debugProjectId, debugProject?.workspace_id || undefined),
    enabled: isAdmin && tab === "settings" && settingsSubtab === "debug" && Boolean(debugProjectId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const debugBranches = useMemo(
    () =>
      [...(debugBranchesQuery.data ?? [])].sort((left, right) => {
        const nameComparison = compareDisplayValues(left.name || left.id, right.name || right.id);
        if (nameComparison !== 0) {
          return nameComparison;
        }
        return compareDisplayValues(left.id, right.id);
      }),
    [debugBranchesQuery.data],
  );

  useEffect(() => {
    if (!compareLeftProjectId && selectedProjectId) {
      setCompareLeftProjectId(selectedProjectId);
    }
    if (!compareRightProjectId && selectedProjectId) {
      setCompareRightProjectId(selectedProjectId);
    }
  }, [compareLeftProjectId, compareRightProjectId, selectedProjectId]);

  useEffect(() => {
    if (debugProjectId || !projects.length) {
      return;
    }
    setDebugProjectId(selectedProjectId || projects[0].id);
  }, [debugProjectId, projects, selectedProjectId]);

  useEffect(() => {
    if (!debugProjectId || debugBranchesQuery.isLoading) {
      return;
    }
    if (!debugBranches.length) {
      setDebugBranchId("trunk");
      return;
    }
    const trunkBranch = debugBranches.find((branch) => normalizeLookupKey(branch.id) === "trunk" || normalizeLookupKey(branch.name) === "trunk");
    const preferredBranchId = trunkBranch?.id ?? debugBranches[0].id;
    if (!debugBranches.some((branch) => branch.id === debugBranchId)) {
      setDebugBranchId(preferredBranchId);
    }
  }, [debugBranches, debugBranchesQuery.isLoading, debugBranchId, debugProjectId]);

  useEffect(() => {
    if (!compareLeftProjectId || compareLeftBranchesQuery.isLoading) {
      return;
    }
    if (!compareLeftBranches.some((branch) => branch.id === compareLeftBranchId)) {
      setCompareLeftBranchId(compareLeftBranches[0]?.id ?? "");
    }
  }, [compareLeftBranchId, compareLeftBranches, compareLeftBranchesQuery.isLoading, compareLeftProjectId]);

  useEffect(() => {
    if (!compareRightProjectId || compareRightBranchesQuery.isLoading) {
      return;
    }
    if (!compareRightBranches.some((branch) => branch.id === compareRightBranchId)) {
      setCompareRightBranchId(compareRightBranches[0]?.id ?? "");
    }
  }, [compareRightBranchId, compareRightBranches, compareRightBranchesQuery.isLoading, compareRightProjectId]);

  useEffect(() => {
    if (!selectedProjectId) {
      setSelectedBranchId("");
      return;
    }
    if (branchesQuery.isLoading) {
      return;
    }
    if (!selectedProjectBranches.length) {
      return;
    }
    if (!selectedProjectBranches.some((branch) => branch.id === selectedBranchId)) {
      setSelectedBranchId(selectedProjectBranches[0].id);
    }
  }, [branchesQuery.isLoading, selectedBranchId, selectedProjectBranches, selectedProjectId]);

  useEffect(() => {
    setSelectedItemId("");
    setItemDraft(null);
  }, [selectedBranchId]);

  useEffect(() => {
    setAgentMessages([]);
  }, [selectedProjectId, selectedBranchId]);

  useEffect(() => {
    setExpandedTreeNodeIds(readStoredStringArray(treeExpandedStorageKey));
  }, [treeExpandedStorageKey]);

  useEffect(() => {
    setNavPaneWidth(readStoredNumber(navPaneStorageKey, 280, 240, 420));
  }, [navPaneStorageKey]);

  useEffect(() => {
    setModelContainmentPaneWidth(readStoredNumber(modelContainmentPaneStorageKey, 320, 260, 460));
  }, [modelContainmentPaneStorageKey]);

  useEffect(() => {
    const clampPaneWidths = () => {
      const viewportWidth = window.innerWidth;
      setNavPaneWidth((current) => clampNumber(current, 240, paneMaxWidthForViewport(viewportWidth, 0.28, 240, 420)));
      setModelContainmentPaneWidth((current) => clampNumber(current, 260, paneMaxWidthForViewport(viewportWidth, 0.34, 260, 460)));
    };
    clampPaneWidths();
    window.addEventListener("resize", clampPaneWidths);
    return () => window.removeEventListener("resize", clampPaneWidths);
  }, []);

  useEffect(() => {
    persistStoredValue(navPaneStorageKey, navPaneWidth);
  }, [navPaneStorageKey, navPaneWidth]);

  useEffect(() => {
    persistStoredValue(modelContainmentPaneStorageKey, modelContainmentPaneWidth);
  }, [modelContainmentPaneStorageKey, modelContainmentPaneWidth]);

  useEffect(() => {
    persistStoredValue(treeExpandedStorageKey, expandedTreeNodeIds);
  }, [expandedTreeNodeIds, treeExpandedStorageKey]);

  useEffect(() => {
    const currentSearch = searchParamsKey;
    if (pendingSearchSyncRef.current !== null && pendingSearchSyncRef.current === currentSearch) {
      pendingSearchSyncRef.current = null;
      return;
    }
    const urlParams = new URLSearchParams(currentSearch);
    applyingSearchParamsRef.current = true;
    setTab(parseWorkspaceTab(urlParams.get("tab")));
    setSelectedProjectId(urlParams.get("project") ?? "");
    setSelectedBranchId(urlParams.get("branch") ?? "");
    setSelectedItemId(urlParams.get("item") ?? "");
    setElementSearchMode(parseElementSearchMode(urlParams.get("searchMode")));
    setElementSearchQuery(urlParams.get("searchQuery") ?? "");
    setElementSearchStereotype(urlParams.get("searchStereotype") ?? "");
    setElementSearchItemType(urlParams.get("searchItemType") ?? "");
  }, [searchParamsKey]);

  useEffect(() => {
    if (applyingSearchParamsRef.current) {
      applyingSearchParamsRef.current = false;
      return;
    }
    const nextParams = new URLSearchParams(searchParamsKey);
    const nextTab = parseWorkspaceTab(tab);
    if (nextTab === "dashboard") {
      nextParams.delete("tab");
    } else {
      nextParams.set("tab", nextTab);
    }
    if (selectedProjectId) {
      nextParams.set("project", selectedProjectId);
    } else {
      nextParams.delete("project");
    }
    if (selectedBranchId) {
      nextParams.set("branch", selectedBranchId);
    } else {
      nextParams.delete("branch");
    }
    if (selectedItemId) {
      nextParams.set("item", selectedItemId);
    } else {
      nextParams.delete("item");
    }
    if (elementSearchMode !== "query") {
      nextParams.set("searchMode", elementSearchMode);
    } else {
      nextParams.delete("searchMode");
    }
    if (elementSearchQuery.trim()) {
      nextParams.set("searchQuery", elementSearchQuery.trim());
    } else {
      nextParams.delete("searchQuery");
    }
    if (elementSearchStereotype.trim()) {
      nextParams.set("searchStereotype", elementSearchStereotype.trim());
    } else {
      nextParams.delete("searchStereotype");
    }
    if (elementSearchItemType.trim()) {
      nextParams.set("searchItemType", elementSearchItemType.trim());
    } else {
      nextParams.delete("searchItemType");
    }
    const current = searchParamsKey;
    const next = nextParams.toString();
    if (current !== next) {
      pendingSearchSyncRef.current = next;
      setSearchParams(nextParams, { replace: true });
    }
  }, [elementSearchItemType, elementSearchMode, elementSearchQuery, elementSearchStereotype, searchParamsKey, selectedBranchId, selectedItemId, selectedProjectId, setSearchParams, tab]);

  const treeQuery = useQuery({
    queryKey: ["workspace-tree", ...sessionCacheKey, selectedProjectId, selectedBranchId],
    queryFn: () => api.getTree(selectedProjectId || undefined, selectedBranchId || undefined, selectedProject?.workspace_id || undefined, false, 0),
    enabled:
      projectContextActive &&
      Boolean(selectedProjectId) &&
      !branchesQuery.isLoading &&
      (!selectedProjectBranches.length || Boolean(selectedBranchId)),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchInterval: projectContextActive ? 10_000 : false,
    refetchOnWindowFocus: true,
  });
  const baseTreeNodes = treeQuery.data ?? [];
  const projectUsagesQuery = useQuery<ProjectUsageResponse>({
    queryKey: ["workspace-project-usages", ...sessionCacheKey, selectedProjectId, selectedBranchId],
    queryFn: () => api.getProjectUsages(selectedProjectId, selectedBranchId, selectedProject?.workspace_id || undefined, false),
    enabled: projectContextActive && Boolean(selectedProjectId) && Boolean(selectedBranchId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchInterval: projectContextActive ? 10_000 : false,
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    if (treeContextRef.current !== treeContextKey) {
      treeContextRef.current = treeContextKey;
      setTreeNodes(baseTreeNodes);
      treeNodesRef.current = baseTreeNodes;
      setLoadingTreeNodeIds([]);
      return;
    }
    if (!baseTreeNodes.length) {
      setTreeNodes([]);
      treeNodesRef.current = [];
      setLoadingTreeNodeIds([]);
      return;
    }
    setTreeNodes((current) => {
      if (!current.length) {
        treeNodesRef.current = baseTreeNodes;
        return baseTreeNodes;
      }
      const merged = mergeTreeNodesPreservingLoadedChildren(baseTreeNodes, current);
      treeNodesRef.current = merged;
      return merged;
    });
  }, [baseTreeNodes, treeContextKey]);

  useEffect(() => {
    let cancelled = false;
    if (
      !projectContextActive ||
      !selectedProjectId ||
      !selectedBranchId ||
      treeQuery.isFetching ||
      treeNodesRef.current.length ||
      baseTreeNodes.length
    ) {
      return () => {
        cancelled = true;
      };
    }
    void api
      .getTree(selectedProjectId, selectedBranchId, selectedProject?.workspace_id || undefined, false, 0)
      .then((nodes) => {
        if (cancelled || !nodes.length) {
          return;
        }
        treeNodesRef.current = nodes;
        setTreeNodes(nodes);
        queryClient.setQueryData(["workspace-tree", ...sessionCacheKey, selectedProjectId, selectedBranchId], nodes);
      })
      .catch(() => {
        // The normal query path will surface access/API errors. This fallback
        // exists only to recover a valid cached tree that was not mounted into
        // React state after URL/session changes.
      });
    return () => {
      cancelled = true;
    };
  }, [
    baseTreeNodes.length,
    projectContextActive,
    queryClient,
    selectedBranchId,
    selectedProject?.workspace_id,
    selectedProjectId,
    sessionCacheKey,
    treeQuery.isFetching,
  ]);

  useEffect(() => {
    treeNodesRef.current = treeNodes;
  }, [treeNodes]);

  useEffect(() => {
    setItemDetailViewMode(parseItemDetailViewMode(currentPreferences.item_detail_view_mode));
  }, [currentPreferences.item_detail_view_mode]);

  const baseFlatNodes = useMemo(() => flattenTree(baseTreeNodes), [baseTreeNodes]);
  const loadedFlatNodes = useMemo(() => flattenTree(treeNodes), [treeNodes]);
  const selectedTreeNode = useMemo(
    () => (selectedItemId ? loadedFlatNodes.find((node) => node.id === selectedItemId) ?? null : null),
    [loadedFlatNodes, selectedItemId],
  );
  const selectedTreeModelId =
    typeof selectedTreeNode?.metadata.model_id === "string" ? selectedTreeNode.metadata.model_id.trim() : "";
  const branchAccessManifestQuery = useQuery({
    queryKey: ["workspace-access-map", ...sessionCacheKey, selectedProjectId, selectedBranchId],
    queryFn: () => api.getBranchAccessManifestStatus(selectedProjectId, selectedBranchId),
    enabled: Boolean(selectedProjectId) && Boolean(selectedBranchId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  const branchAccessManifestStatus: BranchAccessManifestStatus | null = branchAccessManifestQuery.data ?? null;
  const hasTcwProjectAccessAdmin = Boolean(branchAccessManifestStatus?.current_user_access_admin_access);
  const canAssignProjectAccess = Boolean(isAdmin || hasTcwProjectAccessAdmin);
  const canRefreshAccessMap = Boolean(hasVerifiedTwcPermissionConnection && hasTcwProjectAccessAdmin);
  useEffect(() => {
    if (!canAssignProjectAccess || !selectedProjectId || !selectedBranchId) {
      return;
    }
    setWorkbenchAccessAssignment((current) => ({
      ...current,
      project_id: selectedProjectId,
      branch_id: selectedBranchId,
    }));
  }, [canAssignProjectAccess, selectedBranchId, selectedProjectId]);
  const contractManifest = contractQuery.data ?? null;
  const workbenchBaseUrlExample = typeof window !== "undefined" ? window.location.origin : "https://your-workbench-host";
  const developerApiServerId = session?.server?.id ?? "<server_id>";
  const developerApiProjectId = selectedProjectId || selectedProject?.resource_id || "<project_id>";
  const developerApiBranchId = selectedBranchId || "<branch_id>";
  const developerApiElementId = selectedItemId || "<element_id>";
  const manifestPythonExample = useMemo(
    () => workbenchManifestPythonScript(workbenchBaseUrlExample),
    [workbenchBaseUrlExample],
  );
  const projectDumpPythonExample = useMemo(
    () =>
      workbenchProjectDumpPythonScript(
        workbenchBaseUrlExample,
        developerApiServerId,
        developerApiProjectId,
      ),
    [developerApiProjectId, developerApiServerId, workbenchBaseUrlExample],
  );
  const listElementsPythonExample = useMemo(
    () =>
      workbenchListElementsPythonScript(
        workbenchBaseUrlExample,
        developerApiServerId,
        developerApiProjectId,
        developerApiBranchId,
      ),
    [developerApiBranchId, developerApiProjectId, developerApiServerId, workbenchBaseUrlExample],
  );
  const fullTreePythonExample = useMemo(
    () =>
      workbenchFullTreePythonScript(
        workbenchBaseUrlExample,
        developerApiServerId,
        developerApiProjectId,
        developerApiBranchId,
      ),
    [developerApiBranchId, developerApiProjectId, developerApiServerId, workbenchBaseUrlExample],
  );
  const stereotypeSearchPythonExample = useMemo(
    () =>
      workbenchStereotypeSearchPythonScript(
        workbenchBaseUrlExample,
        developerApiServerId,
        developerApiProjectId,
        developerApiBranchId,
      ),
    [developerApiBranchId, developerApiProjectId, developerApiServerId, workbenchBaseUrlExample],
  );
  const nativeSpecificationPythonExample = useMemo(
    () =>
      workbenchNativeSpecificationPythonScript(
        workbenchBaseUrlExample,
        developerApiServerId,
        developerApiProjectId,
        developerApiBranchId,
        developerApiElementId,
      ),
    [developerApiBranchId, developerApiElementId, developerApiProjectId, developerApiServerId, workbenchBaseUrlExample],
  );
  const specDiagnosticPythonExample = useMemo(
    () =>
      workbenchSpecDiagnosticPythonScript(
        workbenchBaseUrlExample,
        developerApiServerId,
        developerApiProjectId,
        developerApiBranchId,
        developerApiElementId,
      ),
    [developerApiBranchId, developerApiElementId, developerApiProjectId, developerApiServerId, workbenchBaseUrlExample],
  );
  const editElementPythonExample = useMemo(
    () =>
      workbenchEditElementPythonScript(
        workbenchBaseUrlExample,
        developerApiServerId,
        developerApiProjectId,
        developerApiBranchId,
        developerApiElementId,
      ),
    [developerApiBranchId, developerApiElementId, developerApiProjectId, developerApiServerId, workbenchBaseUrlExample],
  );
  const developerApiExamples = useMemo(
    () => [
      {
        title: "Discover the API manifest",
        description: "Start here. Lists the Workbench routes, operation keys, scopes, and schemas available to your API key.",
        value: manifestPythonExample,
        minRows: 18,
      },
      {
        title: "Dump the full project trunk package",
        description: "One Workbench API call that exports branch metadata, full tree, all cached elements, derived details, project usages, and attached permissions for trunk.",
        value: projectDumpPythonExample,
        minRows: 34,
      },
      {
        title: "Retrieve the complete accessible model tree",
        description: "Exports the full stored containment tree for the selected project and branch.",
        value: fullTreePythonExample,
        minRows: 24,
      },
      {
        title: "Get all stored elements",
        description: "Pages through every stored element for the selected project and branch.",
        value: listElementsPythonExample,
        minRows: 22,
      },
      {
        title: "Search by applied stereotype",
        description: "Finds elements by stereotype name across the selected stored snapshot.",
        value: stereotypeSearchPythonExample,
        minRows: 24,
      },
      {
        title: "Read full Cameo-style specification properties",
        description: "Loads native Cameo fields, stereotype/tag values, relationships, usages, allocations, and traceability for one element.",
        value: nativeSpecificationPythonExample,
        minRows: 24,
      },
      {
        title: "Export spec diagnostic mapping payload",
        description: "Troubleshooting view that returns raw plugin payloads beside Workbench's derived specification sections.",
        value: specDiagnosticPythonExample,
        minRows: 28,
      },
      {
        title: "Edit a stored element",
        description: "Shows the plugin-backed edit call shape for updating a stored element when the user has edit access.",
        value: editElementPythonExample,
        minRows: 22,
      },
    ],
    [
      editElementPythonExample,
      fullTreePythonExample,
      listElementsPythonExample,
      manifestPythonExample,
      nativeSpecificationPythonExample,
      projectDumpPythonExample,
      specDiagnosticPythonExample,
      stereotypeSearchPythonExample,
    ],
  );
  const apiTags = useMemo(
    () => Object.keys(contractManifest?.tag_counts ?? {}).sort((left, right) => left.localeCompare(right)),
    [contractManifest],
  );
  const apiOperations = useMemo(() => contractManifest?.operations ?? [], [contractManifest]);
  const filteredApiOperations = useMemo(() => {
    const search = apiSearch.trim().toLowerCase();
    return apiOperations
      .filter((operation) => operation.tag === selectedApiTag)
      .filter((operation) => {
        if (!search) {
          return true;
        }
        return `${operation.method} ${operation.path} ${operation.summary} ${operation.description}`.toLowerCase().includes(search);
      });
  }, [apiOperations, apiSearch, selectedApiTag]);
  const selectedOperation = useMemo(
    () => apiOperations.find((operation) => operation.key === selectedOperationKey) ?? filteredApiOperations[0] ?? null,
    [apiOperations, filteredApiOperations, selectedOperationKey],
  );
  const apiOperationStats = useMemo(
    () =>
      Object.entries(contractManifest?.operation_counts ?? {})
        .map(([method, count]) => `${method} ${count}`)
        .join(" / "),
    [contractManifest],
  );

  const cacheIngestTokenStatus = cacheIngestTokenQuery.data ?? null;
  const cacheApiKeys = cacheApiKeysQuery.data ?? [];

  useEffect(() => {
    if (!workbenchAgentStatus) {
      return;
    }
    setAgentBaseUrlDraft(workbenchAgentStatus.base_url ?? "");
    setAgentSelectedModelId(workbenchAgentStatus.model_id ?? "");
    setAgentSelectedModelName(workbenchAgentStatus.model_name ?? "");
  }, [
    workbenchAgentStatus?.base_url,
    workbenchAgentStatus?.configured,
    workbenchAgentStatus?.model_id,
    workbenchAgentStatus?.model_name,
  ]);

  useEffect(() => {
    if (!agentSelectedModelId || !workbenchAgentModels.length) {
      return;
    }
    const selectedModel = workbenchAgentModels.find((entry) => entry.id === agentSelectedModelId);
    if (selectedModel && selectedModel.name !== agentSelectedModelName) {
      setAgentSelectedModelName(selectedModel.name);
    }
  }, [agentSelectedModelId, agentSelectedModelName, workbenchAgentModels]);

  const contextParameterValue = (parameter: SwaggerParameterSpec): string => {
    const normalized = parameter.name.toLowerCase();
    if (normalized === "workspaceid") {
      return selectedProject?.workspace_id ?? "";
    }
    if (normalized === "resourceid") {
      return selectedProject?.resource_id ?? selectedProjectId;
    }
    if (normalized === "branchid") {
      return selectedBranchId;
    }
    if (normalized === "elementid" || normalized === "modelid") {
      return selectedItemId;
    }
    if (normalized === "source") {
      return compareLeft;
    }
    if (normalized === "target") {
      return compareRight;
    }
    return defaultParameterValue(parameter);
  };

  useEffect(() => {
    if (!selectedApiTag && apiTags.length) {
      setSelectedApiTag(apiTags[0]);
    }
  }, [apiTags, selectedApiTag]);

  useEffect(() => {
    if (!filteredApiOperations.length) {
      setSelectedOperationKey("");
      return;
    }
    if (!filteredApiOperations.some((operation) => operation.key === selectedOperationKey)) {
      setSelectedOperationKey(filteredApiOperations[0].key);
    }
  }, [filteredApiOperations, selectedOperationKey]);

  useEffect(() => {
    if (!selectedOperation) {
      return;
    }
    setApiPathParams(
      selectedOperation.path_parameters.reduce<Record<string, string>>((values, parameter) => {
        values[parameter.name] = contextParameterValue(parameter);
        return values;
      }, {}),
    );
    setApiQueryParams(
      selectedOperation.query_parameters.reduce<Record<string, string>>((values, parameter) => {
        values[parameter.name] = defaultParameterValue(parameter);
        return values;
      }, {}),
    );
    setApiContentType(selectedOperation.request_body?.content_types[0] ?? "");
    setApiBodyText(requestBodyTemplate(selectedOperation, contractManifest));
    setApiUploadFile(null);
  }, [
    selectedOperation,
    contractManifest,
    selectedProject?.workspace_id,
    selectedProject?.resource_id,
    selectedProjectId,
    selectedBranchId,
    selectedItemId,
    compareLeft,
    compareRight,
  ]);

  const itemQuery = useQuery({
    queryKey: ["workspace-item", ...sessionCacheKey, selectedItemId, selectedProjectId, selectedBranchId],
    queryFn: () =>
      api.getItem(
        selectedItemId,
        selectedProjectId || undefined,
        selectedBranchId || undefined,
        selectedProject?.workspace_id || undefined,
        false,
        undefined,
      ),
    enabled: Boolean(selectedItemId),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchInterval: selectedItemId ? 10_000 : false,
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    setItemDraft(itemQuery.data ?? null);
  }, [itemQuery.data]);

  useEffect(() => {
    setSelectedSpecificationSection("properties");
  }, [selectedItemId]);

  useEffect(() => {
    setElementSearchResponse(null);
    setElementSearchSummary("");
  }, [selectedProjectId, selectedBranchId]);

  const selectedTreeFallbackItem = selectedTreeNode && selectedProjectId && selectedBranchId
    ? itemDetailsFromTreeNode(selectedTreeNode, selectedProjectId, selectedBranchId)
    : null;
  const selectedWorkspaceItem = itemQuery.data ?? itemDraft ?? selectedTreeFallbackItem;
  const selectedWorkspaceItemIsDiagram = isDiagramLikeItem(selectedWorkspaceItem);
  const selectedWorkspaceItemDiagramPreviewUrl = selectedWorkspaceItem ? diagramPreviewDataUrl(selectedWorkspaceItem) : null;
  const referenceNameById = useMemo(() => {
    const lookup: Record<string, string> = {};
    projects.forEach((project) => {
      if (project.name) {
        lookup[normalizeLookupKey(project.id)] = project.name;
      }
      if (project.resource_id) {
        lookup[normalizeLookupKey(project.resource_id)] = project.name;
      }
    });
    selectedProjectBranches.forEach((branch) => {
      if (branch.name) {
        lookup[normalizeLookupKey(branch.id)] = branch.name;
      }
    });
    loadedFlatNodes.forEach((node) => {
      if (node.label) {
        lookup[normalizeLookupKey(node.id)] = node.label;
      }
    });
    if (selectedWorkspaceItem?.name) {
      lookup[normalizeLookupKey(selectedWorkspaceItem.id)] = selectedWorkspaceItem.name;
    }
    if (selectedWorkspaceItem?.owner?.name) {
      lookup[normalizeLookupKey(selectedWorkspaceItem.owner.id)] = selectedWorkspaceItem.owner.name;
    }
    selectedWorkspaceItem?.type_references.forEach((reference) => {
      if (reference.name) {
        lookup[normalizeLookupKey(reference.id)] = reference.name;
      }
    });
    selectedWorkspaceItem?.contained_elements.forEach((reference) => {
      if (reference.name) {
        lookup[normalizeLookupKey(reference.id)] = reference.name;
      }
    });
    selectedWorkspaceItem?.related_items.forEach((reference) => {
      if (reference.name) {
        lookup[normalizeLookupKey(reference.id)] = reference.name;
      }
    });
    const cameoReferenceLabels = selectedWorkspaceItem?.metadata?.cameo_reference_labels;
    if (cameoReferenceLabels && typeof cameoReferenceLabels === "object" && !Array.isArray(cameoReferenceLabels)) {
      Object.entries(cameoReferenceLabels as Record<string, unknown>).forEach(([id, label]) => {
        if (typeof label === "string" && label.trim()) {
          lookup[normalizeLookupKey(id)] = label.trim();
        }
      });
    }
    return lookup;
  }, [loadedFlatNodes, projects, selectedProjectBranches, selectedWorkspaceItem]);

  const selectedWorkspaceItemName = selectedWorkspaceItem
    ? displayEntityName(selectedWorkspaceItem.name, selectedWorkspaceItem.id, selectedWorkspaceItem.item_type, referenceNameById, selectedWorkspaceItem.path)
    : "";
  const selectedWorkspaceItemPath = selectedWorkspaceItem ? friendlyPath(selectedWorkspaceItem.path, referenceNameById) : "";
  const selectedPermissionModelId = (() => {
    const candidates = [
      selectedTreeNode?.metadata.model_id,
      selectedWorkspaceItem?.metadata.model_id,
      selectedWorkspaceItem?.source_payload.model_id,
    ];
    return candidates.find((value): value is string => typeof value === "string" && Boolean(value.trim()))?.trim() ?? "";
  })();
  const selectedInnerElementTreeQuery = useQuery({
    queryKey: [
      "workspace-inner-elements-tree",
      ...sessionCacheKey,
      selectedProjectId,
      selectedBranchId,
      selectedItemId,
      selectedPermissionModelId,
      selectedProject?.workspace_id,
    ],
    queryFn: async () => {
      if (!selectedProjectId || !selectedBranchId || !selectedItemId) {
        return [] as TreeNode[];
      }
      const maxDepth = 4;
      const maxNodes = 500;
      let visitedCount = 0;
      const hydrateChildren = async (parentId: string, depth: number): Promise<TreeNode[]> => {
        if (depth > maxDepth || visitedCount >= maxNodes) {
          return [];
        }
        const children = await api.getTreeChildren(
          selectedProjectId,
          selectedBranchId,
          parentId,
          selectedPermissionModelId || undefined,
          selectedProject?.workspace_id || undefined,
          false,
        );
        const hydrated: TreeNode[] = [];
        for (const child of children) {
          if (visitedCount >= maxNodes) {
            break;
          }
          visitedCount += 1;
          const childCount =
            typeof child.metadata.child_count === "number"
              ? child.metadata.child_count
              : typeof child.metadata.total_children === "number"
                ? child.metadata.total_children
                : typeof child.metadata.children === "number"
                  ? child.metadata.children
                  : child.children.length;
          const loadedChildren = child.children.length
            ? child.children
            : childCount > 0 && depth < maxDepth
              ? await hydrateChildren(child.id, depth + 1)
              : [];
          hydrated.push({ ...child, children: loadedChildren });
        }
        return hydrated;
      };
      return hydrateChildren(selectedItemId, 0);
    },
    enabled: Boolean(
      projectContextActive &&
      selectedSpecificationSection === "inner-elements" &&
      selectedProjectId &&
      selectedBranchId &&
      selectedItemId,
    ),
    staleTime: cacheTimeMs,
    gcTime: cacheTimeMs,
    refetchOnWindowFocus: false,
  });
  useEffect(() => {
    if (selectedSpecificationSection !== "inner-elements") {
      return;
    }
    const nodes = selectedInnerElementTreeQuery.data ?? [];
    setExpandedInnerElementNodeIds(expandableTreeNodeIds(nodes));
  }, [selectedItemId, selectedSpecificationSection, selectedInnerElementTreeQuery.data]);
  const currentPermissionStatusQuery = useQuery({
    queryKey: [
      "workspace-current-permission",
      ...sessionCacheKey,
      selectedProjectId,
      selectedBranchId,
      selectedPermissionModelId,
    ],
    queryFn: () => api.getCurrentPermissionStatus(
      selectedProjectId,
      selectedBranchId,
      selectedPermissionModelId || undefined,
    ),
    enabled: Boolean(selectedProjectId && selectedBranchId),
    staleTime: 5_000,
    gcTime: cacheTimeMs,
    refetchInterval: 10_000,
    refetchOnWindowFocus: true,
  });

  useEffect(() => {
    const status = currentPermissionStatusQuery.data;
    if (
      !status ||
      status.project_id !== selectedProjectId ||
      status.branch_id !== selectedBranchId ||
      (status.model_id ?? "") !== selectedPermissionModelId
    ) {
      return;
    }
    if (!status.branch_accessible) {
      const branchQueryKey = [
        "workspace-branches",
        session?.user?.preferred_username ?? "anonymous",
        session?.server?.id ?? "no-server",
        selectedProjectId,
        selectedProject?.workspace_id,
      ];
      queryClient.setQueryData<ProjectSummary["branches"]>(branchQueryKey, (current) =>
        current?.filter((branch) => branch.id !== selectedBranchId),
      );
      void queryClient.invalidateQueries({ queryKey: branchQueryKey });
      setSelectedBranchId("");
      setSelectedItemId("");
      setItemDraft(null);
      setNotice({ severity: "warning", message: "The selected branch is no longer accessible and was closed. Other permitted branches remain available." });
      return;
    }
    if (selectedPermissionModelId && status.model_accessible === false) {
      setSelectedItemId("");
      setItemDraft(null);
      setNotice({ severity: "warning", message: "The selected model is no longer accessible and was closed. The permitted remainder of the branch stays open." });
    }
  }, [
    currentPermissionStatusQuery.data,
    queryClient,
    selectedBranchId,
    selectedPermissionModelId,
    selectedProject?.workspace_id,
    selectedProjectId,
    session?.server?.id,
    session?.user?.preferred_username,
  ]);
  const selectedContainmentPath = selectedWorkspaceItemPath || (selectedTreeNode ? friendlyPath(selectedTreeNode.path, referenceNameById) : "");
  const selectedContainmentSegments = selectedContainmentPath
    .split(" / ")
    .map((segment) => segment.trim())
    .filter(Boolean);
  const showAuxiliaryResourcesInTree = Boolean(
    currentPreferences.show_hidden_packages_in_tree || currentPreferences.show_auxiliary_resources_in_tree,
  );
  const showAppliedStereotypesInTree = Boolean(currentPreferences.show_applied_stereotypes_in_tree);
  const visibleTreeNodes = useMemo(
    () => {
      const filtered = filterContainmentTree(treeNodes, {
        showAuxiliaryResources: showAuxiliaryResourcesInTree,
        showAppliedStereotypes: showAppliedStereotypesInTree,
      });
      if (!filtered.length && treeNodes.length && !treeFilter.trim()) {
        return treeNodes;
      }
      return filtered;
    },
    [showAppliedStereotypesInTree, showAuxiliaryResourcesInTree, treeFilter, treeNodes],
  );
  const selectedWorkbenchAgentModel = useMemo<OpenWebUIModelEntry | null>(
    () => workbenchAgentModels.find((entry) => entry.id === agentSelectedModelId) ?? null,
    [agentSelectedModelId, workbenchAgentModels],
  );
  const workbenchAgentProjectLabel = selectedProject?.name || "Select a project";
  const workbenchAgentBranchLabel = selectedBranchId ? branchLabel(selectedProjectBranches, selectedBranchId) : "Select a branch";
  const compareLeftName = compareLeft.trim() ? humanReadableReference(compareLeft, referenceNameById) : "";
  const compareRightName = compareRight.trim() ? humanReadableReference(compareRight, referenceNameById) : "";
  const compareLeftFieldValue = compareLeftDisplay || compareLeft;
  const compareRightFieldValue = compareRightDisplay || compareRight;
  const compareLeftLabel = compareLeft.trim()
    ? compareLeftName !== compareLeft || isRevisionValue(compareLeft)
      ? compareLeftName
      : "Selected item reference"
    : "";
  const compareRightLabel = compareRight.trim()
    ? compareRightName !== compareRight || isRevisionValue(compareRight)
      ? compareRightName
      : "Selected item reference"
    : "";
  const compareLeftContextLabel = compareLeftProject
    ? `${compareLeftProject.name} / ${branchLabel(compareLeftBranches, compareLeftBranchId)}`
    : "Select a left project and branch";
  const compareRightContextLabel = compareRightProject
    ? `${compareRightProject.name} / ${branchLabel(compareRightBranches, compareRightBranchId)}`
    : "Select a right project and branch";
  const selectedSearchDetail = useMemo(
    () => elementSearchResponse?.details.find((detail) => detail.id === selectedItemId) ?? null,
    [elementSearchResponse, selectedItemId],
  );
  const selectedSearchWorkspaceItem = selectedWorkspaceItem ?? selectedSearchDetail;

  const logoutMutation = useMutation({
    mutationFn: () => api.logout(csrfToken),
    onSuccess: async () => {
      await refreshSession();
      navigate("/", { replace: true });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const capabilityMutation = useMutation({
    mutationFn: () => api.refreshCapabilities(csrfToken, {
      selected_project_id: selectedProjectId || undefined,
      selected_branch_id: selectedBranchId || undefined,
      selected_model_id: selectedPermissionModelId || undefined,
    }),
    onSuccess: async (capabilities) => {
      await refreshSession();
      const jobId = capabilities.permission_refresh_job_id;
      if (!jobId) {
        setNotice({ severity: "warning", message: "Capabilities refreshed, but Workbench did not receive a permission refresh job identifier." });
        return;
      }
      setNotice({ severity: "info", message: "Permission refresh is running in the background. You can keep working in the open model." });
      void (async () => {
        try {
          let job = await api.getJob(jobId);
          const deadline = Date.now() + 20 * 60 * 1000;
          while (job.status === "pending" || job.status === "running") {
            if (Date.now() >= deadline) {
              throw new Error("The permission refresh is still running. Its status remains available in Job Center.");
            }
            await new Promise((resolve) => window.setTimeout(resolve, 2_000));
            job = await api.getJob(jobId);
          }
          await refreshSession();
          if (job.status !== "succeeded" || !job.result) {
            setNotice({ severity: "warning", message: job.message || "Teamwork Cloud could not confirm the permission refresh. The last valid snapshot remains active." });
            return;
          }

          const result = job.result;
          const projects = await api.getProjects(false);
          queryClient.setQueryData(["workspace-projects", ...sessionCacheKey], projects);
          const projectWasRevoked = Boolean(
            selectedProjectId && !projects.some((project) => project.id === selectedProjectId),
          );
          if (projectWasRevoked) {
            setSelectedProjectId("");
            setSelectedBranchId("");
            setSelectedItemId("");
            setItemDraft(null);
            queryClient.removeQueries({ queryKey: ["workspace-branches", ...sessionCacheKey] });
            queryClient.removeQueries({ queryKey: ["workspace-tree", ...sessionCacheKey] });
            queryClient.removeQueries({ queryKey: ["workspace-project-usages", ...sessionCacheKey] });
            queryClient.removeQueries({ queryKey: ["workspace-access-map", ...sessionCacheKey] });
            queryClient.removeQueries({ queryKey: ["workspace-item", ...sessionCacheKey] });
            setNotice({ severity: "warning", message: "Teamwork Cloud no longer grants access to the selected project, so it was closed." });
            return;
          }

          if (selectedProjectId) {
            const branches = await api.getProjectBranches(selectedProjectId, selectedProject?.workspace_id || undefined, false);
            queryClient.setQueryData(
              ["workspace-branches", ...sessionCacheKey, selectedProjectId, selectedProject?.workspace_id],
              branches,
            );
            if (selectedBranchId && !branches.some((branch) => branch.id === selectedBranchId)) {
              setSelectedBranchId("");
              setSelectedItemId("");
              setItemDraft(null);
              queryClient.removeQueries({ queryKey: ["workspace-tree", ...sessionCacheKey, selectedProjectId, selectedBranchId] });
              queryClient.removeQueries({ queryKey: ["workspace-project-usages", ...sessionCacheKey, selectedProjectId, selectedBranchId] });
              queryClient.removeQueries({ queryKey: ["workspace-access-map", ...sessionCacheKey, selectedProjectId, selectedBranchId] });
              queryClient.removeQueries({ queryKey: ["workspace-item", ...sessionCacheKey] });
              setNotice({ severity: "warning", message: "The selected branch is no longer accessible and was closed. Other permitted branches remain available." });
              return;
            }
          }

          const revokedModels = Array.isArray(result.revoked_models) ? result.revoked_models : [];
          const selectedModelKey = selectedProjectId && selectedBranchId && selectedPermissionModelId
            ? `${selectedProjectId}/${selectedBranchId}/${selectedPermissionModelId}`
            : "";
          if (selectedModelKey && revokedModels.includes(selectedModelKey)) {
            setSelectedItemId("");
            setItemDraft(null);
            queryClient.removeQueries({ queryKey: ["workspace-item", ...sessionCacheKey] });
            void queryClient.invalidateQueries({ queryKey: ["workspace-tree", ...sessionCacheKey, selectedProjectId, selectedBranchId] });
            setNotice({ severity: "warning", message: "The selected model is no longer accessible and was closed. The permitted remainder of the branch stays open." });
            return;
          }

          void Promise.all([
            queryClient.invalidateQueries({ queryKey: ["workspace-tree", ...sessionCacheKey, selectedProjectId, selectedBranchId] }),
            queryClient.invalidateQueries({ queryKey: ["workspace-item", ...sessionCacheKey] }),
            queryClient.invalidateQueries({ queryKey: ["workspace-project-usages", ...sessionCacheKey, selectedProjectId, selectedBranchId] }),
            queryClient.invalidateQueries({ queryKey: ["workspace-access-map", ...sessionCacheKey, selectedProjectId, selectedBranchId] }),
          ]);
          setNotice({ severity: "success", message: "Permissions refreshed without reloading the open project, branch, or model." });
        } catch (caught) {
          await refreshSession();
          setNotice({ severity: "warning", message: `${errorMessage(caught)} The last valid permission snapshot remains active.` });
        }
      })();
    },
    onError: () => setNotice({ severity: "warning", message: "Teamwork Cloud could not confirm the refresh. Your last valid project access remains active and the open model was not disturbed." }),
  });

  const settingsMutation = useMutation({
    mutationFn: (preferences: SessionPreferences) => api.updatePreferences(preferences, csrfToken),
    onSuccess: (preferences) => {
      if (session) {
        setSessionSnapshot({
          ...session,
          preferences,
        });
      }
      setNotice({ severity: "success", message: "Workspace settings saved." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const updateSessionPreferences = async (patch: Partial<SessionPreferences>) => {
    await settingsMutation.mutateAsync({
      ...currentPreferences,
      ...patch,
    });
  };

  const elementSearchMutation = useMutation({
    mutationFn: async (mode: ElementSearchMode) => {
      if (!selectedProjectId || !selectedBranchId) {
        throw new Error("Select a project and branch before searching stored model data.");
      }
      if (mode === "stereotype") {
        const stereotype = elementSearchStereotype.trim();
        if (!stereotype) {
          throw new Error("Enter a stereotype name before running a stereotype search.");
        }
        return {
          mode,
          response: await api.searchCachedElementsByStereotype({
            projectId: selectedProjectId,
            branchId: selectedBranchId,
            stereotype,
            includeDetails: true,
            limit: 500,
          }),
        };
      }
      const query = elementSearchQuery.trim();
      if (!query) {
        throw new Error("Enter an element, package, resource, or ID query before searching.");
      }
      return {
        mode,
        response: await api.searchCachedElements({
          projectId: selectedProjectId,
          branchId: selectedBranchId,
          q: query,
          itemType: elementSearchItemType.trim() || undefined,
          includeDetails: true,
          limit: 500,
        }),
      };
    },
    onSuccess: ({ mode, response }) => {
      setElementSearchMode(mode);
      setElementSearchResponse(response);
      const summary =
        mode === "stereotype"
          ? `Found ${response.total} stored branch element${response.total === 1 ? "" : "s"} matching stereotype "${elementSearchStereotype.trim()}".`
          : `Found ${response.total} stored branch element${response.total === 1 ? "" : "s"} for "${elementSearchQuery.trim()}".`;
      setElementSearchSummary(summary);
      if (response.items.length) {
        const nextId = response.items[0].element_id;
        setSelectedItemId((current) => (current && response.items.some((item) => item.element_id === current) ? current : nextId));
      }
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const itemDetailViewModeMutation = useMutation({
    mutationFn: (nextMode: ItemDetailViewMode) =>
      api.updatePreferences(
        {
          ...currentPreferences,
          item_detail_view_mode: nextMode,
        },
        csrfToken,
      ),
    onMutate: async (_nextMode) => ({ previousMode: itemDetailViewMode }),
    onError: (caught, _nextMode, context) => {
      setItemDetailViewMode(context?.previousMode ?? parseItemDetailViewMode(currentPreferences.item_detail_view_mode));
      setNotice({ severity: "error", message: errorMessage(caught) });
    },
  });

  const handleItemDetailViewModeChange = (_event: ReactMouseEvent<HTMLElement> | SyntheticEvent, nextMode: ItemDetailViewMode | null) => {
    if (!nextMode || nextMode === itemDetailViewMode) {
      return;
    }
    setItemDetailViewMode(nextMode);
    itemDetailViewModeMutation.mutate(nextMode);
  };

  const refreshProjectsMutation = useMutation({
    mutationFn: () => api.getProjects(true),
    onSuccess: (projects) => {
      queryClient.setQueryData(["workspace-projects", ...sessionCacheKey], projects);
      setNotice({ severity: "success", message: "Stored project list reloaded." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const exportDebugProjectDumpMutation = useMutation({
    mutationFn: async (): Promise<Record<string, unknown>> => {
      if (!debugProjectId) {
        throw new Error("Select a project before exporting a Workbench digest.");
      }
      const branchId = debugBranchId || "trunk";
      const branch = debugBranches.find((candidate) => candidate.id === branchId);
      const url = api.projectBranchDumpDownloadUrl({
        projectId: debugProjectId,
        branchId,
        includeTree: true,
        includeElements: true,
        includeDetails: true,
        includeRawPayload: true,
        includePermissions: true,
      });
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener";
      document.body.appendChild(link);
      link.click();
      link.remove();
      return {
        project_id: debugProjectId,
        project_name: debugProject?.name ?? debugProjectId,
        branch_id: branchId,
        branch_name: branch?.name || branchId,
        workspace_id: debugProject?.workspace_id ?? null,
        export_started_at: new Date().toISOString(),
      };
    },
    onSuccess: (digest) => {
      setDebugDumpDigest(digest);
      setNotice({ severity: "success", message: "Started full Workbench digest download. The UI no longer parses the large payload." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const exportTableauProjectDbMutation = useMutation({
    mutationFn: async (): Promise<Record<string, unknown>> => {
      if (!debugProjectId) {
        throw new Error("Select a project before exporting a Tableau database.");
      }
      const branchId = debugBranchId || "trunk";
      const branch = debugBranches.find((candidate) => candidate.id === branchId);
      const url = api.projectBranchTableauDbDownloadUrl({
        projectId: debugProjectId,
        branchId,
      });
      const link = document.createElement("a");
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener";
      document.body.appendChild(link);
      link.click();
      link.remove();
      return {
        export_type: "tableau-sqlite",
        project_id: debugProjectId,
        project_name: debugProject?.name ?? debugProjectId,
        branch_id: branchId,
        branch_name: branch?.name || branchId,
        workspace_id: debugProject?.workspace_id ?? null,
        export_started_at: new Date().toISOString(),
      };
    },
    onSuccess: (digest) => {
      setDebugDumpDigest(digest);
      setNotice({ severity: "success", message: "Started Tableau SQLite project database download." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const refreshSelectedProjectMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProjectId) {
        throw new Error("Select a project before refreshing.");
      }
      const branches = await api.getProjectBranches(selectedProjectId, selectedProject?.workspace_id || undefined, true);
      let tree: TreeNode[] | null = null;
      const currentBranchId = selectedBranchId || branches[0]?.id;
      if (currentBranchId) {
        tree = await api.getTree(selectedProjectId, currentBranchId, selectedProject?.workspace_id || undefined, true, 0);
      }
      return { branches, tree, branchId: currentBranchId ?? "" };
    },
    onSuccess: ({ branches, tree, branchId }) => {
      queryClient.setQueryData(["workspace-branches", ...sessionCacheKey, selectedProjectId, selectedProject?.workspace_id], branches);
      if (branchId) {
        queryClient.setQueryData(["workspace-tree", ...sessionCacheKey, selectedProjectId, branchId], tree ?? []);
        setSelectedBranchId(branchId);
      }
      setNotice({ severity: "success", message: "Stored project data reloaded and permissions rechecked." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const refreshItemMutation = useMutation({
    mutationFn: () => {
      if (!selectedItemId) {
        throw new Error("Select an item before refreshing.");
      }
      return api.getItem(
        selectedItemId,
        selectedProjectId || undefined,
        selectedBranchId || undefined,
        selectedProject?.workspace_id || undefined,
        true,
        undefined,
      );
    },
    onSuccess: (item) => {
      queryClient.setQueryData(["workspace-item", ...sessionCacheKey, selectedItemId, selectedProjectId, selectedBranchId], item);
      setItemDraft(item);
      setNotice({ severity: "success", message: "Stored model item reloaded and permissions rechecked." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const refreshBranchAccessManifestMutation = useMutation({
    mutationFn: () => {
      if (!selectedProjectId || !selectedBranchId) {
        throw new Error("Select a project branch before refreshing access.");
      }
      return api.refreshBranchAccessManifest(selectedProjectId, selectedBranchId, csrfToken);
    },
    onSuccess: async (status) => {
      queryClient.setQueryData(["workspace-access-map", ...sessionCacheKey, selectedProjectId, selectedBranchId], status);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workspace-projects", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-branches", ...sessionCacheKey, selectedProjectId, selectedProject?.workspace_id] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-tree", ...sessionCacheKey, selectedProjectId, selectedBranchId] }),
        selectedItemId
          ? queryClient.invalidateQueries({
              queryKey: ["workspace-item", ...sessionCacheKey, selectedItemId, selectedProjectId, selectedBranchId],
            })
          : Promise.resolve(),
      ]);
      setNotice({ severity: "success", message: "Shared access map refreshed from Teamwork Cloud." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const saveItemMutation = useMutation({
    mutationFn: () => {
      if (!selectedItemId || !itemDraft) {
        throw new Error("Select an item before saving.");
      }
      return api.updateItem(
        selectedItemId,
        {
          name: itemDraft.name,
          description: itemDraft.description,
        },
        csrfToken,
        selectedProjectId || undefined,
        selectedBranchId || undefined,
      );
    },
    onSuccess: async (savedItem) => {
      setItemDraft(savedItem);
      await queryClient.invalidateQueries({ queryKey: ["workspace-item", ...sessionCacheKey] });
      await queryClient.invalidateQueries({ queryKey: ["workspace-tree", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "Item saved to Teamwork Cloud." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const compareMutation = useMutation({
    mutationFn: () => {
      if (!compareLeftProjectId || !compareLeftBranchId || !compareRightProjectId || !compareRightBranchId) {
        throw new Error("Select a project and branch on both sides before comparing.");
      }
      if (compareMode === "branch") {
        return api.compareBranches(
          compareLeftProjectId,
          compareLeftBranchId,
          compareRightProjectId,
          compareRightBranchId,
        );
      }
      return api.compare(
        compareLeft.trim(),
        compareRight.trim(),
        compareLeftProjectId,
        compareLeftBranchId,
        compareRightProjectId,
        compareRightBranchId,
      );
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const apiOperationMutation = useMutation({
    mutationFn: () => {
      if (!selectedOperation) {
        throw new Error("Select a Swagger operation first.");
      }
      const pathParams = collectParameterValues(selectedOperation.path_parameters, apiPathParams);
      const queryParams = collectParameterValues(selectedOperation.query_parameters, apiQueryParams);
      if (selectedOperation.supports_file_upload) {
        if (!apiUploadFile) {
          throw new Error("Select a file before running this upload operation.");
        }
        return api.executeContractUpload(selectedOperation.key, pathParams, queryParams, apiUploadFile, csrfToken);
      }
      let body: unknown = undefined;
      const bodyText = apiBodyText.trim();
      if (selectedOperation.request_body && bodyText) {
        body = apiContentType === "text/plain" ? apiBodyText : JSON.parse(bodyText);
      }
      return api.executeContractOperation(
        {
          operation_key: selectedOperation.key,
          path_params: pathParams,
          query_params: queryParams,
          body,
          content_type: selectedOperation.request_body ? apiContentType || selectedOperation.request_body.content_types[0] : null,
          timeout_seconds: 30,
        },
        csrfToken,
      );
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const rotateCacheIngestTokenMutation = useMutation({
    mutationFn: () => api.rotateCacheIngestToken(csrfToken),
    onSuccess: async (result) => {
      setRevealedCacheIngestToken(result.token);
      setManualCacheIngestToken(result.token);
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "A new plugin ingest token was generated and stored inside Workbench." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const retryPermissionInventoryMutation = useMutation({
    mutationFn: () => api.retryPermissionInventory(csrfToken),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workspace-permission-inventory-status", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-permission-inventory-details", ...sessionCacheKey] }),
      ]);
      setNotice({ severity: "success", message: "The TWC permission inventory refresh was queued in the background." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const updateAuthSettingsMutation = useMutation({
    mutationFn: (payload: Partial<WorkbenchAuthSettings>) => api.updateAuthManagementSettings(payload, csrfToken),
    onSuccess: async (status) => {
      setAuthSettingsDraft(status.settings);
      queryClient.setQueryData(["auth-management-status", ...sessionCacheKey], status);
      setNotice({ severity: "success", message: "Workbench authentication settings were saved." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const revealCacheIngestTokenMutation = useMutation({
    mutationFn: () => api.revealCacheIngestToken(csrfToken),
    onSuccess: (result) => {
      setRevealedCacheIngestToken(result.token);
      setManualCacheIngestToken(result.token);
      setNotice({ severity: "success", message: "Current app-managed plugin ingest token revealed. Copy it into the Cameo plugin." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const createWorkbenchUserMutation = useMutation({
    mutationFn: (payload: WorkbenchUserCreateRequest) => api.createWorkbenchUser(payload, csrfToken),
    onSuccess: async () => {
      setNewWorkbenchUser({ username: "", password: "", role: "user", enabled: true, display_name: "" });
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workbench-users", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["auth-management-status", ...sessionCacheKey] }),
      ]);
      setNotice({ severity: "success", message: "Workbench user created." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const updateWorkbenchUserMutation = useMutation({
    mutationFn: ({ username, payload }: { username: string; payload: WorkbenchUserUpdateRequest }) =>
      api.updateWorkbenchUser(username, payload, csrfToken),
    onSuccess: async (user) => {
      setWorkbenchPasswordResets((current) => {
        const next = { ...current };
        delete next[user.username];
        return next;
      });
      await queryClient.invalidateQueries({ queryKey: ["workbench-users", ...sessionCacheKey] });
      setNotice({ severity: "success", message: `Workbench user ${user.username} updated.` });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const deleteWorkbenchUserMutation = useMutation({
    mutationFn: (username: string) => api.deleteWorkbenchUser(username, csrfToken),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workbench-users", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["auth-management-status", ...sessionCacheKey] }),
      ]);
      setNotice({ severity: "success", message: "Workbench user deleted." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const createWorkbenchGroupMutation = useMutation({
    mutationFn: (payload: WorkbenchGroupCreateRequest) => api.createWorkbenchGroup(payload, csrfToken),
    onSuccess: async () => {
      setNewWorkbenchGroup({ name: "", description: "", users: [], enabled: true });
      await queryClient.invalidateQueries({ queryKey: ["workbench-groups", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "Workbench group created." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const updateWorkbenchGroupMutation = useMutation({
    mutationFn: ({ name, payload }: { name: string; payload: WorkbenchGroupUpdateRequest }) =>
      api.updateWorkbenchGroup(name, payload, csrfToken),
    onSuccess: async (group) => {
      setWorkbenchGroupUserDrafts((current) => {
        const next = { ...current };
        delete next[group.name];
        return next;
      });
      await queryClient.invalidateQueries({ queryKey: ["workbench-groups", ...sessionCacheKey] });
      setNotice({ severity: "success", message: `Workbench group ${group.name} updated.` });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const deleteWorkbenchGroupMutation = useMutation({
    mutationFn: (name: string) => api.deleteWorkbenchGroup(name, csrfToken),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workbench-groups", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "Workbench group deleted." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const assignWorkbenchProjectAccessMutation = useMutation({
    mutationFn: (payload: WorkbenchProjectAccessAssignmentRequest) => api.assignWorkbenchProjectAccess(payload, csrfToken),
    onSuccess: async (response) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workbench-users", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workbench-groups", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-projects", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-branches", ...sessionCacheKey] }),
      ]);
      setNotice({ severity: "success", message: response.message });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const createServerMutation = useMutation({
    mutationFn: (payload: ServerProfileInput) => api.createServer(payload, csrfToken),
    onSuccess: async () => {
      setNewServerPreset(createServerProfileDraft());
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["managed-servers", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-projects", ...sessionCacheKey] }),
      ]);
      setNotice({ severity: "success", message: "Workbench server profile created. Use its server key as the Cameo plugin metadata.serverId." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const updateServerMutation = useMutation({
    mutationFn: ({ serverId, payload }: { serverId: string; payload: Partial<ServerProfileInput> }) =>
      api.updateServer(serverId, payload, csrfToken),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["managed-servers", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-projects", ...sessionCacheKey] }),
      ]);
      setNotice({ severity: "success", message: "TWC server preset updated." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const deleteServerMutation = useMutation({
    mutationFn: (serverId: string) => api.deleteServer(serverId, csrfToken),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["managed-servers", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-projects", ...sessionCacheKey] }),
      ]);
      setNotice({ severity: "success", message: "TWC server preset deleted." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });


  const storeCacheIngestTokenMutation = useMutation({
    mutationFn: () =>
      api.updateCacheIngestToken(
        {
          token: manualCacheIngestToken.trim(),
        },
        csrfToken,
      ),
    onSuccess: async () => {
      setRevealedCacheIngestToken("");
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "The exact plugin ingest token was saved in encrypted Workbench app storage." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const clearCacheIngestTokenMutation = useMutation({
    mutationFn: () => api.clearCacheIngestToken(csrfToken),
    onSuccess: async () => {
      setRevealedCacheIngestToken("");
      setManualCacheIngestToken("");
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "The app-managed plugin ingest token was cleared." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const createCacheApiKeyMutation = useMutation({
    mutationFn: () =>
      api.createCacheApiKey(
        {
          label: newCacheApiKeyLabel.trim(),
          scopes: newCacheApiKeyScopes,
        },
        csrfToken,
      ),
    onSuccess: async (result) => {
      setRevealedCacheApiKey(result.token);
      setNewCacheApiKeyLabel("");
      setNewCacheApiKeyScopes(["read"]);
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-api-keys", ...sessionCacheKey] });
      setNotice({
        severity: "success",
        message: "API key created. Copy it now; Workbench will not show the full value again after you leave this screen.",
      });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const deleteCacheApiKeyMutation = useMutation({
    mutationFn: (keyId: string) => api.deleteCacheApiKey(keyId, csrfToken),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["workspace-cache-api-keys", ...sessionCacheKey] });
      setNotice({ severity: "success", message: "API key deleted." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const saveWorkbenchAgentConfigMutation = useMutation({
    mutationFn: () =>
      api.updateWorkbenchAgentConfig(
        {
          base_url: agentBaseUrlDraft.trim(),
          api_key: agentApiKeyDraft,
          model_id: agentSelectedModelId,
          model_name: agentSelectedModelName,
        },
        csrfToken,
      ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workspace-agent", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-agent-models", ...sessionCacheKey] }),
      ]);
      setNotice({
        severity: "success",
        message: agentSelectedModelId
          ? "Workbench Agent mapping saved in encrypted Workbench storage."
          : "Open WebUI connection saved. Load models next and map one into Workbench Agent.",
      });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const clearWorkbenchAgentConfigMutation = useMutation({
    mutationFn: () => api.clearWorkbenchAgentConfig(csrfToken),
    onSuccess: async () => {
      setAgentBaseUrlDraft("");
      setAgentApiKeyDraft("");
      setAgentSelectedModelId("");
      setAgentSelectedModelName("");
      setAgentMessages([]);
      setAgentChatInput("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["workspace-agent", ...sessionCacheKey] }),
        queryClient.invalidateQueries({ queryKey: ["workspace-agent-models", ...sessionCacheKey] }),
      ]);
      setNotice({ severity: "success", message: "Workbench Agent mapping cleared for this user." });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const syncWorkbenchAgentKnowledgeMutation = useMutation({
    mutationFn: async () => {
      if (!selectedProjectId || !selectedBranchId) {
        throw new Error("Select a project and branch before syncing Workbench Agent knowledge.");
      }
      let job: JobRecord = await api.startWorkbenchAgentKnowledgeSync(
        {
          project_id: selectedProjectId,
          branch_id: selectedBranchId,
        },
        csrfToken,
      );
      setAgentKnowledgeSyncProgress(`${job.progress}% - ${job.message || "Knowledge push queued"}`);
      const deadline = Date.now() + 31 * 60 * 1000;
      while (job.status === "pending" || job.status === "running") {
        if (Date.now() >= deadline) {
          throw new Error("Workbench Agent knowledge processing is still running after 31 minutes. Check Job Center for its current status.");
        }
        await new Promise((resolve) => window.setTimeout(resolve, 2_000));
        job = await api.getJob(job.id);
        setAgentKnowledgeSyncProgress(`${job.progress}% - ${job.message || "Processing knowledge"}`);
      }
      if (job.status !== "succeeded") {
        throw new Error(job.message || "Workbench Agent knowledge processing failed.");
      }
      if (!job.result) {
        throw new Error("Workbench Agent knowledge processing completed without a result.");
      }
      return job.result as unknown as WorkbenchAgentKnowledgeStatus;
    },
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({ queryKey: ["workspace-agent", ...sessionCacheKey] });
      setAgentKnowledgeSyncProgress("100% - Knowledge push completed");
      setNotice({ severity: "success", message: result.message });
    },
    onError: (caught) => {
      setAgentKnowledgeSyncProgress("");
      setNotice({ severity: "error", message: errorMessage(caught) });
    },
  });

  const workbenchAgentChatMutation = useMutation({
    mutationFn: async (payload: { messages: WorkbenchAgentChatMessage[]; syncKnowledge: boolean }) => {
      if (!selectedProjectId || !selectedBranchId) {
        throw new Error("Select a project and branch before starting a Workbench Agent conversation.");
      }
      if (payload.syncKnowledge) {
        let job = await api.startWorkbenchAgentKnowledgeSync(
          { project_id: selectedProjectId, branch_id: selectedBranchId },
          csrfToken,
        );
        setAgentKnowledgeSyncProgress(`${job.progress}% - ${job.message || "Knowledge push queued"}`);
        const deadline = Date.now() + 31 * 60 * 1000;
        while (job.status === "pending" || job.status === "running") {
          if (Date.now() >= deadline) {
            throw new Error("Workbench Agent knowledge processing is still running after 31 minutes. Check Job Center for its current status.");
          }
          await new Promise((resolve) => window.setTimeout(resolve, 2_000));
          job = await api.getJob(job.id);
          setAgentKnowledgeSyncProgress(`${job.progress}% - ${job.message || "Processing knowledge"}`);
        }
        if (job.status !== "succeeded") {
          throw new Error(job.message || "Workbench Agent knowledge processing failed.");
        }
        setAgentKnowledgeSyncProgress("100% - Knowledge push completed");
      }
      return api.runWorkbenchAgentChat(
        {
          project_id: selectedProjectId,
          branch_id: selectedBranchId,
          messages: payload.messages,
          sync_knowledge: false,
        },
        csrfToken,
      );
    },
    onSuccess: async (result, variables) => {
      setAgentMessages([
        ...variables.messages,
        {
          role: "assistant",
          content: result.assistant_message,
        },
      ]);
      await queryClient.invalidateQueries({ queryKey: ["workspace-agent", ...sessionCacheKey] });
      setNotice({ severity: "success", message: result.message });
    },
    onError: (caught) => setNotice({ severity: "error", message: errorMessage(caught) }),
  });

  const handleTabChange = (_event: SyntheticEvent, nextTab: WorkspaceTab) => {
    setTab(nextTab);
  };

  const openWorkspaceMenu = (group: WorkspaceMenuGroup) => (event: ReactMouseEvent<HTMLElement>) => {
    setWorkspaceMenuGroup(group);
    setWorkspaceMenuAnchorEl(event.currentTarget);
  };

  const closeWorkspaceMenu = () => {
    setWorkspaceMenuGroup(null);
    setWorkspaceMenuAnchorEl(null);
  };

  const openUserMenu = (event: ReactMouseEvent<HTMLElement>) => {
    setUserMenuAnchorEl(event.currentTarget);
  };

  const closeUserMenu = () => {
    setUserMenuAnchorEl(null);
  };

  const currentMenuGroup = (() => {
    if (tab === "developer" || tab === "api") {
      return "api" as const;
    }
    if (tab === "diagram-viewer") {
      return "diagrams" as const;
    }
    return "views" as const;
  })();
  const userMenuLabel = session?.user?.preferred_username || "User";

  const selectProject = (projectId: string) => {
    setSelectedProjectId(projectId);
    setSelectedBranchId("");
    setSelectedItemId("");
    setItemDraft(null);
    setElementSearchResponse(null);
    setElementSearchSummary("");
  };

  const openProjectInModelBrowser = (projectId: string) => {
    selectProject(projectId);
    setTab("models");
  };

  const selectContainmentNode = (node: TreeNode, preferredTab: WorkspaceTab = "models") => {
    setSelectedItemId(node.id);
    if (tab !== preferredTab) {
      setTab(preferredTab);
    }
  };

  const openNode = (node: TreeNode) => {
    setSelectedItemId(node.id);
    setTab("models");
  };

  const openElementId = (itemId: string) => {
    setSelectedItemId(itemId);
    setTab("models");
  };

  const revealElementPathInTree = async (item: ItemDetails | null) => {
    if (!item || !selectedProjectId || !selectedBranchId) {
      return;
    }
    const loadedTrail = findNodeTrail(treeNodesRef.current, item.id);
    if (loadedTrail.length) {
      setExpandedTreeNodeIds(Array.from(new Set([...expandedTreeNodeIds, ...loadedTrail.slice(0, -1).map((node) => node.id)])));
      setSelectedItemId(item.id);
      setTab("models");
      return;
    }
    const ownerChainIds: string[] = [];
    const visitedOwnerIds = new Set<string>([item.id]);
    let currentOwnerId = item.owner?.id || (typeof item.source_payload.owner_id === "string" ? item.source_payload.owner_id : "");
    while (currentOwnerId && !visitedOwnerIds.has(currentOwnerId)) {
      visitedOwnerIds.add(currentOwnerId);
      ownerChainIds.unshift(currentOwnerId);
      const loadedOwner = findNodeById(treeNodesRef.current, currentOwnerId);
      if (loadedOwner) {
        break;
      }
      try {
        const ownerDetails = await api.getItem(
          currentOwnerId,
          selectedProjectId,
          selectedBranchId,
          selectedProject?.workspace_id || undefined,
          false,
          typeof item.source_payload.model_id === "string" ? item.source_payload.model_id : undefined,
        );
        currentOwnerId = ownerDetails.owner?.id || (typeof ownerDetails.source_payload.owner_id === "string" ? ownerDetails.source_payload.owner_id : "");
      } catch {
        break;
      }
    }
    const pathIds = [...new Set([...ownerChainIds, item.id])];
    if (!pathIds.length) {
      return;
    }
    const nextExpanded = new Set(expandedTreeNodeIds);
    for (let index = 0; index < pathIds.length - 1; index += 1) {
      const parentId = pathIds[index];
      let parentNode = findNodeById(treeNodesRef.current, parentId);
      if (!parentNode) {
        break;
      }
      nextExpanded.add(parentNode.id);
      const childrenLoaded = parentNode.children.length > 0 || parentNode.metadata.children_loaded === true;
      if (!childrenLoaded) {
        await loadTreeChildren(parentNode);
        parentNode = findNodeById(treeNodesRef.current, parentId);
        if (!parentNode) {
          break;
        }
      }
    }
    setExpandedTreeNodeIds(Array.from(nextExpanded));
    setSelectedItemId(item.id);
    setTab("models");
    if (!findNodeById(treeNodesRef.current, item.id)) {
      setNotice({ severity: "warning", message: "Workbench selected the item, but its containment parents are not loaded in the current tree yet. Expand its parent package or search for the item to reveal it." });
    }
  };

  const navigateToSpecificationElement = async (elementId: string, modelId?: string) => {
    const cleanElementId = elementId.trim();
    if (!cleanElementId || !selectedProjectId || !selectedBranchId) {
      return;
    }
    setSelectedItemId(cleanElementId);
    setTab("models");
    try {
      const targetDetails = await api.getItem(
        cleanElementId,
        selectedProjectId,
        selectedBranchId,
        selectedProject?.workspace_id || undefined,
        false,
        modelId,
      );
      await revealElementPathInTree(targetDetails);
    } catch {
      setNotice({
        severity: "warning",
        message: "Workbench selected the referenced item, but could not fully reveal it in the current containment tree yet.",
      });
    }
  };

  const revealSelectedInTree = () => {
    if (!selectedItemId) {
      return;
    }
    void revealElementPathInTree(selectedSearchWorkspaceItem);
  };

  const openDiagramViewer = () => {
    if (!selectedWorkspaceItemDiagramPreviewUrl && !selectedWorkspaceItemIsDiagram) {
      return;
    }
    setTab("diagram-viewer");
  };

  const openDiagramDetails = () => {
    if (!selectedWorkspaceItemIsDiagram) {
      return;
    }
    setSelectedSpecificationSection("properties");
    setTab("models");
  };

  const beginHorizontalResize = (
    event: ReactMouseEvent,
    startWidth: number,
    setWidth: (next: number) => void,
    minimum: number,
    maximum: number,
    direction: "grow-right" | "grow-left" = "grow-right",
  ) => {
    event.preventDefault();
    const originX = event.clientX;
    const handleMove = (moveEvent: MouseEvent) => {
      const delta = moveEvent.clientX - originX;
      const nextWidth =
        direction === "grow-left"
          ? clampNumber(startWidth - delta, minimum, maximum)
          : clampNumber(startWidth + delta, minimum, maximum);
      setWidth(nextWidth);
    };
    const handleUp = () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
  };

  const loadTreeChildren = async (node: TreeNode) => {
    if (!selectedProjectId || !selectedBranchId) {
      return;
    }
    if (loadingTreeNodeIds.includes(node.id)) {
      return;
    }
    const modelId = typeof node.metadata.model_id === "string" ? node.metadata.model_id : undefined;
    setLoadingTreeNodeIds((current) => [...current, node.id]);
    try {
      const children = await api.getTreeChildren(
        selectedProjectId,
        selectedBranchId,
        node.id,
        modelId,
        selectedProject?.workspace_id || undefined,
      );
      setTreeNodes((current) => {
        const nextTree = replaceNodeChildren(current, node.id, children);
        treeNodesRef.current = nextTree;
        return nextTree;
      });
    } catch (caught) {
      setNotice({ severity: "error", message: errorMessage(caught) });
    } finally {
      setLoadingTreeNodeIds((current) => current.filter((value) => value !== node.id));
    }
  };

  const sendWorkbenchAgentPrompt = () => {
    const prompt = agentChatInput.trim();
    if (!prompt) {
      return;
    }
    const nextMessages: WorkbenchAgentChatMessage[] = [
      ...agentMessages,
      {
        role: "user",
        content: prompt,
      },
    ];
    setAgentMessages(nextMessages);
    setAgentChatInput("");
    workbenchAgentChatMutation.mutate({
      messages: nextMessages,
      syncKnowledge: agentSyncKnowledgeBeforeChat,
    });
  };

  const renderSpecificationTable = (rows: InspectorRow[], emptyText: string) =>
    rows.length ? (
      <Paper variant="outlined" sx={{ borderRadius: 2, overflow: "hidden" }}>
        {rows.map((row, index) => (
          <Box
            key={row.key}
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "1fr",
                sm: compactUi ? "180px minmax(0, 1fr)" : "220px minmax(0, 1fr)",
              },
              gap: 1.5,
              px: compactUi ? 1.5 : 2,
              py: compactUi ? 1 : 1.25,
              borderTop: index ? "1px solid" : "none",
              borderColor: "divider",
              alignItems: "start",
            }}
          >
            <Typography variant="body2" fontWeight={600} color="text.secondary">
              {row.label}
            </Typography>
            <Box sx={{ minWidth: 0, "& .MuiButton-root": { maxWidth: "100%" } }}>
              {row.rawValue !== undefined ? (
                renderSpecificationValue(row.rawValue)
              ) : (
                <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {row.value}
                </Typography>
              )}
            </Box>
          </Box>
        ))}
      </Paper>
    ) : (
      <Typography color="text.secondary">{emptyText}</Typography>
    );

  const renderReferenceList = (
    references: ItemReference[],
    emptyText: string,
    options?: {
      inlineTypeOnly?: boolean;
    },
  ) =>
    references.length ? (
      <List dense disablePadding sx={{ maxHeight: 320, overflow: "auto" }}>
        {references.map((reference) => (
          <ListItemButton key={`${reference.relationship_type}-${reference.id}`} dense onClick={() => openElementId(reference.id)}>
            <ListItemText
              primary={
                options?.inlineTypeOnly
                  ? `${itemReferenceDisplayName(reference, referenceNameById)} · ${itemReferenceTypeLabel(reference)}`
                  : itemReferenceDisplayName(reference, referenceNameById)
              }
              secondary={
                options?.inlineTypeOnly
                  ? undefined
                  : `${humanizeFieldLabel(reference.relationship_type)}${itemReferenceSecondaryText(reference, referenceNameById) ? ` · ${itemReferenceSecondaryText(reference, referenceNameById)}` : ""}`
              }
            />
          </ListItemButton>
        ))}
      </List>
    ) : (
      <Typography color="text.secondary">{emptyText}</Typography>
    );

  const renderReferenceTable = (
    references: ItemReference[],
    emptyText: string,
    options?: {
      secondaryColumnLabel?: string;
      secondaryColumn?: (reference: ItemReference) => string;
    },
  ) =>
    references.length ? (
      <Paper variant="outlined" sx={{ borderRadius: 2, overflow: "hidden" }}>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "minmax(0, 1fr)",
              sm: compactUi ? "minmax(0, 1.2fr) minmax(160px, 0.8fr)" : "minmax(0, 1.3fr) minmax(180px, 0.7fr)",
            },
            gap: 1.5,
            px: compactUi ? 1.5 : 2,
            py: compactUi ? 1 : 1.25,
            bgcolor: "action.hover",
          }}
        >
          <Typography variant="body2" fontWeight={600} color="text.secondary">
            Name
          </Typography>
          <Typography variant="body2" fontWeight={600} color="text.secondary">
            {options?.secondaryColumnLabel ?? "Type"}
          </Typography>
        </Box>
        {references.map((reference, index) => (
          <Box
            key={`${reference.relationship_type}:${reference.id}`}
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: "minmax(0, 1fr)",
                sm: compactUi ? "minmax(0, 1.2fr) minmax(160px, 0.8fr)" : "minmax(0, 1.3fr) minmax(180px, 0.7fr)",
              },
              gap: 1.5,
              px: compactUi ? 1.5 : 2,
              py: compactUi ? 1 : 1.25,
              borderTop: "1px solid",
              borderColor: "divider",
              alignItems: "start",
            }}
          >
            <Button
              variant="text"
              sx={{ justifyContent: "flex-start", px: 0, minWidth: 0, textTransform: "none", fontWeight: 500 }}
              onClick={() => openElementId(reference.id)}
            >
              {itemReferenceDisplayName(reference, referenceNameById)}
            </Button>
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {(options?.secondaryColumn?.(reference) ?? itemReferenceTypeLabel(reference)) || ""}
            </Typography>
          </Box>
        ))}
      </Paper>
    ) : (
      <Typography color="text.secondary">{emptyText}</Typography>
    );

  const renderDataTable = (
    headers: string[],
    rows: DataTableRow[],
    emptyText: string,
    options?: {
      columnTemplate?: { xs: string; sm: string };
    },
  ) =>
    rows.length ? (
      <Paper variant="outlined" sx={{ borderRadius: 2, overflow: "hidden" }}>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: options?.columnTemplate?.xs ?? "minmax(0, 1fr)",
              sm: options?.columnTemplate?.sm ?? `repeat(${headers.length}, minmax(0, 1fr))`,
            },
            gap: 1.5,
            px: compactUi ? 1.5 : 2,
            py: compactUi ? 1 : 1.25,
            bgcolor: "action.hover",
          }}
        >
          {headers.map((header) => (
            <Typography key={header} variant="body2" fontWeight={600} color="text.secondary">
              {header}
            </Typography>
          ))}
        </Box>
        {rows.map((row) => (
          <Box
            key={row.key}
            sx={{
              display: "grid",
              gridTemplateColumns: {
                xs: options?.columnTemplate?.xs ?? "minmax(0, 1fr)",
                sm: options?.columnTemplate?.sm ?? `repeat(${headers.length}, minmax(0, 1fr))`,
              },
              gap: 1.5,
              px: compactUi ? 1.5 : 2,
              py: compactUi ? 1 : 1.25,
              borderTop: "1px solid",
              borderColor: "divider",
              alignItems: "start",
            }}
          >
            {row.cells.map((cell, index) => {
              const targetId = row.targetIds?.[index];
              const indentLevel = row.indentCells?.[index] ?? 0;
              const indentSx = indentLevel ? { ml: `${indentLevel * 1.4}rem` } : {};
              if (targetId && (typeof cell === "string" || typeof cell === "number")) {
                return (
                  <Button
                    key={`${row.key}-${index}`}
                    size="small"
                    variant="text"
                    sx={{ justifyContent: "flex-start", minWidth: 0, px: 0.5, py: 0, textTransform: "none", textAlign: "left", ...indentSx }}
                    onClick={() => void navigateToSpecificationElement(targetId)}
                  >
                    {cell || ""}
                  </Button>
                );
              }
              return typeof cell === "string" || typeof cell === "number" ? (
                <Typography key={`${row.key}-${index}`} variant="body2" sx={{ whiteSpace: "pre-wrap", wordBreak: "break-word", ...indentSx }}>
                  {cell || ""}
                </Typography>
              ) : (
                <Box key={`${row.key}-${index}`} sx={{ minWidth: 0, ...indentSx, "& .MuiButton-root": { maxWidth: "100%" } }}>
                  {cell || ""}
                </Box>
              );
            })}
          </Box>
        ))}
      </Paper>
    ) : (
      <Typography color="text.secondary">{emptyText}</Typography>
    );

  const renderSpecificationValue = (value: unknown): ReactNode => {
    if (!hasMeaningfulValue(value)) {
      return "";
    }
    if (Array.isArray(value)) {
      return (
        <Stack spacing={0.5} alignItems="flex-start">
          {value.map((entry, index) => (
            <Box key={`spec-value-${index}`} sx={{ minWidth: 0 }}>
              {renderSpecificationValue(entry)}
            </Box>
          ))}
        </Stack>
      );
    }
    if (value && typeof value === "object") {
      const record = value as Record<string, unknown>;
      const id = typeof record.id === "string" ? record.id.trim() : "";
      const modelId = typeof record.model_id === "string"
        ? record.model_id.trim()
        : typeof record.modelId === "string"
          ? record.modelId.trim()
          : undefined;
      const display = [
        record.qualifiedName,
        record.qualified_name,
        record.human_name,
        record.humanName,
        record.name,
        record.label,
        record.title,
        id,
      ]
        .map((candidate) => (typeof candidate === "string" ? candidate.trim() : ""))
        .find(Boolean);
      if (id) {
        return (
          <Button
            size="small"
            variant="text"
            sx={{ justifyContent: "flex-start", minWidth: 0, px: 0.5, py: 0, textTransform: "none", textAlign: "left" }}
            onClick={() => void navigateToSpecificationElement(id, modelId)}
          >
            {humanReadableReference(display || id, referenceNameById)}
          </Button>
        );
      }
      return (
        <Typography component="span" variant="body2" sx={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
          {humanReadableValue(value, referenceNameById)}
        </Typography>
      );
    }
    if (typeof value === "string") {
      const id = value.trim();
      if (id && isOpaqueIdentifier(id)) {
        return (
          <Button
            size="small"
            variant="text"
            sx={{ justifyContent: "flex-start", minWidth: 0, px: 0.5, py: 0, textTransform: "none", textAlign: "left" }}
            onClick={() => void navigateToSpecificationElement(id)}
          >
            {humanReadableReference(id, referenceNameById)}
          </Button>
        );
      }
    }
    return humanReadableValue(value, referenceNameById);
  };

  const renderTextBlocks = (blocks: string[], emptyText: string) =>
    blocks.length ? (
      <Paper variant="outlined" sx={{ borderRadius: 2, overflow: "hidden" }}>
        {blocks.map((block, index) => (
          <Box
            key={`${index}-${block.slice(0, 32)}`}
            sx={{
              px: compactUi ? 1.5 : 2,
              py: compactUi ? 1 : 1.25,
              borderTop: index ? "1px solid" : "none",
              borderColor: "divider",
            }}
          >
            <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {block}
            </Typography>
          </Box>
        ))}
      </Paper>
    ) : (
      <Typography color="text.secondary">{emptyText}</Typography>
    );

  const renderSpecificationWorkspace = (
    item: ItemDetails,
    options: {
      mode: "browser" | "details";
      editable: boolean;
      extraHeader?: ReactNode;
    },
  ) => {
    const sourcePayload = item.source_payload ?? {};
    const propertiesRows = specificationWindowRows(item, referenceNameById, itemDetailViewMode);
    const nativeMetamodelEntries = payloadNativeMetamodelEntries(item);
    const nativePropertyRows: DataTableRow[] = nativeMetamodelEntries.map((entry, index) => {
      const value = hasMeaningfulValue(entry.value) ? entry.value : entry.defaultValue;
      const targetId = firstReferencedElementId(value);
      return {
        key: `native-property-${String(entry.id ?? index)}`,
        targetIds: targetId ? { 1: targetId } : undefined,
        cells: [
          String(entry.name ?? entry.id ?? "Property"),
          hasMeaningfulValue(entry.value)
            ? renderSpecificationValue(entry.value)
            : hasMeaningfulValue(entry.defaultValue)
              ? renderSpecificationValue(entry.defaultValue)
              : "",
          String(entry.valueType ?? entry.kind ?? ""),
          nativeSpecificationState(entry),
        ],
      };
    });
    const nativeStereotypeRows: DataTableRow[] = payloadNativeStereotypeSections(item).flatMap((section, sectionIndex) => {
      const entries = Array.isArray(section.entries)
        ? section.entries.filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === "object" && !Array.isArray(entry))
        : [];
      return entries.map((entry, entryIndex) => ({
        key: `native-stereotype-${String(section.id ?? sectionIndex)}-${String(entry.id ?? entryIndex)}`,
        targetIds: firstReferencedElementId(hasMeaningfulValue(entry.value) ? entry.value : entry.defaultValue)
          ? { 2: firstReferencedElementId(hasMeaningfulValue(entry.value) ? entry.value : entry.defaultValue) }
          : undefined,
        cells: [
          String(section.name ?? entry.stereotypeName ?? "Stereotype"),
          String(entry.name ?? entry.id ?? "Property"),
          hasMeaningfulValue(entry.value)
            ? renderSpecificationValue(entry.value)
            : hasMeaningfulValue(entry.defaultValue)
              ? renderSpecificationValue(entry.defaultValue)
              : "",
          String(entry.valueType ?? ""),
          nativeSpecificationState(entry),
        ],
      }));
    });
    const documentationSections = extractDocumentationSections(item);
    const structuredNavigationRows = payloadSpecSectionEntries(item, "navigation").map((entry, index) => ({
      key: `navigation-${index}`,
      cells: [
        structuredEntryName(entry),
        structuredEntryValue(entry, ["type"], referenceNameById),
        structuredEntryValue(entry, ["value", "target"], referenceNameById),
      ],
    }));
    const structuredUsageRows = payloadSpecSectionEntries(item, "usage-diagrams").map((entry, index) => ({
      key: `usage-${index}`,
      cells: [
        structuredEntryValue(entry, ["value", "target"], referenceNameById) || structuredEntryName(entry),
        structuredEntryValue(entry, ["type"], referenceNameById) || "Diagram",
      ],
    }));
    const structuredInnerElementRows = payloadSpecSectionEntries(item, "inner-elements").map((entry, index) => ({
      key: `inner-${index}`,
      cells: [
        structuredEntryValue(entry, ["value", "target"], referenceNameById) || structuredEntryName(entry),
        structuredEntryValue(entry, ["type"], referenceNameById) || "Owned Element",
      ],
    }));
    const structuredRelationRows = payloadSpecSectionEntries(item, "relations").map((entry, index) => ({
      key: `relation-${index}`,
      cells: [
        structuredEntryName(entry),
        structuredEntryValue(entry, ["element"], referenceNameById),
        structuredEntryValue(entry, ["direction"], referenceNameById),
        structuredEntryValue(entry, ["relatedElement", "value", "target"], referenceNameById),
      ],
    }));
    const structuredTagRows = payloadSpecSectionEntries(item, "tags").map((entry, index) => ({
      key: `tag-${index}`,
      cells: [structuredEntryName(entry), structuredEntryValue(entry, ["value"], referenceNameById)],
    }));
    const structuredConstraintRows = payloadSpecSectionEntries(item, "constraints").map((entry, index) => ({
      key: `constraint-${index}`,
      cells: [structuredEntryName(entry), structuredEntryValue(entry, ["specification", "value"], referenceNameById)],
    }));
    const structuredTraceabilityRows = payloadSpecSectionEntries(item, "traceability").map((entry, index) => ({
      key: `trace-${index}`,
      cells: [structuredEntryName(entry), structuredEntryValue(entry, ["value", "target"], referenceNameById)],
    }));
    const structuredAllocationRows = payloadSpecSectionEntries(item, "allocations").map((entry, index) => ({
      key: `allocation-${index}`,
      cells: [structuredEntryName(entry), structuredEntryValue(entry, ["value", "target"], referenceNameById)],
    }));
    const navigationRows = collectHintRows(item, referenceNameById, NAVIGATION_FIELD_HINTS, {
      includeMetadata: true,
      inlineOnly: false,
    });
    const nativeNavigationRows = nativeReferenceRowsForHints(item, referenceNameById, NAVIGATION_FIELD_HINTS, { defaultType: "Navigation" }).map((row) => ({
      key: `navigation-${row.key}`,
      targetIds: row.targetIds?.[1] ? { 2: row.targetIds[1] } : undefined,
      cells: [row.cells[0], row.cells[2], row.cells[1]],
    }));
    const diagramUsageReferences = collectReferenceMatches(item, ["diagram", "symbol", "usage"]);
    const nativeUsageRows = nativeReferenceRowsForHints(item, referenceNameById, ["diagram", "symbol", "usage"], { defaultType: "Diagram" }).map((row) => ({
      key: `usage-${row.key}`,
      targetIds: row.targetIds?.[1] ? { 0: row.targetIds[1] } : undefined,
      cells: [row.cells[1], row.cells[0]],
    }));
    const nativeInnerRows = nativeReferenceRowsForHints(item, referenceNameById, ["owned", "inner", "diagramElement", "element"], {
      defaultType: "Element",
    }).map((row) => ({
      key: `inner-${row.key}`,
      targetIds: row.targetIds?.[1] ? { 0: row.targetIds[1] } : undefined,
      cells: [row.cells[1], row.cells[0]],
    }));
    const navigationTableRows = hintRowsToTableRows(navigationRows);
    const relationRows = relationshipTableRows(item, referenceNameById);
    const combineDataRows = (...groups: DataTableRow[][]): DataTableRow[] => {
      const seen = new Set<string>();
      return groups.flat().filter((row) => {
        const key = `${row.key}:${row.cells.map((cell) => String(cell)).join("::")}`;
        if (seen.has(key)) {
          return false;
        }
        seen.add(key);
        return true;
      });
    };
    const nativeRowsForHints = (
      sectionKey: string,
      hints: string[],
      options?: { includeUnset?: boolean; onlyReferences?: boolean },
    ): DataTableRow[] =>
      nativeMetamodelEntries
        .filter((entry) => {
          const entryName = String(entry.name ?? entry.id ?? "");
          const value = hasMeaningfulValue(entry.value) ? entry.value : entry.defaultValue;
          if (!keyMatchesHints(entryName, hints)) {
            return false;
          }
          if (options?.onlyReferences && String(entry.kind ?? "").toLowerCase() !== "reference") {
            return false;
          }
          return options?.includeUnset || hasMeaningfulValue(value);
        })
        .map((entry, index) => {
          const value = hasMeaningfulValue(entry.value) ? entry.value : entry.defaultValue;
          const targetId = firstReferencedElementId(value);
          return {
            key: `${sectionKey}-${String(entry.id ?? index)}`,
            targetIds: targetId ? { 1: targetId } : undefined,
            cells: [
              String(entry.name ?? entry.id ?? "Property"),
              hasMeaningfulValue(value) ? renderSpecificationValue(value) : "",
              String(entry.valueType ?? entry.kind ?? ""),
              nativeSpecificationState(entry),
            ],
          };
        });
    const nativeSectionTable = (rows: DataTableRow[], emptyText: string) =>
      renderDataTable(["Property", "Value", "Type", "State"], rows, emptyText, {
        columnTemplate: {
          xs: "minmax(0, 1fr)",
          sm: "minmax(180px, 0.8fr) minmax(0, 1.4fr) minmax(130px, 0.55fr) minmax(150px, 0.65fr)",
        },
      });
    const usageInRows = combineDataRows(
      nativeRowsForHints("usage-in", ["used", "usage", "typedElement", "classifier", "member", "use"], { onlyReferences: true }),
      referenceRowsToTableRows(collectReferenceMatches(item, ["used", "usage", "typed", "classifier", "member"]), referenceNameById).map((row) => ({
        key: `usage-in-${row.key}`,
        targetIds: row.targetIds?.[0] ? { 1: row.targetIds[0] } : undefined,
        cells: [row.cells[1] ?? "Reference", row.cells[0] ?? "Referenced item", "Reference", "set"],
      })),
    );
    const portsInterfaceRows = nativeRowsForHints("ports-interfaces", ["port", "interface", "provided", "required", "connector"], {
      includeUnset: itemDetailViewMode === "all",
    });
    const elementPropertyRows = nativeRowsForHints("element-properties", ["property", "ownedAttribute", "attribute", "part", "role", "member"], {
      includeUnset: itemDetailViewMode === "all",
    });
    const attributeRows = nativeRowsForHints("attributes", ["attribute", "ownedAttribute"], { includeUnset: itemDetailViewMode === "all" });
    const portRows = nativeRowsForHints("ports", ["port"], { includeUnset: itemDetailViewMode === "all" });
    const operationRows = nativeRowsForHints("operations", ["operation"], { includeUnset: itemDetailViewMode === "all" });
    const receptionRows = nativeRowsForHints("receptions", ["reception"], { includeUnset: itemDetailViewMode === "all" });
    const behaviorRows = nativeRowsForHints("behaviors", ["behavior", "activity", "stateMachine", "interaction"], { includeUnset: itemDetailViewMode === "all" });
    const templateParameterRows = nativeRowsForHints("template-parameters", ["template", "parameter"], { includeUnset: itemDetailViewMode === "all" });
    const instanceRows = nativeRowsForHints("instances", ["instance", "slot"], { includeUnset: itemDetailViewMode === "all" });
    const usageDiagramRows = combineDataRows(
      structuredUsageRows,
      referenceRowsToTableRows(diagramUsageReferences, referenceNameById),
      nativeUsageRows,
    );
    const innerElementRows = combineDataRows(
      structuredInnerElementRows,
      referenceRowsToTableRows(item.contained_elements, referenceNameById),
      nativeInnerRows,
    );
    const directInnerElementTreeNodes: TreeNode[] = item.contained_elements.map((reference) => ({
      id: reference.id,
      label: itemReferenceDisplayName(reference, referenceNameById),
      node_type: reference.item_type || reference.relationship_type || "element",
      path: reference.path,
      children: [],
      metadata: {
        project_id: item.project_id,
        branch_id: item.branch_id,
        model_id: selectedPermissionModelId,
        qualified_name: reference.path,
        metaclass: reference.item_type || reference.relationship_type || "Element",
        child_count: 0,
        children_loaded: true,
      },
    }));
    const fallbackInnerElementTreeNodes = directInnerElementTreeNodes.length
      ? directInnerElementTreeNodes
      : innerElementRows
        .filter((row) => Boolean(row.targetIds?.[0]))
        .map((row, index) => {
          const targetId = row.targetIds?.[0] ?? `inner-element-row-${index}`;
          const label = String(row.cells[0] ?? "").trim() || `Inner Element ${index + 1}`;
          const typeLabel = String(row.cells[1] ?? "").trim() || "Element";
          return {
            id: targetId,
            label,
            node_type: typeLabel,
            path: label,
            children: [],
            metadata: {
              project_id: item.project_id,
              branch_id: item.branch_id,
              model_id: selectedPermissionModelId,
              qualified_name: label,
              metaclass: typeLabel,
              child_count: 0,
              children_loaded: true,
            },
          };
        });
    const displayedInnerElementTreeNodes =
      options.mode === "browser" && item.id === selectedItemId && selectedInnerElementTreeQuery.data?.length
        ? selectedInnerElementTreeQuery.data
        : fallbackInnerElementTreeNodes;
    const nativeRelationRows = nativeReferenceRowsForHints(item, referenceNameById, ["owner", "owned", "supplier", "client", "relationship", "relation", "dependency", "element"], {
      defaultType: "Reference",
    }).map((row) => ({
      key: `relation-${row.key}`,
      targetIds: row.targetIds?.[1] ? { 3: row.targetIds[1] } : undefined,
      cells: [row.cells[0], displayEntityName(item.name, item.id, item.item_type, referenceNameById, item.path), "Related", row.cells[1]],
    }));
    const combinedRelationRows = combineDataRows(structuredRelationRows, relationRows, nativeRelationRows);
    const tagRows = dedupeInspectorRows([
      ...(item.stereotypes.length
        ? [
            {
              key: "stereotypes",
              label: "Applied Stereotypes",
              value: item.stereotypes.join(", "),
            },
          ]
        : []),
      ...collectHintRows(item, referenceNameById, TAG_FIELD_HINTS, {
        includeMetadata: true,
        inlineOnly: false,
      }),
      ...mapInlineInspectorRows(item.metadata ?? {}, referenceNameById).filter((row) => keyMatchesHints(row.key, TAG_FIELD_HINTS)),
    ]);
    const tagTableRows = hintRowsToTableRows(tagRows);
    const combinedTagRows = combineDataRows(structuredTagRows, tagTableRows, nativeStereotypeTagRows(item, referenceNameById));
    const constraintSectionRows = constraintRows(item, referenceNameById);
    const constraintLinkedItems = constraintReferenceItems(item);
    const constraintTableRows = hintRowsToTableRows(constraintSectionRows);
    const traceabilityRows = collectHintRows(item, referenceNameById, TRACEABILITY_FIELD_HINTS, {
      includeMetadata: true,
      inlineOnly: false,
    });
    const traceabilityReferences = collectReferenceMatches(item, TRACEABILITY_FIELD_HINTS);
    const nativeTraceabilityRows = nativeReferenceRowsForHints(item, referenceNameById, TRACEABILITY_FIELD_HINTS, { includeUnset: true, defaultType: "Traceability" }).map((row) => ({
      key: `trace-${row.key}`,
      targetIds: row.targetIds?.[1] ? { 1: row.targetIds[1] } : undefined,
      cells: [row.cells[0], row.cells[1]],
    }));
    const traceabilityTableRows = [
      ...hintRowsToTableRows(traceabilityRows),
      ...referenceRowsToTableRows(traceabilityReferences, referenceNameById),
      ...nativeTraceabilityRows,
    ];
    const combinedTraceabilityRows = combineDataRows(structuredTraceabilityRows, traceabilityTableRows);
    const allocationRows = collectHintRows(item, referenceNameById, ALLOCATION_FIELD_HINTS, {
      includeMetadata: true,
      inlineOnly: false,
    });
    const allocationReferences = collectReferenceMatches(item, ALLOCATION_FIELD_HINTS);
    const nativeAllocationRows = nativeReferenceRowsForHints(item, referenceNameById, ALLOCATION_FIELD_HINTS, { includeUnset: true, defaultType: "Allocation" }).map((row) => ({
      key: `allocation-${row.key}`,
      targetIds: row.targetIds?.[1] ? { 1: row.targetIds[1] } : undefined,
      cells: [row.cells[0], row.cells[1]],
    }));
    const allocationTableRows = [
      ...hintRowsToTableRows(allocationRows),
      ...referenceRowsToTableRows(allocationReferences, referenceNameById),
      ...nativeAllocationRows,
    ];
    const combinedAllocationRows = combineDataRows(structuredAllocationRows, allocationTableRows);
    const specificationChildSections = specificationChildSectionsForItem(item);
    const selectedSectionTitle =
      selectedSpecificationSection === "properties"
        ? displayEntityName(item.name, item.id, item.item_type, referenceNameById, item.path)
        : SPECIFICATION_SECTION_LABELS[selectedSpecificationSection];

    const renderSelectedSectionContent = () => {
      switch (selectedSpecificationSection) {
        case "properties":
          return (
            <Stack spacing={2}>
              {options.editable ? (
                <Paper variant="outlined" sx={{ p: compactUi ? 1.5 : 2, borderRadius: 2 }}>
                  <Stack spacing={1.5}>
                    <Typography variant="subtitle2">Editable Fields</Typography>
                    <TextField label="Path" value={friendlyPath(item.path, referenceNameById)} disabled fullWidth />
                    <TextField
                      label="Name"
                      value={item.name}
                      disabled={!options.editable}
                      onChange={(event) => setItemDraft((current) => (current ? { ...current, name: event.target.value } : current))}
                      fullWidth
                    />
                    <TextField
                      label="Description"
                      value={item.description}
                      disabled={!options.editable}
                      onChange={(event) => setItemDraft((current) => (current ? { ...current, description: event.target.value } : current))}
                      fullWidth
                      multiline
                      minRows={3}
                    />
                  </Stack>
                </Paper>
              ) : null}
              {renderSpecificationTable(propertiesRows, "No published properties were returned for this item.")}
              {itemDetailViewMode === "all" && !isPackageLikeItemType(item.item_type) && nativePropertyRows.length ? (
                <Stack spacing={1}>
                  <Typography variant="subtitle2">All Cameo Properties</Typography>
                  {renderDataTable(
                    ["Property", "Value", "Type", "State"],
                    nativePropertyRows,
                    "No native Cameo metamodel properties were published for this item.",
                    {
                      columnTemplate: {
                        xs: "minmax(0, 1fr)",
                        sm: "minmax(180px, 0.8fr) minmax(0, 1.4fr) minmax(130px, 0.55fr) minmax(150px, 0.65fr)",
                      },
                    },
                  )}
                </Stack>
              ) : null}
              {itemDetailViewMode === "all" && !isPackageLikeItemType(item.item_type) && nativeStereotypeRows.length ? (
                <Stack spacing={1}>
                  <Typography variant="subtitle2">Stereotype Properties</Typography>
                  {renderDataTable(
                    ["Stereotype", "Property", "Value", "Type", "State"],
                    nativeStereotypeRows,
                    "No applied stereotype properties were published for this item.",
                    {
                      columnTemplate: {
                        xs: "minmax(0, 1fr)",
                        sm: "minmax(140px, 0.65fr) minmax(160px, 0.75fr) minmax(0, 1.3fr) minmax(120px, 0.55fr) minmax(140px, 0.65fr)",
                      },
                    },
                  )}
                </Stack>
              ) : null}
            </Stack>
          );
        case "documentation": {
          const hasDocumentation = documentationSections.documentation.length > 0;
          const hasComments = documentationSections.comments.length > 0;
          return (
            <Stack spacing={2}>
              <Paper variant="outlined" sx={{ p: compactUi ? 1.5 : 2, borderRadius: 2 }}>
                <Stack spacing={1}>
                  <Typography variant="subtitle2">Documentation</Typography>
                  {renderTextBlocks(documentationSections.documentation, "No documentation was published for this item.")}
                </Stack>
              </Paper>
              <Paper variant="outlined" sx={{ p: compactUi ? 1.5 : 2, borderRadius: 2 }}>
                <Stack spacing={1}>
                  <Typography variant="subtitle2">Comments</Typography>
                  {renderTextBlocks(documentationSections.comments, hasDocumentation ? "No comments were published for this item." : "No documentation or comments were published for this item.")}
                </Stack>
              </Paper>
            </Stack>
          );
        }
        case "navigation":
          return renderDataTable(
            ["Name", "Type", "Value"],
            combineDataRows(structuredNavigationRows, nativeNavigationRows, navigationTableRows.map((row) => ({ key: row.key, cells: [row.cells[0], "Navigation", row.cells[1]] }))),
            "No navigation targets or hyperlinks were published for this item.",
            {
              columnTemplate: {
                xs: "minmax(0, 1fr)",
                sm: "minmax(180px, 0.75fr) minmax(160px, 0.55fr) minmax(0, 1.2fr)",
              },
            },
          );
        case "usage-diagrams":
          return usageDiagramRows.length
            ? renderDataTable(["Name", "Type"], usageDiagramRows, "No diagram usage references were published for this item.", {
                columnTemplate: {
                  xs: "minmax(0, 1fr)",
                  sm: "minmax(0, 1.2fr) minmax(160px, 0.8fr)",
                },
              })
            : renderReferenceTable(diagramUsageReferences, "No diagram usage references were published for this item.");
        case "usage-in":
          return nativeSectionTable(usageInRows, "No usage-in references were published for this item.");
        case "ports-interfaces":
          return nativeSectionTable(portsInterfaceRows, "No ports or interface properties were published for this item.");
        case "element-properties":
          return nativeSectionTable(elementPropertyRows.length ? elementPropertyRows : nativePropertyRows, "No properties were published for this item.");
        case "attributes":
          return nativeSectionTable(attributeRows, "No attributes were published for this item.");
        case "ports":
          return nativeSectionTable(portRows, "No ports were published for this item.");
        case "operations":
          return nativeSectionTable(operationRows, "No operations were published for this item.");
        case "receptions":
          return nativeSectionTable(receptionRows, "No receptions were published for this item.");
        case "behaviors":
          return nativeSectionTable(behaviorRows, "No behaviors were published for this item.");
        case "inner-elements":
          return (
            <Stack spacing={1.5}>
              {selectedInnerElementTreeQuery.isFetching && options.mode === "browser" && item.id === selectedItemId ? (
                <Stack direction="row" spacing={1} alignItems="center">
                  <CircularProgress size={16} />
                  <Typography variant="body2" color="text.secondary">
                    Loading nested Inner Elements...
                  </Typography>
                </Stack>
              ) : null}
              {displayedInnerElementTreeNodes.length ? (
                <Paper variant="outlined" sx={{ p: compactUi ? 1 : 1.25, borderRadius: 2 }}>
                  <ProjectTree
                    nodes={displayedInnerElementTreeNodes}
                    selectedId={selectedItemId}
                    filter=""
                    expandedIds={expandedInnerElementNodeIds}
                    onExpandedChange={setExpandedInnerElementNodeIds}
                    onSelect={(node) => {
                      const modelId = typeof node.metadata.model_id === "string" ? node.metadata.model_id : undefined;
                      void navigateToSpecificationElement(node.id, modelId);
                    }}
                    showFullTypes
                  />
                </Paper>
              ) : (
                <Typography color="text.secondary">No contained elements were published for this item.</Typography>
              )}
            </Stack>
          );
        case "relations":
          return renderDataTable(["Name", "Element", "Direction", "Related Element"], combinedRelationRows, "No relationships were published for this item.", {
            columnTemplate: {
              xs: "minmax(0, 1fr)",
              sm: "minmax(150px, 0.9fr) minmax(180px, 1fr) minmax(120px, 0.6fr) minmax(180px, 1fr)",
            },
          });
        case "tags":
          return renderDataTable(["Tag", "Value"], combinedTagRows, "No tags or stereotypes were published for this item.", {
            columnTemplate: {
              xs: "minmax(0, 1fr)",
              sm: "minmax(180px, 0.8fr) minmax(0, 1.2fr)",
            },
          });
        case "constraints":
          return (
            <Stack spacing={2}>
              {renderDataTable(["Name", "Specification"], structuredConstraintRows.length ? structuredConstraintRows : constraintTableRows, "No constraints were published for this item.", {
                columnTemplate: {
                  xs: "minmax(0, 1fr)",
                  sm: "minmax(180px, 0.8fr) minmax(0, 1.2fr)",
                },
              })}
              {constraintLinkedItems.length ? renderReferenceTable(constraintLinkedItems, "No constraint-linked elements were published for this item.") : null}
            </Stack>
          );
        case "traceability":
          return renderDataTable(["Name", "Value"], combinedTraceabilityRows, "No traceability properties were published for this item.", {
            columnTemplate: {
              xs: "minmax(0, 1fr)",
              sm: "minmax(180px, 0.8fr) minmax(0, 1.2fr)",
            },
          });
        case "allocations":
          return renderDataTable(["Name", "Value"], combinedAllocationRows, "No allocation properties were published for this item.", {
            columnTemplate: {
              xs: "minmax(0, 1fr)",
              sm: "minmax(180px, 0.8fr) minmax(0, 1.2fr)",
            },
          });
        case "template-parameters":
          return nativeSectionTable(templateParameterRows, "No template parameters were published for this item.");
        case "instances":
          return nativeSectionTable(instanceRows, "No instances were published for this item.");
        default:
          return null;
      }
    };

    return (
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", lg: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", lg: "center" }}>
          <Stack spacing={0.75}>
            <Typography variant="h6">{displayEntityName(item.name, item.id, item.item_type, referenceNameById, item.path)}</Typography>
            <Typography variant="body2" color="text.secondary">
              {friendlyPath(item.path, referenceNameById) || `${selectedProject?.name ?? "Project"} / ${branchLabel(selectedProjectBranches, selectedBranchId)}`}
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Chip label={humanizeFieldLabel(item.item_type)} />
              <Chip label={`Version ${item.version}`} variant="outlined" />
              {selectedProject ? <Chip label={`Project ${selectedProject.name}`} variant="outlined" /> : null}
              <Chip label={`Branch ${branchLabel(selectedProjectBranches, selectedBranchId)}`} variant="outlined" />
              {sourcePayload.metaclass ? <Chip label={humanizeFieldLabel(String(sourcePayload.metaclass))} variant="outlined" size="small" /> : null}
            </Stack>
          </Stack>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ xs: "stretch", sm: "center" }}>
            <ToggleButtonGroup size="small" exclusive value={itemDetailViewMode} onChange={handleItemDetailViewModeChange} aria-label="Item detail view mode">
              {ITEM_DETAIL_VIEW_MODES.map((mode) => (
                <ToggleButton key={mode} value={mode}>
                  {ITEM_DETAIL_VIEW_LABELS[mode]}
                </ToggleButton>
              ))}
            </ToggleButtonGroup>
            {options.extraHeader}
          </Stack>
        </Stack>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              lg: compactUi ? "260px minmax(0, 1fr)" : "300px minmax(0, 1fr)",
            },
            gap: 2,
            alignItems: "start",
          }}
        >
          <Paper sx={{ p: compactUi ? 1 : 1.5, borderRadius: 2 }}>
            <Typography variant="overline" color="text.secondary">
              Specification Sections
            </Typography>
            <List dense disablePadding>
              <ListItemButton selected={selectedSpecificationSection === "properties"} onClick={() => setSelectedSpecificationSection("properties")}>
                <ListItemText
                  primary={displayEntityName(item.name, item.id, item.item_type, referenceNameById, item.path)}
                  secondary={humanizeFieldLabel(item.item_type)}
                />
              </ListItemButton>
              {specificationChildSections.map((sectionId) => (
                <ListItemButton
                  key={sectionId}
                  selected={selectedSpecificationSection === sectionId}
                  onClick={() => setSelectedSpecificationSection(sectionId)}
                  sx={{ pl: 4 }}
                >
                  <ListItemText primary={SPECIFICATION_SECTION_LABELS[sectionId]} />
                </ListItemButton>
              ))}
            </List>
          </Paper>
          <Paper sx={{ p: panelPadding, borderRadius: 2, minWidth: 0 }}>
            <Stack spacing={sectionSpacing}>
              <Box>
                <Typography variant="h6">{selectedSectionTitle}</Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                  {specificationSectionIntro(selectedSpecificationSection, item)}
                </Typography>
              </Box>
              {renderSelectedSectionContent()}
            </Stack>
          </Paper>
        </Box>
      </Stack>
    );
  };

  const pickCompareSide = (side: "left" | "right", itemId: string) => {
    const readableLabel = humanReadableReference(itemId, referenceNameById);
    setCompareMode("item");
    compareMutation.reset();
    if (side === "left") {
      setCompareLeft(itemId);
      setCompareLeftDisplay(readableLabel);
      setCompareLeftProjectId(selectedProjectId);
      setCompareLeftBranchId(selectedBranchId);
    } else {
      setCompareRight(itemId);
      setCompareRightDisplay(readableLabel);
      setCompareRightProjectId(selectedProjectId);
      setCompareRightBranchId(selectedBranchId);
    }
    setTab("compare");
  };

  const renderParameterControls = (
    title: string,
    parameters: SwaggerParameterSpec[],
    values: Record<string, string>,
    onChange: (name: string, value: string) => void,
  ) => (
    <Stack spacing={1}>
      <Typography variant="subtitle2">{title}</Typography>
      {parameters.length ? (
        <Grid container spacing={1.5}>
          {parameters.map((parameter) => {
            const options = parameter.enum.length
              ? ["", ...parameter.enum.map((option) => String(option))]
              : parameter.schema_type === "boolean"
                ? ["", "true", "false"]
                : null;
            return (
              <Grid item xs={12} md={6} key={`${title}-${parameter.name}`}>
                <TextField
                  label={`${parameter.name}${parameter.required ? " *" : ""}`}
                  value={values[parameter.name] ?? ""}
                  onChange={(event) => onChange(parameter.name, event.target.value)}
                  helperText={parameter.description || parameter.schema_type}
                  fullWidth
                  select={Boolean(options)}
                >
                  {options?.map((option) => (
                    <MenuItem key={option || "blank"} value={option}>
                      {option || "Unset"}
                    </MenuItem>
                  ))}
                </TextField>
              </Grid>
            );
          })}
        </Grid>
      ) : (
        <Typography variant="body2" color="text.secondary">
          No {title.toLowerCase()} declared.
        </Typography>
      )}
    </Stack>
  );

  const renderDashboard = () => (
    <Stack spacing={2}>
      <Grid container spacing={2}>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: "100%", borderRadius: 2 }}>
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                Repository
              </Typography>
              <Typography variant="h3">{projects.length}</Typography>
              <Typography color="text.secondary">RealSwagger resource entries available to this TWC user.</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: "100%", borderRadius: 2 }}>
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                Active Project Branches
              </Typography>
              <Typography variant="h3">{selectedProjectId ? selectedProjectBranches.length : 0}</Typography>
              <Typography color="text.secondary">Loaded only for the currently selected project.</Typography>
            </CardContent>
          </Card>
        </Grid>
        <Grid item xs={12} md={4}>
          <Card sx={{ height: "100%", borderRadius: 2 }}>
            <CardContent>
              <Typography variant="overline" color="text.secondary">
                Model Items
              </Typography>
              <Typography variant="h3">{baseFlatNodes.length}</Typography>
              <Typography color="text.secondary">Loaded for the selected project and branch.</Typography>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Typography variant="h5">Swagger Contract Boundary</Typography>
          <Typography color="text.secondary">
            This workspace exposes only Teamwork Cloud operations present in RealSwagger.json. The curated tabs cover common repository and model flows; API Explorer exposes the complete contract as read-only documentation for every user and enables execution for administrators.
          </Typography>
          <Typography color="text.secondary">
            Simulation, collaborator workspaces, global model search, publishing, export jobs, job center, saved searches, bookmarks, comments, documents, and collaborator-style attachments are not shown because this Swagger file does not define those APIs. Swagger artifact upload and download operations remain administrator-only in API Explorer.
          </Typography>
          {contractManifest ? (
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Chip label={`${contractManifest.operations.length} operations`} />
              <Chip label={`${Object.keys(contractManifest.tag_counts).length} tags`} variant="outlined" />
              <Chip label={apiOperationStats || "No operation counts"} variant="outlined" />
              <Chip label={`${contractManifest.schemas.length} schemas`} variant="outlined" />
            </Stack>
          ) : null}
          {contractManifest?.warnings.map((warning) => (
            <Alert severity="warning" key={warning}>
              {warning}
            </Alert>
          ))}
          {session?.capabilities ? <CapabilityBadges capabilities={Object.values(session.capabilities.capabilities)} /> : null}
        </Stack>
      </Paper>
    </Stack>
  );

  const renderProjects = () => (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
        <Box>
          <Typography variant="h5">Project Browser</Typography>
          <Typography variant="body2" color="text.secondary">
            Browse the published content for the selected project and branch from the stored Workbench model snapshot.
          </Typography>
        </Box>
        <Button
          variant="outlined"
          startIcon={<RefreshRoundedIcon />}
          onClick={() => refreshSelectedProjectMutation.mutate()}
          disabled={!selectedProjectId || refreshSelectedProjectMutation.isPending}
        >
          Reload Stored Project
        </Button>
      </Stack>
      {!selectedProject ? (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a project</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Use the selector on the left to choose which published project snapshot you want to browse.
          </Typography>
        </Paper>
      ) : null}
      {selectedProject ? (
        <Paper sx={{ p: 3, borderRadius: 2 }}>
          <Stack spacing={1.5}>
            <Typography variant="h6">{selectedProject.name}</Typography>
            <Typography variant="body2" color="text.secondary">
              {selectedProject.description || "Browse the current branch snapshot as cards for quick scanning and jumping into details."}
            </Typography>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Chip label="Stored Workbench project" variant="outlined" />
              {selectedProject.workspace_id ? <Chip label="Workspace-scoped" variant="outlined" /> : null}
              <Chip
                label={
                  branchesQuery.isLoading
                    ? "Loading branches"
                    : selectedBranchId
                      ? `Branch ${branchLabel(selectedProjectBranches, selectedBranchId)}`
                      : "Default branch context"
                }
                color="primary"
              />
            </Stack>
          </Stack>
        </Paper>
      ) : null}
      {branchesQuery.isLoading && selectedProjectId ? <CircularProgress size={28} /> : null}
      {branchesQuery.error ? <Alert severity="error">{errorMessage(branchesQuery.error)}</Alert> : null}
      {treeQuery.isLoading ? <CircularProgress size={28} /> : null}
      {treeQuery.error ? <Alert severity="error">{errorMessage(treeQuery.error)}</Alert> : null}
      {projectUsagesQuery.isLoading && selectedProjectId && selectedBranchId ? <CircularProgress size={24} /> : null}
      {projectUsagesQuery.error ? <Alert severity="error">{errorMessage(projectUsagesQuery.error)}</Alert> : null}
      {projectUsagesQuery.data ? (
        <Paper sx={{ p: 2.5, borderRadius: 2 }}>
          <Stack spacing={1.5}>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
              <Box>
                <Typography variant="h6">Project Usages</Typography>
                <Typography variant="body2" color="text.secondary">
                  {projectUsagesQuery.data.total
                    ? `${projectUsagesQuery.data.total} attached project model${projectUsagesQuery.data.total === 1 ? "" : "s"} used by ${projectUsagesQuery.data.primary_model_name || selectedProject?.name}.`
                    : "No attached project models were recorded in this branch snapshot."}
                </Typography>
              </Box>
              <Chip label={`${projectUsagesQuery.data.total} attached`} color={projectUsagesQuery.data.total ? "primary" : "default"} variant="outlined" />
            </Stack>
            {projectUsagesQuery.data.source === "legacy-snapshot-inferred" && projectUsagesQuery.data.total ? (
              <Alert severity="info">This older snapshot did not mark its primary model; Workbench treats the first captured model as primary.</Alert>
            ) : null}
            {projectUsagesQuery.data.items.map((usage) => (
              <Box key={usage.id} sx={{ p: 1.5, border: 1, borderColor: "divider", borderRadius: 1.5 }}>
                <Stack spacing={0.75}>
                  <Stack direction={{ xs: "column", sm: "row" }} spacing={1} justifyContent="space-between" alignItems={{ xs: "flex-start", sm: "center" }}>
                    <Typography variant="subtitle1">{usage.name}</Typography>
                    <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                      <Chip label={humanizeFieldLabel(usage.usage_type || "attached")} size="small" />
                      {usage.version ? <Chip label={`Version ${usage.version}`} size="small" variant="outlined" /> : null}
                      {usage.automatic !== null && usage.automatic !== undefined ? (
                        <Chip label={usage.automatic ? "Automatic" : "Manual"} size="small" variant="outlined" />
                      ) : null}
                    </Stack>
                  </Stack>
                  {usage.qualified_name && usage.qualified_name !== usage.name ? (
                    <Typography variant="body2" color="text.secondary">{usage.qualified_name}</Typography>
                  ) : null}
                  <Typography variant="caption" color="text.secondary" sx={{ overflowWrap: "anywhere" }}>
                    {usage.uri || usage.model_id || usage.id}
                  </Typography>
                </Stack>
              </Box>
            ))}
          </Stack>
        </Paper>
      ) : null}
      <Grid container spacing={2}>
        {baseFlatNodes.map((node) => (
          <Grid item xs={12} md={6} lg={4} key={node.id}>
            <Card sx={{ height: "100%", borderRadius: 2 }}>
              <CardContent>
                <Stack spacing={1.5}>
                  <Box>
                    <Typography variant="h6">{node.label}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {selectedProject ? `${selectedProject.name} / ${branchLabel(selectedProjectBranches, selectedBranchId)}` : node.node_type}
                    </Typography>
                    {node.path ? (
                      <Typography variant="caption" color="text.secondary">
                        {friendlyPath(node.path, referenceNameById)}
                      </Typography>
                    ) : null}
                  </Box>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label={humanizeFieldLabel(node.node_type)} size="small" />
                    {selectedProject ? <Chip label={`Project: ${selectedProject.name}`} size="small" variant="outlined" /> : null}
                    {selectedBranchId ? <Chip label={`Branch: ${branchLabel(selectedProjectBranches, selectedBranchId)}`} size="small" variant="outlined" /> : null}
                  </Stack>
                  <Stack direction="row" spacing={1}>
                    <Button size="small" variant="contained" onClick={() => openNode(node)}>
                      Details
                    </Button>
                    <Button size="small" onClick={() => pickCompareSide("left", node.id)}>
                      Compare Left
                    </Button>
                    <Button size="small" onClick={() => pickCompareSide("right", node.id)}>
                      Compare Right
                    </Button>
                  </Stack>
                </Stack>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
      {!treeQuery.isLoading && selectedProjectId && !baseFlatNodes.length ? (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography color="text.secondary">No model entries were returned for the selected project and branch.</Typography>
        </Paper>
      ) : null}
    </Stack>
  );

  const renderModels = () => (
    <Stack spacing={2}>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
        <Box>
          <Typography variant="h5">Model Browser</Typography>
          <Typography variant="body2" color="text.secondary">
            {selectedProject
              ? `${selectedProject.name} / ${branchLabel(selectedProjectBranches, selectedBranchId)}`
              : "Select a project to inspect its published branch tree and specification window."}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          <Button
            variant="outlined"
            startIcon={<RefreshRoundedIcon />}
            onClick={() => refreshSelectedProjectMutation.mutate()}
            disabled={!selectedProjectId || refreshSelectedProjectMutation.isPending}
          >
            Reload Stored Project
          </Button>
          {canRefreshAccessMap ? (
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              onClick={() => refreshBranchAccessManifestMutation.mutate()}
              disabled={
                !csrfToken
                || !selectedProjectId
                || !selectedBranchId
                || refreshBranchAccessManifestMutation.isPending
              }
            >
              Refresh Access Map
            </Button>
          ) : null}
        </Stack>
      </Stack>
      {!selectedProject ? (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a project</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Choose a published project snapshot from the selector on the left to inspect the full branch model tree.
          </Typography>
        </Paper>
      ) : null}
      {selectedProject && !selectedBranchId && !branchesQuery.isLoading ? (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a branch</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Model Browser follows one published branch snapshot at a time so we can keep the full containment tree and specification data coherent.
          </Typography>
        </Paper>
      ) : null}
      {branchesQuery.isLoading && selectedProjectId ? <CircularProgress size={28} /> : null}
      {branchesQuery.error ? <Alert severity="error">{errorMessage(branchesQuery.error)}</Alert> : null}
      {treeQuery.isLoading ? <CircularProgress size={28} /> : null}
      {treeQuery.error ? <Alert severity="error">{errorMessage(treeQuery.error)}</Alert> : null}
      {branchAccessManifestQuery.error ? <Alert severity="error">{errorMessage(branchAccessManifestQuery.error)}</Alert> : null}
      {branchAccessManifestStatus?.message ? (
        <Alert severity={branchAccessManifestStatus.accessible_user_count ? "info" : "warning"}>
          {branchAccessManifestStatus.message}
          {branchAccessManifestStatus.updated_at ? ` Last refreshed ${new Date(branchAccessManifestStatus.updated_at).toLocaleString()}.` : ""}
        </Alert>
      ) : null}
      {refreshBranchAccessManifestMutation.isPending ? (
        <Alert severity="info">Refreshing the shared access map from Teamwork Cloud permissions.</Alert>
      ) : null}
      {selectedProject && selectedBranchId ? (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: {
              xs: "1fr",
              xl: `${modelContainmentPaneWidth}px 12px minmax(0, 1fr)`,
            },
            gap: 0,
            minWidth: 0,
            alignItems: "start",
          }}
        >
          <Paper
            sx={{
              p: compactUi ? 1.5 : 2,
              borderRadius: 2,
              minWidth: 0,
              display: "flex",
              flexDirection: "column",
              maxHeight: { xs: "none", xl: viewportPanelMaxHeight },
              overflow: "hidden",
            }}
          >
            <Stack spacing={sectionSpacing} sx={{ minHeight: 0, flex: 1 }}>
              <TextField label="Filter containment tree" value={treeFilter} onChange={(event) => setTreeFilter(event.target.value)} fullWidth />
              {branchAccessManifestStatus ? (
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                  <Chip
                    label={
                      branchAccessManifestStatus.current_user_admin_access
                        ? "Your access: project admin"
                        : branchAccessManifestStatus.current_user_editable
                          ? "Your access: editor"
                          : "Your access: viewer"
                    }
                    color={branchAccessManifestStatus.current_user_admin_access ? "primary" : "default"}
                    variant="outlined"
                  />
                  <Chip label={`${branchAccessManifestStatus.accessible_user_count} viewers`} variant="outlined" />
                  <Chip label={`${branchAccessManifestStatus.editable_user_count} editors`} variant="outlined" />
                  <Chip label={`${branchAccessManifestStatus.admin_user_count} admins`} variant="outlined" />
                </Stack>
              ) : null}
              <Paper variant="outlined" sx={{ p: compactUi ? 1.25 : 1.5, borderRadius: 2 }}>
                <Stack spacing={0.5}>
                  <Typography variant="overline" color="text.secondary">
                    Containment Tree
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    Browse the published branch containment just like Cameo, then inspect the selected node in the specification window on the right.
                  </Typography>
                  <Stack spacing={0.25} sx={{ pt: 0.75 }}>
                    <FormControlLabel
                      control={
                        <Checkbox
                          size="small"
                          checked={showAuxiliaryResourcesInTree}
                          disabled={!csrfToken || settingsMutation.isPending}
                          onChange={(event) =>
                            settingsMutation.mutate({
                              ...currentPreferences,
                              show_hidden_packages_in_tree: event.target.checked,
                              show_auxiliary_resources_in_tree: event.target.checked,
                            })
                          }
                        />
                      }
                      label="Show Auxiliary Resources"
                    />
                    <FormControlLabel
                      control={
                        <Checkbox
                          size="small"
                          checked={showAppliedStereotypesInTree}
                          disabled={!csrfToken || settingsMutation.isPending}
                          onChange={(event) =>
                            settingsMutation.mutate({
                              ...currentPreferences,
                              show_applied_stereotypes_in_tree: event.target.checked,
                            })
                          }
                        />
                      }
                      label="Show Applied Stereotypes"
                    />
                    <FormControlLabel
                      control={
                        <Checkbox
                          size="small"
                          checked={Boolean(currentPreferences.show_full_types_in_tree)}
                          disabled={!csrfToken || settingsMutation.isPending}
                          onChange={(event) =>
                            settingsMutation.mutate({
                              ...currentPreferences,
                              show_full_types_in_tree: event.target.checked,
                            })
                          }
                        />
                      }
                      label="Show Full Types"
                    />
                  </Stack>
                </Stack>
              </Paper>
              <Box sx={{ minHeight: 0, flex: 1, overflow: "auto", pr: 0.5 }}>
                <ProjectTree
                  nodes={visibleTreeNodes}
                  selectedId={selectedItemId}
                  filter={treeFilter}
                  onSelect={(node) => selectContainmentNode(node, "models")}
                  onExpand={loadTreeChildren}
                  loadingIds={loadingTreeNodeIds}
                  expandedIds={expandedTreeNodeIds}
                  onExpandedChange={setExpandedTreeNodeIds}
                  showFullTypes={Boolean(currentPreferences.show_full_types_in_tree)}
                />
              </Box>
            </Stack>
          </Paper>
          <Box
            role="separator"
            aria-orientation="vertical"
            sx={resizeHandleStyles()}
            onMouseDown={(event) => beginHorizontalResize(event, modelContainmentPaneWidth, setModelContainmentPaneWidth, 260, 460)}
          />
          <Box sx={{ minWidth: 0, pl: { xs: 0, xl: compactUi ? 1.5 : 2 } }}>
            {selectedWorkspaceItem ? (
              <Paper sx={{ p: panelPadding, borderRadius: 2 }}>
                {renderSpecificationWorkspace(selectedWorkspaceItem, {
                  mode: "browser",
                  editable: Boolean(selectedWorkspaceItem.editable && canEdit),
                  extraHeader: (
                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                      {selectedWorkspaceItemDiagramPreviewUrl ? (
                        <Button size="small" variant="contained" onClick={openDiagramViewer}>
                          View Diagram
                        </Button>
                      ) : null}
                      <Button size="small" onClick={() => pickCompareSide("left", selectedWorkspaceItem.id)}>
                        Compare Left
                      </Button>
                      <Button size="small" onClick={() => pickCompareSide("right", selectedWorkspaceItem.id)}>
                        Compare Right
                      </Button>
                      <Button size="small" variant="outlined" onClick={revealSelectedInTree} disabled={!selectedItemId}>
                        Reveal In Tree
                      </Button>
                      <Button
                        size="small"
                        variant="contained"
                        startIcon={<SaveRoundedIcon />}
                        disabled={!selectedWorkspaceItem.editable || !canEdit || saveItemMutation.isPending}
                        onClick={() => saveItemMutation.mutate()}
                      >
                        Save
                      </Button>
                    </Stack>
                  ),
                })}
              </Paper>
            ) : (
              <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
                {selectedTreeNode ? (
                  <Stack spacing={1.25} alignItems="center">
                    <Typography variant="h6">{selectedTreeNode.label}</Typography>
                    <Chip label={humanizeFieldLabel(selectedTreeNode.node_type)} variant="outlined" />
                    <Typography color="text.secondary">
                      {friendlyPath(selectedTreeNode.path, referenceNameById) || selectedTreeNode.id}
                    </Typography>
                    {itemQuery.isLoading ? <CircularProgress size={24} /> : null}
                    {itemQuery.error ? <Alert severity="warning">{errorMessage(itemQuery.error)}</Alert> : null}
                    <Typography variant="body2" color="text.secondary">
                      Workbench selected this containment node, but the full item specification is still being resolved from the stored branch snapshot.
                    </Typography>
                  </Stack>
                ) : (
                  <>
                    <Typography variant="h6">Select a model item</Typography>
                    <Typography color="text.secondary" sx={{ mt: 1 }}>
                      Use the containment tree to the left to pick any node from the published branch tree, then inspect it here.
                    </Typography>
                  </>
                )}
              </Paper>
            )}
          </Box>
        </Box>
      ) : null}
    </Stack>
  );

  const renderDetails = () => {
    const selectedItem = selectedWorkspaceItem;
    const editable = Boolean(selectedItem?.editable && canEdit);

    if (!selectedItemId) {
      return (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a model item</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Use the model tree or Model Browser to open details from the stored branch model already published into Workbench.
          </Typography>
        </Paper>
      );
    }

    if (itemQuery.isLoading && !selectedItem) {
      return <CircularProgress size={28} />;
    }
    if (!selectedItem) {
      return (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Item details unavailable</Typography>
          {itemQuery.error ? <Alert severity="warning" sx={{ mt: 2 }}>{errorMessage(itemQuery.error)}</Alert> : null}
        </Paper>
      );
    }

    return (
      <Stack spacing={2}>
        <Box>
          <Typography variant="h5">Item Details</Typography>
          <Typography variant="body2" color="text.secondary">
            Use the same category-driven specification workspace you would expect in Cameo, backed by the stored Workbench model data.
          </Typography>
        </Box>
        {!editable ? (
          <Alert severity="info">
            Editing is disabled for this item unless TWC marks it editable and the RealSwagger element update capability is available to the current session.
          </Alert>
        ) : null}
        {renderSpecificationWorkspace(selectedItem, {
          mode: "details",
          editable,
          extraHeader: (
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Button startIcon={<RefreshRoundedIcon />} onClick={() => refreshItemMutation.mutate()} disabled={refreshItemMutation.isPending}>
                Refresh
              </Button>
              <Button startIcon={<CompareArrowsRoundedIcon />} onClick={() => pickCompareSide("left", selectedItemId)}>
                Compare Left
              </Button>
              <Button startIcon={<CompareArrowsRoundedIcon />} onClick={() => pickCompareSide("right", selectedItemId)}>
                Compare Right
              </Button>
              <Button variant="outlined" onClick={revealSelectedInTree} disabled={!selectedItemId}>
                Reveal In Tree
              </Button>
              <Button
                variant="contained"
                startIcon={<SaveRoundedIcon />}
                disabled={!editable || saveItemMutation.isPending}
                onClick={() => saveItemMutation.mutate()}
              >
                Save
              </Button>
            </Stack>
          ),
        })}
      </Stack>
    );
  };

  const renderDiagramViewer = () => {
    if (!selectedItemId) {
      return (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">Select a diagram</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            Pick a diagram from Model Browser, then use the diagram action to open it here.
          </Typography>
        </Paper>
      );
    }

    if (itemQuery.isLoading || !selectedWorkspaceItem) {
      return <CircularProgress size={28} />;
    }

    if (!selectedWorkspaceItemDiagramPreviewUrl) {
      return (
        <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
          <Typography variant="h5">No published diagram preview</Typography>
          <Typography color="text.secondary" sx={{ mt: 1 }}>
            The selected item does not currently include a viewable published diagram preview. Select a diagram with a preview from Model Browser to open it here.
          </Typography>
          <Stack direction="row" spacing={1} justifyContent="center" sx={{ mt: 2 }}>
            <Button variant="contained" onClick={() => setTab("models")}>
              Back to Model Browser
            </Button>
          </Stack>
        </Paper>
      );
    }

    return (
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
          <Box>
            <Typography variant="h5">Diagram Viewer</Typography>
            <Typography variant="body2" color="text.secondary">
              {displayEntityName(selectedWorkspaceItem.name, selectedWorkspaceItem.id, selectedWorkspaceItem.item_type, referenceNameById, selectedWorkspaceItem.path)}
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Button variant="outlined" onClick={openDiagramDetails}>
              Diagram Details
            </Button>
            <Button variant="outlined" onClick={() => setTab("models")}>
              Back to Model Browser
            </Button>
          </Stack>
        </Stack>
        <Paper sx={{ p: panelPadding, borderRadius: 2 }}>
          <Box
            sx={{
              display: "flex",
              justifyContent: "center",
              alignItems: "center",
              maxHeight: viewportPanelMaxHeight,
              overflow: "auto",
              bgcolor: "background.paper",
            }}
          >
            <Box
              component="img"
              src={selectedWorkspaceItemDiagramPreviewUrl}
              alt={displayEntityName(selectedWorkspaceItem.name, selectedWorkspaceItem.id, selectedWorkspaceItem.item_type, referenceNameById, selectedWorkspaceItem.path)}
              sx={{
                maxWidth: "100%",
                maxHeight: previewMaxHeight,
                height: "auto",
                objectFit: "contain",
                borderRadius: 1,
              }}
            />
          </Box>
        </Paper>
      </Stack>
    );
  };

  const renderElementSearch = () => {
    const resultItems: CachedElementRecord[] = elementSearchResponse?.items ?? [];
    const activeSearchItem = selectedSearchWorkspaceItem;
    const currentSearchMode = elementSearchMode;

    return (
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
          <Box>
            <Typography variant="h5">Element Search</Typography>
            <Typography variant="body2" color="text.secondary">
              Search the stored branch snapshot by element id, package path, resource name, element name, or applied stereotype, then inspect the full specification window without leaving Workbench.
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              onClick={() => {
                setElementSearchQuery("");
                setElementSearchStereotype("");
                setElementSearchItemType("");
                setElementSearchResponse(null);
                setElementSearchSummary("");
              }}
            >
              Clear Search
            </Button>
            <Button variant="outlined" onClick={() => setTab("models")} disabled={!selectedProjectId || !selectedBranchId}>
              Open Model Browser
            </Button>
          </Stack>
        </Stack>
        {!selectedProject ? (
          <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
            <Typography variant="h5">Select a project</Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>
              Choose a published project snapshot first, then search its stored branch elements here.
            </Typography>
          </Paper>
        ) : null}
        {selectedProject && !selectedBranchId ? (
          <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
            <Typography variant="h5">Select a branch</Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>
              Element Search stays scoped to one stored branch at a time so paths, tree locations, and specifications remain exact.
            </Typography>
          </Paper>
        ) : null}
        {selectedProject && selectedBranchId ? (
          <>
            <Paper sx={{ p: 3, borderRadius: 2 }}>
              <Grid container spacing={2}>
                <Grid item xs={12} lg={7}>
                  <Stack spacing={1.5}>
                    <TextField
                      label="Search by ID, package, resource, or element"
                      value={elementSearchQuery}
                      onChange={(event) => setElementSearchQuery(event.target.value)}
                      helperText="Examples: full element id, qualified path text, package name, diagram name, or model resource text."
                      fullWidth
                    />
                    <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
                      <TextField
                        label="Optional item type filter"
                        value={elementSearchItemType}
                        onChange={(event) => setElementSearchItemType(event.target.value)}
                        helperText="Examples: package, diagram, model, class, element"
                        fullWidth
                      />
                      <Button
                        variant="contained"
                        sx={{ minWidth: { md: 180 } }}
                        disabled={elementSearchMutation.isPending}
                        onClick={() => elementSearchMutation.mutate("query")}
                      >
                        Search Stored Branch
                      </Button>
                    </Stack>
                  </Stack>
                </Grid>
                <Grid item xs={12} lg={5}>
                  <Stack spacing={1.5}>
                    <TextField
                      label="Search all elements by stereotype"
                      value={elementSearchStereotype}
                      onChange={(event) => setElementSearchStereotype(event.target.value)}
                      helperText="Use the applied stereotype name exactly as it appears in the model."
                      fullWidth
                    />
                    <Button
                      variant="outlined"
                      disabled={elementSearchMutation.isPending}
                      onClick={() => elementSearchMutation.mutate("stereotype")}
                    >
                      Search by Stereotype
                    </Button>
                  </Stack>
                </Grid>
              </Grid>
            </Paper>
            {elementSearchMutation.isPending ? <CircularProgress size={28} /> : null}
            {elementSearchSummary ? <Alert severity="success">{elementSearchSummary}</Alert> : null}
            {elementSearchResponse ? (
              <Box
                sx={{
                  display: "grid",
                  gridTemplateColumns: {
                    xs: "1fr",
                    xl: "minmax(320px, 0.9fr) minmax(0, 1.6fr)",
                  },
                  gap: 2,
                  minWidth: 0,
                  alignItems: "start",
                }}
              >
                <Paper sx={{ p: 2, borderRadius: 2, minWidth: 0 }}>
                  <Stack spacing={1.5}>
                    <Stack spacing={0.5}>
                      <Typography variant="overline" color="text.secondary">
                        Search Results
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {currentSearchMode === "stereotype"
                          ? `Stereotype "${elementSearchStereotype.trim()}"`
                          : `Query "${elementSearchQuery.trim()}"`}
                      </Typography>
                    </Stack>
                    {resultItems.length ? (
                      <List dense disablePadding sx={{ maxHeight: viewportPanelMaxHeight, overflow: "auto" }}>
                        {resultItems.map((item) => {
                          const selected = item.element_id === selectedItemId;
                          return (
                            <ListItemButton
                              key={item.element_id}
                              selected={selected}
                              onClick={() => setSelectedItemId(item.element_id)}
                              sx={{ borderRadius: 1.5, mb: 0.75, alignItems: "flex-start" }}
                            >
                              <ListItemText
                                primary={item.name || item.element_id}
                                secondary={
                                  <Stack spacing={0.6} sx={{ mt: 0.5 }}>
                                    <Typography variant="caption" color="text.secondary">
                                      {friendlyPath(item.path, referenceNameById) || item.path || item.element_id}
                                    </Typography>
                                    <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                                      <Chip label={humanizeFieldLabel(item.item_type)} size="small" variant="outlined" />
                                      <Chip label={`${item.child_count} child${item.child_count === 1 ? "" : "ren"}`} size="small" variant="outlined" />
                                    </Stack>
                                  </Stack>
                                }
                              />
                            </ListItemButton>
                          );
                        })}
                      </List>
                    ) : (
                      <Typography color="text.secondary">No stored branch elements matched this search.</Typography>
                    )}
                  </Stack>
                </Paper>
                <Box sx={{ minWidth: 0 }}>
                  {activeSearchItem ? (
                    <Paper sx={{ p: panelPadding, borderRadius: 2 }}>
                      {renderSpecificationWorkspace(activeSearchItem, {
                        mode: "browser",
                        editable: Boolean(activeSearchItem.editable && canEdit),
                        extraHeader: (
                          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                            <Button size="small" variant="outlined" onClick={() => void revealElementPathInTree(activeSearchItem)}>
                              Open in Model Browser
                            </Button>
                            <Button size="small" onClick={() => pickCompareSide("left", activeSearchItem.id)}>
                              Compare Left
                            </Button>
                            <Button size="small" onClick={() => pickCompareSide("right", activeSearchItem.id)}>
                              Compare Right
                            </Button>
                            {isDiagramLikeItem(activeSearchItem) && diagramPreviewDataUrl(activeSearchItem) ? (
                              <Button size="small" variant="contained" onClick={openDiagramViewer}>
                                View Diagram
                              </Button>
                            ) : null}
                          </Stack>
                        ),
                      })}
                    </Paper>
                  ) : (
                    <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
                      <Typography variant="h6">Select a search result</Typography>
                      <Typography color="text.secondary" sx={{ mt: 1 }}>
                        Pick any matched element on the left to open its full stored specification data and exact tree path here.
                      </Typography>
                    </Paper>
                  )}
                </Box>
              </Box>
            ) : null}
          </>
        ) : null}
      </Stack>
    );
  };

  const renderCompare = () => {
    const result = compareMutation.data;
    const resultLeftLabel = result?.left_context
      ? `${result.left_context.project_name} / ${result.left_context.branch_name}`
      : compareLeftLabel;
    const resultRightLabel = result?.right_context
      ? `${result.right_context.project_name} / ${result.right_context.branch_name}`
      : compareRightLabel;
    const totalDifferences = result?.total_differences ?? result?.differences.length ?? 0;
    const contextReady = Boolean(
      compareLeftProjectId && compareLeftBranchId && compareRightProjectId && compareRightBranchId,
    );
    const valuesReady = compareMode === "branch" || Boolean(compareLeft.trim() && compareRight.trim());

    return (
      <Stack spacing={2}>
        <Box>
          <Typography variant="h5">Compare</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            Compare complete stored branches across the same project or two different projects. Item and numeric revision comparison remains available with an independent context on each side.
          </Typography>
        </Box>
        <ToggleButtonGroup
          exclusive
          value={compareMode}
          onChange={(_event, value: CompareMode | null) => {
            if (value) {
              setCompareMode(value);
              compareMutation.reset();
            }
          }}
          size="small"
        >
          <ToggleButton value="branch">Projects / branches</ToggleButton>
          <ToggleButton value="item">Items / revisions</ToggleButton>
        </ToggleButtonGroup>
        <Paper sx={{ p: 3, borderRadius: 2 }}>
          <Grid container spacing={2}>
            <Grid item xs={12} md={3}>
              <TextField
                select
                label="Left project"
                value={compareLeftProjectId}
                onChange={(event) => {
                  setCompareLeftProjectId(event.target.value);
                  setCompareLeftBranchId("");
                  compareMutation.reset();
                }}
                fullWidth
              >
                <MenuItem value=""><em>Select project</em></MenuItem>
                {projects.map((project) => <MenuItem key={project.id} value={project.id}>{project.name}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={12} md={3}>
              <TextField
                select
                label="Left branch"
                value={compareLeftBranchId}
                onChange={(event) => {
                  setCompareLeftBranchId(event.target.value);
                  compareMutation.reset();
                }}
                disabled={!compareLeftProjectId || compareLeftBranchesQuery.isLoading || !compareLeftBranches.length}
                fullWidth
              >
                {compareLeftBranches.map((branch) => <MenuItem key={branch.id} value={branch.id}>{branch.name}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={12} md={3}>
              <TextField
                select
                label="Right project"
                value={compareRightProjectId}
                onChange={(event) => {
                  setCompareRightProjectId(event.target.value);
                  setCompareRightBranchId("");
                  compareMutation.reset();
                }}
                fullWidth
              >
                <MenuItem value=""><em>Select project</em></MenuItem>
                {projects.map((project) => <MenuItem key={project.id} value={project.id}>{project.name}</MenuItem>)}
              </TextField>
            </Grid>
            <Grid item xs={12} md={3}>
              <TextField
                select
                label="Right branch"
                value={compareRightBranchId}
                onChange={(event) => {
                  setCompareRightBranchId(event.target.value);
                  compareMutation.reset();
                }}
                disabled={!compareRightProjectId || compareRightBranchesQuery.isLoading || !compareRightBranches.length}
                fullWidth
              >
                {compareRightBranches.map((branch) => <MenuItem key={branch.id} value={branch.id}>{branch.name}</MenuItem>)}
              </TextField>
            </Grid>
          </Grid>
          {compareLeftBranchesQuery.error ? <Alert severity="error" sx={{ mt: 2 }}>{errorMessage(compareLeftBranchesQuery.error)}</Alert> : null}
          {compareRightBranchesQuery.error ? <Alert severity="error" sx={{ mt: 2 }}>{errorMessage(compareRightBranchesQuery.error)}</Alert> : null}
        </Paper>
        {compareMode === "item" ? (
          <Paper sx={{ p: 3, borderRadius: 2 }}>
            <Grid container spacing={2}>
              <Grid item xs={12} md={6}>
                <TextField
                  label="Left item or revision"
                  value={compareLeftFieldValue}
                  onChange={(event) => {
                    const nextValue = event.target.value;
                    setCompareLeft(nextValue);
                    setCompareLeftDisplay(nextValue);
                    compareMutation.reset();
                  }}
                  helperText={compareLeft.trim() ? compareLeftLabel : "Use a discovered item or a revision number."}
                  fullWidth
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <TextField
                  label="Right item or revision"
                  value={compareRightFieldValue}
                  onChange={(event) => {
                    const nextValue = event.target.value;
                    setCompareRight(nextValue);
                    setCompareRightDisplay(nextValue);
                    compareMutation.reset();
                  }}
                  helperText={compareRight.trim() ? compareRightLabel : "Numeric revision diff requires the same project on both sides."}
                  fullWidth
                />
              </Grid>
            </Grid>
          </Paper>
        ) : null}
        <Paper sx={{ p: 3, borderRadius: 2 }}>
          <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>
            <Box sx={{ flex: 1 }}>
              <Typography variant="overline" color="text.secondary">Left context</Typography>
              <Typography variant="subtitle2">{compareLeftContextLabel}</Typography>
            </Box>
            <CompareArrowsRoundedIcon color="action" />
            <Box sx={{ flex: 1 }}>
              <Typography variant="overline" color="text.secondary">Right context</Typography>
              <Typography variant="subtitle2">{compareRightContextLabel}</Typography>
            </Box>
            <Button
              variant="contained"
              startIcon={<CompareArrowsRoundedIcon />}
              disabled={!contextReady || !valuesReady || compareMutation.isPending}
              onClick={() => compareMutation.mutate()}
            >
              Run diff
            </Button>
          </Stack>
        </Paper>
        {compareMutation.isPending ? <CircularProgress size={28} /> : null}
        {result ? (
          <Paper sx={{ p: 3, borderRadius: 2 }}>
            <Stack spacing={2}>
              <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
                <Typography variant="h6">{resultLeftLabel && resultRightLabel ? `${resultLeftLabel} vs ${resultRightLabel}` : result.summary}</Typography>
                <Chip label={result.compare_type} />
                <Chip label={`${totalDifferences} differences`} variant="outlined" />
                {result.left_context ? <Chip label={`${result.left_context.element_count} left elements`} variant="outlined" /> : null}
                {result.right_context ? <Chip label={`${result.right_context.element_count} right elements`} variant="outlined" /> : null}
              </Stack>
              <Typography variant="body2" color="text.secondary">{result.summary}</Typography>
              {result.truncated ? (
                <Alert severity="warning">Showing the first {result.differences.length} of {totalDifferences} differences.</Alert>
              ) : null}
              {!result.differences.length ? <Alert severity="success">No differences were found in the accessible stored content.</Alert> : null}
              <List disablePadding>
                {result.differences.map((difference) => (
                  <ListItemButton key={difference.field_path} alignItems="flex-start">
                    <ListItemText
                      primary={humanizeFieldPath(difference.field_path)}
                      secondary={
                        <Box component="span" sx={{ display: "block", mt: 1 }}>
                          <Typography component="span" variant="body2" sx={{ display: "block" }}>{difference.summary}</Typography>
                          <Typography component="pre" variant="caption" sx={{ display: "block", whiteSpace: "pre-wrap", mt: 1, mb: 0 }}>
                            {`Left: ${humanReadableValue(difference.left_value, referenceNameById)}\nRight: ${humanReadableValue(difference.right_value, referenceNameById)}`}
                          </Typography>
                        </Box>
                      }
                    />
                  </ListItemButton>
                ))}
              </List>
            </Stack>
          </Paper>
        ) : null}
      </Stack>
    );
  };

  const renderCacheApiKeys = () => (
    <Paper sx={{ p: 3, borderRadius: 2 }}>
      <Stack spacing={2}>
        <Box>
          <Typography variant="h5">API Access Keys</Typography>
          <Typography variant="body2" color="text.secondary">
            Create bearer keys for scripts, AI tools, and integrations that need to work with Workbench data as you. The model data stays shared in one cache copy per branch, while Workbench keeps a separate per-user permission overlay so visibility still follows your TWC access.
          </Typography>
        </Box>
        {cacheApiKeysQuery.isLoading ? <CircularProgress size={28} /> : null}
        {cacheApiKeysQuery.error ? <Alert severity="error">{errorMessage(cacheApiKeysQuery.error)}</Alert> : null}
        <Alert severity="info">
          Use these keys with <code>Authorization: Bearer &lt;key&gt;</code>. Start with <code>GET /api/cache</code> or <code>GET /api/cache/servers</code>, then drill into the project, branch, model, and element routes.
        </Alert>
        <Typography variant="caption" color="text.secondary">
          These keys read the Workbench cache, not live TWC directly. Open a project branch in Workbench first so its cached data and your per-user visibility snapshot are available for scripts and AI tools.
        </Typography>
        <TextField
          label="New API key label"
          value={newCacheApiKeyLabel}
          onChange={(event) => setNewCacheApiKeyLabel(event.target.value)}
          helperText="Example: Local Python extractor, Langflow reader, AI notebook, or nightly report."
          fullWidth
        />
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} useFlexGap flexWrap="wrap">
          <FormControlLabel
            control={<Checkbox checked={newCacheApiKeyScopes.includes("read")} onChange={(event) => toggleNewCacheApiKeyScope("read", event.target.checked)} />}
            label="Read"
          />
          <FormControlLabel
            control={<Checkbox checked={newCacheApiKeyScopes.includes("write")} onChange={(event) => toggleNewCacheApiKeyScope("write", event.target.checked)} />}
            label="Write"
          />
          <FormControlLabel
            control={<Checkbox checked={newCacheApiKeyScopes.includes("edit")} onChange={(event) => toggleNewCacheApiKeyScope("edit", event.target.checked)} />}
            label="Edit"
          />
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
          <Button
            variant="contained"
            disabled={!csrfToken || !newCacheApiKeyLabel.trim() || !newCacheApiKeyScopes.length || createCacheApiKeyMutation.isPending}
            onClick={() => createCacheApiKeyMutation.mutate()}
          >
            Create API Key
          </Button>
          <Button
            variant="outlined"
            startIcon={<RefreshRoundedIcon />}
            onClick={() => queryClient.invalidateQueries({ queryKey: ["workspace-cache-api-keys", ...sessionCacheKey] })}
          >
            Refresh Keys
          </Button>
          {createCacheApiKeyMutation.isPending || deleteCacheApiKeyMutation.isPending ? <CircularProgress size={24} /> : null}
        </Stack>
        {revealedCacheApiKey ? (
          <>
            <Alert severity="success">
              Copy this API key now. Workbench stores only a secure hash and will not reveal the full value again after you leave this screen.
            </Alert>
            <TextField label="New cache API key" value={revealedCacheApiKey} fullWidth InputProps={{ readOnly: true }} />
          </>
        ) : null}
        <TextField
          label="Quick start Python script"
          value={manifestPythonExample}
          fullWidth
          multiline
          minRows={18}
          InputProps={{ readOnly: true }}
        />
        <Stack spacing={1.5}>
          {cacheApiKeys.length ? (
            cacheApiKeys.map((key: CacheApiKeySummary) => (
              <Paper key={key.key_id} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
                  <Box>
                    <Typography variant="subtitle2">{key.label}</Typography>
                    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                      <Chip label={key.token_hint} variant="outlined" size="small" />
                      {key.scopes.map((scope) => (
                        <Chip key={`${key.key_id}-${scope}`} label={scope} variant="outlined" size="small" />
                      ))}
                      <Chip label={`Created ${new Date(key.created_at).toLocaleString()}`} variant="outlined" size="small" />
                      <Chip
                        label={key.last_used_at ? `Last used ${new Date(key.last_used_at).toLocaleString()}` : "Never used"}
                        color={key.last_used_at ? "success" : "default"}
                        variant="outlined"
                        size="small"
                      />
                    </Stack>
                  </Box>
                  <Button
                    variant="text"
                    color="warning"
                    disabled={!csrfToken || deleteCacheApiKeyMutation.isPending}
                    onClick={() => deleteCacheApiKeyMutation.mutate(key.key_id)}
                  >
                    Delete Key
                  </Button>
                </Stack>
              </Paper>
            ))
          ) : (
            <Typography color="text.secondary">No API keys created yet.</Typography>
          )}
        </Stack>
      </Stack>
    </Paper>
  );

  const renderServerPresetManagement = () => {
    const servers = managedServersQuery.data ?? [];
    const serverBusy = createServerMutation.isPending || updateServerMutation.isPending || deleteServerMutation.isPending;
    const workbenchOrigin = window.location.origin.replace(/\/$/, "");
    const newServerLooksLikeWorkbench = newServerPreset.base_url.trim().replace(/\/$/, "") === workbenchOrigin;

    return (
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
            <Box>
              <Typography variant="h5">Teamwork Cloud Servers</Typography>
              <Typography variant="body2" color="text.secondary">
                Add every Teamwork Cloud target admins want users to sign into or receive plugin snapshots from. The server key is the exact value the Cameo plugin uses as <code>metadata.serverId</code>. Do not set the TWC Base URL to the Workbench app URL.
              </Typography>
            </Box>
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              onClick={() => void managedServersQuery.refetch()}
              disabled={managedServersQuery.isFetching}
            >
              Refresh Servers
            </Button>
          </Stack>
          {managedServersQuery.error ? <Alert severity="error">{errorMessage(managedServersQuery.error)}</Alert> : null}
          <Alert severity="info">
            Workbench callback URI for SSO is separate from the TWC Base URL. Register <code>{workbenchOrigin}/api/auth/callback</code> with the TWC/AuthServer client, but set Base URL to the real Teamwork Cloud server.
          </Alert>
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Stack spacing={1.5}>
              <Typography variant="subtitle1">Add Teamwork Cloud server</Typography>
              <Grid container spacing={1.5}>
                <Grid item xs={12} md={2}>
                  <TextField
                    label="Server key"
                    value={newServerPreset.id ?? ""}
                    onChange={(event) => setNewServerPreset((current) => ({ ...current, id: event.target.value.trim() }))}
                    helperText="Example: localhost, prod-2024x"
                    fullWidth
                  />
                </Grid>
                <Grid item xs={12} md={3}>
                  <TextField
                    label="Name"
                    value={newServerPreset.name}
                    onChange={(event) => setNewServerPreset((current) => ({ ...current, name: event.target.value }))}
                    fullWidth
                  />
                </Grid>
                <Grid item xs={12} md={3}>
                  <TextField
                    label="Base URL"
                    value={newServerPreset.base_url}
                    onChange={(event) => setNewServerPreset((current) => ({ ...current, base_url: event.target.value }))}
                    helperText="Example: https://twc2024.company.com:8111"
                    fullWidth
                  />
                </Grid>
                {newServerLooksLikeWorkbench ? (
                  <Grid item xs={12}>
                    <Alert severity="warning">
                      This Base URL matches the Workbench app. Use the real Teamwork Cloud URL here; Workbench&apos;s localhost URL belongs only in the callback URI.
                    </Alert>
                  </Grid>
                ) : null}
                <Grid item xs={12} md={2}>
                  <TextField
                    select
                    label="Version"
                    value={newServerPreset.version}
                    onChange={(event) => setNewServerPreset((current) => ({ ...current, version: event.target.value as ServerProfileInput["version"] }))}
                    fullWidth
                  >
                    <MenuItem value="2024x">2024x</MenuItem>
                    <MenuItem value="2022x">2022x</MenuItem>
                    <MenuItem value="auto">Auto</MenuItem>
                  </TextField>
                </Grid>
                <Grid item xs={12} md={2}>
                  <TextField
                    label="CA bundle path"
                    value={newServerPreset.ca_bundle_path ?? ""}
                    onChange={(event) => setNewServerPreset((current) => ({ ...current, ca_bundle_path: event.target.value || null }))}
                    fullWidth
                  />
                </Grid>
                <Grid item xs={12} md={12}>
                  <Stack>
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={newServerPreset.verify_tls}
                          onChange={(event) => setNewServerPreset((current) => ({ ...current, verify_tls: event.target.checked }))}
                        />
                      }
                      label="Verify TLS certificates"
                    />
                    <FormControlLabel
                      control={
                        <Checkbox
                          checked={newServerPreset.enabled}
                          onChange={(event) => setNewServerPreset((current) => ({ ...current, enabled: event.target.checked }))}
                        />
                      }
                      label="Enabled for sign-in"
                    />
                  </Stack>
                </Grid>
              </Grid>
              <Accordion variant="outlined" disableGutters>
                <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                  <Typography fontWeight={700}>TWC AuthServer / SSO overrides</Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Grid container spacing={1.5}>
                    <Grid item xs={12} md={6}>
                      <TextField
                        label="OIDC discovery URL"
                        value={newServerPreset.auth_discovery_url ?? ""}
                        onChange={(event) => setNewServerPreset((current) => ({ ...current, auth_discovery_url: event.target.value || null }))}
                        placeholder="https://twc.example:8443/authentication/.well-known/oidc-configuration"
                        fullWidth
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <TextField
                        label="Authorize URL"
                        value={newServerPreset.auth_authorize_url ?? ""}
                        onChange={(event) => setNewServerPreset((current) => ({ ...current, auth_authorize_url: event.target.value || null }))}
                        placeholder="https://twc.example:8443/authentication/oidc/authorize"
                        fullWidth
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <TextField
                        label="Token URL"
                        value={newServerPreset.auth_token_url ?? ""}
                        onChange={(event) => setNewServerPreset((current) => ({ ...current, auth_token_url: event.target.value || null }))}
                        placeholder="https://twc.example:8443/authentication/api/oidc/token"
                        fullWidth
                      />
                    </Grid>
                    <Grid item xs={12} md={3}>
                      <TextField
                        label="Login port"
                        type="number"
                        value={newServerPreset.auth_login_port ?? ""}
                        onChange={(event) =>
                          setNewServerPreset((current) => ({
                            ...current,
                            auth_login_port: event.target.value ? Number.parseInt(event.target.value, 10) : null,
                          }))
                        }
                        fullWidth
                      />
                    </Grid>
                    <Grid item xs={12} md={3}>
                      <TextField
                        label="Scope"
                        value={newServerPreset.auth_scope ?? ""}
                        onChange={(event) => setNewServerPreset((current) => ({ ...current, auth_scope: event.target.value || null }))}
                        placeholder="openid"
                        fullWidth
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <TextField
                        label="Client ID"
                        value={newServerPreset.auth_client_id ?? ""}
                        onChange={(event) => setNewServerPreset((current) => ({ ...current, auth_client_id: event.target.value || null }))}
                        placeholder="twcworkbench-twc-2024x"
                        fullWidth
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <TextField
                        label="Client secret"
                        type="password"
                        value={newServerPreset.auth_client_secret ?? ""}
                        onChange={(event) => setNewServerPreset((current) => ({ ...current, auth_client_secret: event.target.value || null }))}
                        helperText="Saved on submit; not shown again after reload."
                        fullWidth
                      />
                    </Grid>
                  </Grid>
                </AccordionDetails>
              </Accordion>
              <Accordion variant="outlined" disableGutters>
                <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                  <Typography fontWeight={700}>OSLC / RealSwagger overrides</Typography>
                </AccordionSummary>
                <AccordionDetails>
                  <Grid container spacing={1.5}>
                    <Grid item xs={12} md={6}>
                      <TextField
                        label="OSLC/OSMC Base URL"
                        value={newServerPreset.oslc_base_url ?? ""}
                        onChange={(event) => setNewServerPreset((current) => ({ ...current, oslc_base_url: event.target.value || null }))}
                        helperText="Leave blank to use the TWC Base URL for /osmc requests."
                        placeholder="https://twc.example:8111"
                        fullWidth
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <TextField
                        label="OSLC callback URL"
                        value={newServerPreset.oslc_callback_url ?? ""}
                        onChange={(event) => setNewServerPreset((current) => ({ ...current, oslc_callback_url: event.target.value || null }))}
                        fullWidth
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <TextField
                        label="OSLC consumer key"
                        value={newServerPreset.oslc_consumer_key ?? ""}
                        onChange={(event) => setNewServerPreset((current) => ({ ...current, oslc_consumer_key: event.target.value || null }))}
                        fullWidth
                      />
                    </Grid>
                    <Grid item xs={12} md={6}>
                      <TextField
                        label="OSLC consumer secret"
                        type="password"
                        value={newServerPreset.oslc_consumer_secret ?? ""}
                        onChange={(event) => setNewServerPreset((current) => ({ ...current, oslc_consumer_secret: event.target.value || null }))}
                        helperText="Saved on submit; not shown again after reload."
                        fullWidth
                      />
                    </Grid>
                  </Grid>
                </AccordionDetails>
              </Accordion>
              <Button
                variant="contained"
                disabled={!csrfToken || !(newServerPreset.id ?? "").trim() || !newServerPreset.name.trim() || !newServerPreset.base_url.trim() || createServerMutation.isPending}
                onClick={() => createServerMutation.mutate({ ...newServerPreset, id: (newServerPreset.id ?? "").trim(), display_order: servers.length })}
              >
                Add Server
              </Button>
            </Stack>
          </Paper>

          {managedServersQuery.isLoading ? <CircularProgress size={28} /> : null}
          <Stack spacing={1.5}>
            {servers.length ? (
              servers.map((server: ServerProfile) => {
                const draft = serverPresetDrafts[server.id] ?? createServerProfileDraft({
                  name: server.name,
                  base_url: server.base_url,
                  version: server.version,
                  verify_tls: server.verify_tls,
                  ca_bundle_path: server.ca_bundle_path,
                  enabled: server.enabled,
                  display_order: server.display_order,
                  auth_discovery_url: server.auth_discovery_url,
                  auth_authorize_url: server.auth_authorize_url,
                  auth_token_url: server.auth_token_url,
                  auth_login_path: server.auth_login_path,
                  auth_login_port: server.auth_login_port,
                  auth_token_path: server.auth_token_path,
                  auth_client_id: server.auth_client_id,
                  auth_client_secret: null,
                  auth_scope: server.auth_scope ?? "openid",
                  auth_return_url_parameter: server.auth_return_url_parameter ?? "redirect_uri",
                  oslc_base_url: server.oslc_base_url,
                  oslc_consumer_key: server.oslc_consumer_key,
                  oslc_consumer_secret: null,
                  oslc_callback_url: server.oslc_callback_url,
                });
                const serverLooksLikeWorkbench = draft.base_url.trim().replace(/\/$/, "") === workbenchOrigin;
                return (
                  <Paper key={server.id} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                    <Stack spacing={1.5}>
                      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                        <Chip label={`server key: ${server.id}`} variant="outlined" />
                        <Chip label={draft.enabled ? "enabled" : "disabled"} color={draft.enabled ? "success" : "warning"} variant="outlined" />
                        <Chip label={draft.verify_tls ? "TLS verified" : "TLS relaxed"} variant="outlined" />
                      </Stack>
                      <Grid container spacing={1.5}>
                        <Grid item xs={12} md={5}>
                          <TextField
                            label="Cameo plugin server key"
                            value={server.id}
                            fullWidth
                            InputProps={{ readOnly: true }}
                            helperText="Copy this into the Cameo plugin as metadata.serverId."
                          />
                        </Grid>
                        <Grid item xs={12} md={5}>
                          <TextField
                            label="Plugin config line"
                            value={`metadata.serverId=${server.id}`}
                            fullWidth
                            InputProps={{ readOnly: true }}
                          />
                        </Grid>
                        <Grid item xs={12} md={2}>
                          <Button
                            variant="outlined"
                            fullWidth
                            onClick={() => {
                              void navigator.clipboard?.writeText(`metadata.serverId=${server.id}`);
                              setNotice({ severity: "success", message: `Copied metadata.serverId for ${server.id}.` });
                            }}
                          >
                            Copy Key
                          </Button>
                        </Grid>
                      </Grid>
                      <Grid container spacing={1.5}>
                        <Grid item xs={12} md={3}>
                          <TextField
                            label="Name"
                            value={draft.name}
                            onChange={(event) =>
                              setServerPresetDrafts((current) => ({ ...current, [server.id]: { ...draft, name: event.target.value } }))
                            }
                            fullWidth
                          />
                        </Grid>
                        <Grid item xs={12} md={4}>
                          <TextField
                            label="Base URL"
                            value={draft.base_url}
                            onChange={(event) =>
                              setServerPresetDrafts((current) => ({ ...current, [server.id]: { ...draft, base_url: event.target.value } }))
                            }
                            fullWidth
                          />
                        </Grid>
                        <Grid item xs={12} md={2}>
                          <TextField
                            select
                            label="Version"
                            value={draft.version}
                            onChange={(event) =>
                              setServerPresetDrafts((current) => ({
                                ...current,
                                [server.id]: { ...draft, version: event.target.value as ServerProfileInput["version"] },
                              }))
                            }
                            fullWidth
                          >
                            <MenuItem value="2024x">2024x</MenuItem>
                            <MenuItem value="2022x">2022x</MenuItem>
                            <MenuItem value="auto">Auto</MenuItem>
                          </TextField>
                        </Grid>
                        <Grid item xs={12} md={3}>
                          <TextField
                            label="CA bundle path"
                            value={draft.ca_bundle_path ?? ""}
                            onChange={(event) =>
                              setServerPresetDrafts((current) => ({
                                ...current,
                                [server.id]: { ...draft, ca_bundle_path: event.target.value || null },
                              }))
                            }
                            fullWidth
                          />
                        </Grid>
                      </Grid>
                      {serverLooksLikeWorkbench ? (
                        <Alert severity="warning">
                          This Base URL matches the Workbench app. SSO will loop back to Workbench instead of Teamwork Cloud until this is changed to the real TWC URL.
                        </Alert>
                      ) : null}
                      <Accordion variant="outlined" disableGutters>
                        <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                          <Typography fontWeight={700}>TWC AuthServer / SSO overrides</Typography>
                        </AccordionSummary>
                        <AccordionDetails>
                          <Grid container spacing={1.5}>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="OIDC discovery URL"
                                value={draft.auth_discovery_url ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: { ...draft, auth_discovery_url: event.target.value || null },
                                  }))
                                }
                                fullWidth
                              />
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="Authorize URL"
                                value={draft.auth_authorize_url ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: { ...draft, auth_authorize_url: event.target.value || null },
                                  }))
                                }
                                fullWidth
                              />
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="Token URL"
                                value={draft.auth_token_url ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: { ...draft, auth_token_url: event.target.value || null },
                                  }))
                                }
                                fullWidth
                              />
                            </Grid>
                            <Grid item xs={12} md={3}>
                              <TextField
                                label="Login port"
                                type="number"
                                value={draft.auth_login_port ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: {
                                      ...draft,
                                      auth_login_port: event.target.value ? Number.parseInt(event.target.value, 10) : null,
                                    },
                                  }))
                                }
                                fullWidth
                              />
                            </Grid>
                            <Grid item xs={12} md={3}>
                              <TextField
                                label="Scope"
                                value={draft.auth_scope ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: { ...draft, auth_scope: event.target.value || null },
                                  }))
                                }
                                fullWidth
                              />
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="Client ID"
                                value={draft.auth_client_id ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: { ...draft, auth_client_id: event.target.value || null },
                                  }))
                                }
                                fullWidth
                              />
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="Client secret"
                                type="password"
                                value={draft.auth_client_secret ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: { ...draft, auth_client_secret: event.target.value || null },
                                  }))
                                }
                                helperText="Leave blank to keep the saved secret unchanged; enter a value only to set or rotate it."
                                fullWidth
                              />
                            </Grid>
                          </Grid>
                        </AccordionDetails>
                      </Accordion>
                      <Accordion variant="outlined" disableGutters>
                        <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                          <Typography fontWeight={700}>OSLC / RealSwagger overrides</Typography>
                        </AccordionSummary>
                        <AccordionDetails>
                          <Grid container spacing={1.5}>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="OSLC/OSMC Base URL"
                                value={draft.oslc_base_url ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: { ...draft, oslc_base_url: event.target.value || null },
                                  }))
                                }
                                helperText="Leave blank to use the TWC Base URL for /osmc requests."
                                fullWidth
                              />
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="OSLC callback URL"
                                value={draft.oslc_callback_url ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: { ...draft, oslc_callback_url: event.target.value || null },
                                  }))
                                }
                                fullWidth
                              />
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="OSLC consumer key"
                                value={draft.oslc_consumer_key ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: { ...draft, oslc_consumer_key: event.target.value || null },
                                  }))
                                }
                                fullWidth
                              />
                            </Grid>
                            <Grid item xs={12} md={6}>
                              <TextField
                                label="OSLC consumer secret"
                                type="password"
                                value={draft.oslc_consumer_secret ?? ""}
                                onChange={(event) =>
                                  setServerPresetDrafts((current) => ({
                                    ...current,
                                    [server.id]: { ...draft, oslc_consumer_secret: event.target.value || null },
                                  }))
                                }
                                helperText="Leave blank to keep the saved secret unchanged; enter a value only to set or rotate it."
                                fullWidth
                              />
                            </Grid>
                          </Grid>
                        </AccordionDetails>
                      </Accordion>
                      <Stack direction={{ xs: "column", sm: "row" }} spacing={1} useFlexGap flexWrap="wrap" alignItems={{ xs: "stretch", sm: "center" }}>
                        <FormControlLabel
                          control={
                            <Checkbox
                              checked={draft.verify_tls}
                              onChange={(event) =>
                                setServerPresetDrafts((current) => ({ ...current, [server.id]: { ...draft, verify_tls: event.target.checked } }))
                              }
                            />
                          }
                          label="Verify TLS"
                        />
                        <FormControlLabel
                          control={
                            <Checkbox
                              checked={draft.enabled}
                              onChange={(event) =>
                                setServerPresetDrafts((current) => ({ ...current, [server.id]: { ...draft, enabled: event.target.checked } }))
                              }
                            />
                          }
                          label="Enabled"
                        />
                        <Button
                          variant="contained"
                          disabled={!csrfToken || !draft.name.trim() || !draft.base_url.trim() || serverBusy}
                          onClick={() => updateServerMutation.mutate({ serverId: server.id, payload: draft })}
                        >
                          Save Server
                        </Button>
                        <Button
                          variant="text"
                          color="warning"
                          disabled={!csrfToken || serverBusy}
                          onClick={() => deleteServerMutation.mutate(server.id)}
                        >
                          Delete Server
                        </Button>
                      </Stack>
                    </Stack>
                  </Paper>
                );
              })
            ) : (
              <Typography color="text.secondary">No Workbench server profiles have been created yet. Add one here; users will then choose it from the landing page/sign-in flow.</Typography>
            )}
          </Stack>
        </Stack>
      </Paper>
    );
  };

  const renderAuthenticationSettings = () => {
    const status = authManagementStatusQuery.data;
    const userManagementMode = authSettingsDraft.user_management_mode;
    const settingsBusy = updateAuthSettingsMutation.isPending || authManagementStatusQuery.isFetching;
    const localAuthOnlyDisabled =
      userManagementMode === "twc" && !authSettingsDraft.twc_redirect_enabled && !authSettingsDraft.twc_token_enabled;

    return (
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
            <Box>
              <Typography variant="h5">Authentication Type & Settings</Typography>
              <Typography variant="body2" color="text.secondary">
                Choose exactly one sign-in authority. Workbench local users and TWC-managed users are intentionally mutually exclusive.
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Chip
                label={userManagementMode === "local" ? "Mode: local users" : "Mode: TWC users"}
                color={userManagementMode === "local" ? "secondary" : "primary"}
                variant="outlined"
              />
              <Chip
                label={status?.first_admin_setup_required ? "First admin required" : "Auth path ready"}
                color={status?.first_admin_setup_required ? "warning" : "success"}
                variant="outlined"
              />
            </Stack>
          </Stack>

          <Alert severity="info">
            Use local mode for Workbench-managed username/password users, or TWC mode for TWC-managed users. Workbench will not enable both modes at the same time.
          </Alert>
          {status?.first_admin_setup_required ? (
            <Alert severity="warning">
              No local users exist yet. The bootstrap login is <code>admin</code> / <code>admin</code> unless changed in bootstrap env. Rotate that password immediately after first login.
            </Alert>
          ) : null}
          {userManagementMode === "local" ? (
            <Alert severity="warning">
              Local Workbench users do not receive live TWC credentials. Their visible projects and branches come from stored/plugin permission snapshots for the same username and selected server. Live TWC API actions remain unavailable in local mode.
            </Alert>
          ) : (
            <Alert severity="info">
              TWC user-management mode disables local username/password sign-in. Users must authenticate through TWC, and Workbench refreshes project access from the TWC-backed permission workflow.
            </Alert>
          )}
          {authManagementStatusQuery.error ? <Alert severity="error">{errorMessage(authManagementStatusQuery.error)}</Alert> : null}

          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Stack spacing={1.5}>
              <Typography variant="subtitle1">Authentication mode</Typography>
              <TextField
                select
                label="User-management authority"
                value={userManagementMode}
                onChange={(event) => {
                  const mode = event.target.value as WorkbenchAuthSettings["user_management_mode"];
                  setAuthSettingsDraft((current) =>
                    mode === "local"
                      ? {
                          ...current,
                          user_management_mode: "local",
                          local_users_enabled: true,
                          twc_redirect_enabled: false,
                          twc_token_enabled: false,
                        }
                      : {
                          ...current,
                          user_management_mode: "twc",
                          local_users_enabled: false,
                          twc_redirect_enabled: current.twc_redirect_enabled || true,
                          twc_token_enabled: current.twc_token_enabled,
                        },
                  );
                }}
                helperText="Only one authority is active at a time."
                fullWidth
              >
                <MenuItem value="local">Workbench local users</MenuItem>
                <MenuItem value="twc">TWC users</MenuItem>
              </TextField>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1} useFlexGap flexWrap="wrap">
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={authSettingsDraft.local_users_enabled}
                      disabled={userManagementMode === "twc"}
                      onChange={(event) => setAuthSettingsDraft((current) => ({ ...current, local_users_enabled: event.target.checked }))}
                    />
                  }
                  label="Workbench username/password users"
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={authSettingsDraft.twc_redirect_enabled}
                      disabled={userManagementMode === "local"}
                      onChange={(event) => setAuthSettingsDraft((current) => ({ ...current, twc_redirect_enabled: event.target.checked }))}
                    />
                  }
                  label="TWC browser sign-in"
                />
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={authSettingsDraft.twc_token_enabled}
                      disabled={userManagementMode === "local"}
                      onChange={(event) => setAuthSettingsDraft((current) => ({ ...current, twc_token_enabled: event.target.checked }))}
                    />
                  }
                  label="TWC token sign-in"
                />
              </Stack>
              {localAuthOnlyDisabled ? <Alert severity="warning">At least one TWC sign-in method must stay enabled in TWC user-management mode.</Alert> : null}
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
                <Button
                  variant="contained"
                  disabled={!csrfToken || localAuthOnlyDisabled || settingsBusy}
                  onClick={() => updateAuthSettingsMutation.mutate(authSettingsDraft)}
                >
                  Save Authentication Settings
                </Button>
                <Button
                  variant="outlined"
                  startIcon={<RefreshRoundedIcon />}
                  onClick={() => {
                    void authManagementStatusQuery.refetch();
                    void workbenchUsersQuery.refetch();
                  }}
                >
                  Refresh Users
                </Button>
                {settingsBusy ? <CircularProgress size={22} /> : null}
              </Stack>
            </Stack>
          </Paper>
        </Stack>
      </Paper>
    );
  };

  const renderWorkbenchUserManagement = () => {
    const status = authManagementStatusQuery.data;
    const users = workbenchUsersQuery.data ?? [];
    const userBusy = createWorkbenchUserMutation.isPending || updateWorkbenchUserMutation.isPending || deleteWorkbenchUserMutation.isPending;
    const normalizedSearch = workbenchUserSearch.trim().toLowerCase();
    const filteredUsers = normalizedSearch
      ? users.filter((user) =>
          [user.username, user.display_name, user.role]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(normalizedSearch),
        )
      : users;

    return (
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
            <Box>
              <Typography variant="h5">Users</Typography>
              <Typography variant="body2" color="text.secondary">
                Create local Workbench users, search users, rotate passwords, and enable or disable access.
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Chip label={`${status?.local_user_count ?? users.length} local users`} variant="outlined" />
              <Chip
                label={authSettingsDraft.user_management_mode === "local" ? "Local user mode active" : "TWC user mode active"}
                color={authSettingsDraft.user_management_mode === "local" ? "secondary" : "primary"}
                variant="outlined"
              />
            </Stack>
          </Stack>

          {workbenchUsersQuery.error ? <Alert severity="error">{errorMessage(workbenchUsersQuery.error)}</Alert> : null}
          {authSettingsDraft.user_management_mode === "local" ? (
            <Alert severity="warning">
              Local Workbench usernames should match TWC usernames so stored project permissions map cleanly.
            </Alert>
          ) : (
            <Alert severity="info">
              TWC mode is active. Local user records can stay here for audit or future use, but TWC sign-in is the authority.
            </Alert>
          )}

          {isAdmin ? (
            <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Stack spacing={1.5}>
              <Typography variant="subtitle1">Create local Workbench user</Typography>
              <Grid container spacing={1.5}>
                <Grid item xs={12} md={3}>
                  <TextField
                    label="Username"
                    value={newWorkbenchUser.username}
                    onChange={(event) => setNewWorkbenchUser((current) => ({ ...current, username: event.target.value }))}
                    helperText="Match the TWC username for project permissions."
                    fullWidth
                  />
                </Grid>
                <Grid item xs={12} md={3}>
                  <TextField
                    label="Display name"
                    value={newWorkbenchUser.display_name}
                    onChange={(event) => setNewWorkbenchUser((current) => ({ ...current, display_name: event.target.value }))}
                    fullWidth
                  />
                </Grid>
                <Grid item xs={12} md={3}>
                  <TextField
                    label="Temporary password"
                    type="password"
                    value={newWorkbenchUser.password}
                    onChange={(event) => setNewWorkbenchUser((current) => ({ ...current, password: event.target.value }))}
                    helperText="Minimum 12 characters."
                    fullWidth
                  />
                </Grid>
                <Grid item xs={12} md={2}>
                  <TextField
                    select
                    label="Role"
                    value={newWorkbenchUser.role}
                    onChange={(event) => setNewWorkbenchUser((current) => ({ ...current, role: event.target.value as WorkbenchUserCreateRequest["role"] }))}
                    fullWidth
                  >
                    <MenuItem value="user">User</MenuItem>
                    <MenuItem value="group_manager">Group Manager</MenuItem>
                    <MenuItem value="admin">Admin</MenuItem>
                  </TextField>
                </Grid>
                <Grid item xs={12} md={1}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={newWorkbenchUser.enabled}
                        onChange={(event) => setNewWorkbenchUser((current) => ({ ...current, enabled: event.target.checked }))}
                      />
                    }
                    label="Enabled"
                  />
                </Grid>
              </Grid>
              <Button
                variant="contained"
                startIcon={<AccountCircleRoundedIcon />}
                disabled={
                  !csrfToken ||
                  !newWorkbenchUser.username.trim() ||
                  newWorkbenchUser.password.length < 12 ||
                  createWorkbenchUserMutation.isPending
                }
                onClick={() => createWorkbenchUserMutation.mutate(newWorkbenchUser)}
              >
                Create Workbench User
              </Button>
            </Stack>
            </Paper>
          ) : (
            <Alert severity="info">Group managers can search users for group membership. Creating, disabling, deleting, and role changes are administrator-only.</Alert>
          )}

          <TextField
            label="Search users"
            value={workbenchUserSearch}
            onChange={(event) => setWorkbenchUserSearch(event.target.value)}
            helperText="Search username, display name, or role."
            fullWidth
          />

          {workbenchUsersQuery.isLoading ? <CircularProgress size={28} /> : null}
          <Stack spacing={1.5}>
            {filteredUsers.length ? (
              filteredUsers.map((user) => {
                const resetPassword = workbenchPasswordResets[user.username] ?? "";
                const isCurrentUser = user.username.toLowerCase() === (session?.user?.preferred_username ?? "").toLowerCase();
                return (
                  <Paper key={user.username} variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                    <Stack spacing={1.5}>
                      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
                        <Box>
                          <Typography variant="subtitle1">{user.display_name || user.username}</Typography>
                          <Typography variant="body2" color="text.secondary">
                            {user.username} · created {new Date(user.created_at).toLocaleString()}
                            {user.last_login_at ? ` · last login ${new Date(user.last_login_at).toLocaleString()}` : " · never logged in"}
                          </Typography>
                        </Box>
                        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                          <Chip label={user.role} color={user.role === "admin" ? "secondary" : "default"} />
                          <Chip label={user.enabled ? "enabled" : "disabled"} color={user.enabled ? "success" : "warning"} variant="outlined" />
                          {user.password_change_required ? <Chip label="rotate password" color="warning" /> : null}
                          <Chip label={`${user.accessible_project_count} projects`} variant="outlined" />
                          <Chip label={`${user.accessible_branch_count} branches`} variant="outlined" />
                        </Stack>
                      </Stack>
                      {isAdmin ? (
                      <Grid container spacing={1.5} alignItems="center">
                        <Grid item xs={12} md={4}>
                          <TextField
                            label="Reset password"
                            type="password"
                            value={resetPassword}
                            onChange={(event) =>
                              setWorkbenchPasswordResets((current) => ({ ...current, [user.username]: event.target.value }))
                            }
                            helperText="Leave blank unless rotating this user's password."
                            fullWidth
                          />
                        </Grid>
                        <Grid item xs={12} md={8}>
                          <Stack direction={{ xs: "column", sm: "row" }} spacing={1} useFlexGap flexWrap="wrap">
                            <Button
                              variant="outlined"
                              disabled={!csrfToken || userBusy}
                              onClick={() =>
                                updateWorkbenchUserMutation.mutate({
                                  username: user.username,
                                  payload: { enabled: !user.enabled },
                                })
                              }
                            >
                              {user.enabled ? "Disable" : "Enable"}
                            </Button>
                            <Button
                              variant="outlined"
                              disabled={!csrfToken || userBusy}
                              onClick={() =>
                                updateWorkbenchUserMutation.mutate({
                                  username: user.username,
                                  payload: { role: user.role === "admin" ? "user" : "admin" },
                                })
                              }
                            >
                              Make {user.role === "admin" ? "User" : "Admin"}
                            </Button>
                            <Button
                              variant="outlined"
                              disabled={!csrfToken || resetPassword.length < 12 || userBusy}
                              onClick={() =>
                                updateWorkbenchUserMutation.mutate({
                                  username: user.username,
                                  payload: { password: resetPassword },
                                })
                              }
                            >
                              Reset Password
                            </Button>
                            <Button
                              variant="text"
                              color="warning"
                              disabled={!csrfToken || isCurrentUser || userBusy}
                              onClick={() => deleteWorkbenchUserMutation.mutate(user.username)}
                            >
                              Delete
                            </Button>
                          </Stack>
                        </Grid>
                      </Grid>
                      ) : null}
                    </Stack>
                  </Paper>
                );
              })
            ) : (
              <Typography color="text.secondary">
                {users.length ? "No users match that search." : "No local Workbench users exist yet."}
              </Typography>
            )}
          </Stack>
        </Stack>
      </Paper>
    );
  };

  const renderCacheIngestToken = () => {
    const sourceLabel =
      cacheIngestTokenStatus?.source === "shared"
        ? "Encrypted app storage"
        : cacheIngestTokenStatus?.source === "config"
          ? "Legacy environment fallback"
          : "Not configured";

    return (
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
            <Box>
              <Typography variant="h5">Plugin Ingest Token</Typography>
              <Typography variant="body2" color="text.secondary">
                Generate the Cameo plugin write token here. Workbench stores the app-managed token encrypted, and the plugin uses it to send model snapshots and deltas into the cache ingest API.
              </Typography>
            </Box>
            <Stack direction="row" spacing={1}>
              <Button
                variant="outlined"
                startIcon={<RefreshRoundedIcon />}
                onClick={() => queryClient.invalidateQueries({ queryKey: ["workspace-cache-ingest-token", ...sessionCacheKey] })}
              >
                Refresh Token Status
              </Button>
            </Stack>
          </Stack>
          {cacheIngestTokenQuery.isLoading ? <CircularProgress size={28} /> : null}
          {cacheIngestTokenQuery.error ? <Alert severity="error">{errorMessage(cacheIngestTokenQuery.error)}</Alert> : null}
          {cacheIngestTokenStatus ? (
            <>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                <Chip
                  label={cacheIngestTokenStatus.configured ? "Token configured" : "Token not configured"}
                  color={cacheIngestTokenStatus.configured ? "success" : "warning"}
                />
                <Chip label={sourceLabel} variant="outlined" />
                {cacheIngestTokenStatus.token_hint ? <Chip label={cacheIngestTokenStatus.token_hint} variant="outlined" /> : null}
              </Stack>
              {cacheIngestTokenStatus.message ? <Alert severity={cacheIngestTokenStatus.source === "config" ? "warning" : "info"}>{cacheIngestTokenStatus.message}</Alert> : null}
              <TextField
                label="Save exact plugin ingest token"
                type="password"
                value={manualCacheIngestToken}
                onChange={(event) => setManualCacheIngestToken(event.target.value)}
                helperText="Use this when the Cameo plugin should start with a known token instead of a randomly generated one."
                fullWidth
              />
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
                <Button
                  variant="outlined"
                  disabled={!csrfToken || !manualCacheIngestToken.trim() || storeCacheIngestTokenMutation.isPending}
                  onClick={() => storeCacheIngestTokenMutation.mutate()}
                >
                  Save Exact Token
                </Button>
                <Button
                  variant="contained"
                  disabled={!csrfToken || rotateCacheIngestTokenMutation.isPending}
                  onClick={() => rotateCacheIngestTokenMutation.mutate()}
                >
                  {cacheIngestTokenStatus.configured ? "Rotate Token" : "Generate Token"}
                </Button>
                <Button
                  variant="outlined"
                  disabled={!csrfToken || cacheIngestTokenStatus.source !== "shared" || revealCacheIngestTokenMutation.isPending}
                  onClick={() => revealCacheIngestTokenMutation.mutate()}
                >
                  Reveal Current Token
                </Button>
                <Button
                  variant="text"
                  color="warning"
                  disabled={!csrfToken || cacheIngestTokenStatus.source !== "shared" || clearCacheIngestTokenMutation.isPending}
                  onClick={() => clearCacheIngestTokenMutation.mutate()}
                >
                  Clear App-Managed Token
                </Button>
                {storeCacheIngestTokenMutation.isPending || rotateCacheIngestTokenMutation.isPending || revealCacheIngestTokenMutation.isPending || clearCacheIngestTokenMutation.isPending ? <CircularProgress size={24} /> : null}
              </Stack>
              {cacheIngestTokenStatus.updated_at ? (
                <Typography variant="caption" color="text.secondary">
                  Last updated {new Date(cacheIngestTokenStatus.updated_at).toLocaleString()}.
                </Typography>
              ) : null}
              {revealedCacheIngestToken ? (
                <>
                  <Alert severity="success">
                    Copy this token into the Cameo plugin. Workbench stores the app-managed token encrypted; administrators can reveal it here when needed.
                  </Alert>
                  <TextField
                    label="Plugin ingest token"
                    value={revealedCacheIngestToken}
                    fullWidth
                    InputProps={{ readOnly: true }}
                  />
                </>
              ) : null}
            </>
          ) : null}
        </Stack>
      </Paper>
    );
  };

  const renderPermissionInventoryStatus = () => {
    const status = permissionInventoryStatusQuery.data;
    const colorByState: Record<ServerPermissionInventoryStatus["state"], "success" | "warning" | "info" | "error" | "default"> = {
      clean: "success",
      dirty: "warning",
      refreshing: "info",
      failed: "error",
      missing: "default",
    };
    return (
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
            <Box>
              <Typography variant="h5">TWC Permission Inventory</Typography>
              <Typography variant="body2" color="text.secondary">
                Server-wide roles and group scopes are refreshed by a background job. Administrator login and uploads do not wait for this scan.
              </Typography>
            </Box>
            {status ? <Chip label={status.state.toUpperCase()} color={colorByState[status.state]} /> : null}
          </Stack>
          {permissionInventoryStatusQuery.error ? <Alert severity="error">{errorMessage(permissionInventoryStatusQuery.error)}</Alert> : null}
          {status ? (
            <>
              <Alert severity={status.state === "failed" ? "error" : status.state === "dirty" || status.state === "missing" ? "warning" : "info"}>
                {status.message}
              </Alert>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                <Chip label={`${status.role_count} roles`} variant="outlined" />
                <Chip label={`${status.group_count} groups`} variant="outlined" />
                <Chip label={`${status.active_server_administrator_count} active server admins`} variant="outlined" />
                <Chip label={`${status.successful_refresh_count} successful refreshes`} color="success" variant="outlined" />
                <Chip label={`${status.failed_refresh_count} failed refreshes`} color={status.failed_refresh_count ? "error" : "default"} variant="outlined" />
                <Chip label={`${status.consecutive_failure_count} consecutive failures`} color={status.consecutive_failure_count ? "error" : "default"} variant="outlined" />
                <Chip label={status.alert_forwarding_configured ? "Failure alerts configured" : "Failure alerts not configured"} color={status.alert_forwarding_configured ? "success" : "default"} variant="outlined" />
                <Chip label={`${status.last_affected_user_count} user snapshots queued`} variant="outlined" />
                <Chip label={status.current_user_can_refresh ? "TWC Server Administrator" : "App administrator only"} variant="outlined" />
              </Stack>
              {status.warning ? <Alert severity="warning">{status.warning}</Alert> : null}
              <Typography variant="body2" color="text.secondary">
                Captured: {status.captured_at ? new Date(status.captured_at).toLocaleString() : "never"}
                {status.refresh_due_at ? ` · Refresh due: ${new Date(status.refresh_due_at).toLocaleString()}` : ""}
                {status.inventory_age_seconds !== null ? ` · Inventory age: ${Math.floor(status.inventory_age_seconds / 60)} minutes` : ""}
                {status.last_duration_ms !== null ? ` · Last duration: ${(status.last_duration_ms / 1000).toFixed(1)} seconds` : ""}
              </Typography>
              {status.last_job_id ? (
                <Typography variant="body2" color="text.secondary">
                  Last job: {status.last_job_id} ({status.last_job_status ?? "unknown"})
                  {status.last_attempt_at ? ` · Attempted ${new Date(status.last_attempt_at).toLocaleString()}` : ""}
                  {status.last_triggered_by ? ` · Triggered by ${status.last_triggered_by}` : ""}
                </Typography>
              ) : null}
              {status.last_failure ? <Alert severity="error">{status.last_failure}</Alert> : null}
              {status.recent_audits.length ? (
                <Box>
                  <Typography variant="subtitle2" gutterBottom>Recent inventory audit</Typography>
                  <Stack spacing={0.75}>
                    {status.recent_audits.slice(0, 5).map((audit) => (
                      <Typography key={audit.id} variant="caption" color={audit.status === "failed" ? "error" : "text.secondary"}>
                        {new Date(audit.created_at).toLocaleString()} · {audit.status} · {audit.reason} · {audit.triggered_by} · {audit.duration_ms} ms · roles {audit.previous_role_count}→{audit.current_role_count} · groups {audit.previous_group_count}→{audit.current_group_count} · users queued {audit.affected_user_count}
                        {audit.error ? ` · ${audit.error}` : ""}
                      </Typography>
                    ))}
                  </Stack>
                </Box>
              ) : null}
            </>
          ) : permissionInventoryStatusQuery.isLoading ? <CircularProgress size={24} /> : null}
          <Box>
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              disabled={permissionInventoryStatusQuery.isFetching}
              onClick={() => void permissionInventoryStatusQuery.refetch()}
            >
              Refresh Status
            </Button>
            <Button
              sx={{ ml: 1 }}
              variant="contained"
              startIcon={<RefreshRoundedIcon />}
              disabled={!csrfToken || !status?.current_user_can_refresh || status?.state === "refreshing" || retryPermissionInventoryMutation.isPending}
              onClick={() => retryPermissionInventoryMutation.mutate()}
            >
              Retry Now
            </Button>
            {retryPermissionInventoryMutation.isPending ? <CircularProgress size={22} sx={{ ml: 1 }} /> : null}
          </Box>
        </Stack>
      </Paper>
    );
  };

  const renderWorkbenchProjectAccessAssignment = () => {
    const localUsers = workbenchUsersQuery.data ?? [];
    const localGroups = workbenchGroupsQuery.data ?? [];
    const assignmentProject = selectedProjectId
      ? projects.find((project) => project.id === selectedProjectId) ?? null
      : null;
    const assignmentBranches = assignmentProject?.branches.filter((branch) => branch.id === selectedBranchId) ?? [];
    const assignmentBranchOptions = assignmentBranches.length
      ? assignmentBranches
      : selectedBranchId
        ? [{ id: selectedBranchId, name: selectedBranchId }]
        : [];
    const principalOptions = workbenchAccessAssignment.principal_type === "group"
      ? localGroups.filter((group) => group.enabled).map((group) => ({ value: group.name, label: `${group.name} (${group.users.length} users)` }))
      : localUsers.filter((user) => user.enabled).map((user) => ({ value: user.username, label: user.display_name ? `${user.display_name} (${user.username})` : user.username }));
    if (!canAssignProjectAccess || !selectedProjectId || !selectedBranchId || !assignmentProject) {
      return (
        <Alert severity="info">
          Select a project branch. Workbench administrators can manage Workbench-local access for stored projects; TWC project access administrators can manage only branches where TWC grants access-administration rights.
        </Alert>
      );
    }
    return (
      <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
        <Stack spacing={1.5}>
          <Box>
            <Typography variant="subtitle1">Assign project access</Typography>
            <Typography variant="body2" color="text.secondary">
              Grant or revoke WorkBench-local access for the currently selected project branch. Group assignment expands to the group&apos;s current users.
            </Typography>
          </Box>
          <Alert severity="info">
            This affects WorkBench visibility only. It does not change Teamwork Cloud permissions or create live TWC credentials. Workbench administrators always retain Workbench cache visibility; TWC project administrators are scoped to branches where TWC grants access-administration rights.
          </Alert>
          <Grid container spacing={1.5}>
            <Grid item xs={12} md={2}>
              <TextField
                select
                label="Assign to"
                value={workbenchAccessAssignment.principal_type}
                onChange={(event) =>
                  setWorkbenchAccessAssignment((current) => ({
                    ...current,
                    principal_type: event.target.value as "user" | "group",
                    principal_name: "",
                  }))
                }
                fullWidth
              >
                <MenuItem value="user">User</MenuItem>
                <MenuItem value="group">Group</MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={12} md={3}>
              <TextField
                select={canManageGroups}
                label={workbenchAccessAssignment.principal_type === "group" ? "Group" : "User"}
                value={workbenchAccessAssignment.principal_name}
                onChange={(event) => setWorkbenchAccessAssignment((current) => ({ ...current, principal_name: event.target.value }))}
                helperText={canManageGroups ? undefined : "Enter an existing Workbench username or group name."}
                fullWidth
              >
                {canManageGroups ? [
                  <MenuItem key="empty-principal" value="">
                    <em>Select {workbenchAccessAssignment.principal_type}</em>
                  </MenuItem>,
                  ...principalOptions.map((option) => (
                    <MenuItem key={`${workbenchAccessAssignment.principal_type}-${option.value}`} value={option.value}>
                      {option.label}
                    </MenuItem>
                  )),
                ] : null}
              </TextField>
            </Grid>
            <Grid item xs={12} md={3}>
              <TextField
                select
                label="Project"
                value={selectedProjectId}
                onChange={() => undefined}
                disabled
                fullWidth
              >
                <MenuItem value={assignmentProject.id}>
                  {assignmentProject.name} ({assignmentBranchOptions.length || 1} branch)
                </MenuItem>
              </TextField>
            </Grid>
            <Grid item xs={12} md={2}>
              <TextField
                select
                label="Branch"
                value={selectedBranchId}
                onChange={() => undefined}
                disabled
                fullWidth
              >
                {assignmentBranchOptions.map((branch) => (
                  <MenuItem key={`assign-branch-${branch.id}`} value={branch.id}>
                    {branch.name}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid item xs={12} md={2}>
              <Stack spacing={0.5}>
                <FormControlLabel
                  control={<Checkbox checked={workbenchAccessAssignment.accessible} onChange={(event) => setWorkbenchAccessAssignment((current) => ({ ...current, accessible: event.target.checked }))} />}
                  label="Visible"
                />
                <FormControlLabel
                  control={<Checkbox checked={workbenchAccessAssignment.editable} onChange={(event) => setWorkbenchAccessAssignment((current) => ({ ...current, editable: event.target.checked }))} />}
                  label="Editable"
                />
                <FormControlLabel
                  control={<Checkbox checked={workbenchAccessAssignment.admin_access} onChange={(event) => setWorkbenchAccessAssignment((current) => ({ ...current, admin_access: event.target.checked }))} />}
                  label="Access admin"
                />
              </Stack>
            </Grid>
          </Grid>
          <Button
            variant="contained"
            disabled={
              !csrfToken ||
              !workbenchAccessAssignment.principal_name ||
              !selectedProjectId ||
              !selectedBranchId ||
              assignWorkbenchProjectAccessMutation.isPending
            }
            onClick={() =>
              assignWorkbenchProjectAccessMutation.mutate({
                ...workbenchAccessAssignment,
                project_id: selectedProjectId,
                branch_id: selectedBranchId,
              })
            }
          >
            Apply Project Access
          </Button>
        </Stack>
      </Paper>
    );
  };

  const renderWorkbenchGroupManagement = () => {
    const status = permissionInventoryStatusQuery.data;
    const inventory: ServerPermissionInventoryDetails | null = permissionInventoryDetailsQuery.data ?? null;
    const normalizedSearch = twcGroupSearch.trim().toLowerCase();
    const localGroups = workbenchGroupsQuery.data ?? [];
    const localUsers = workbenchUsersQuery.data ?? [];
    const groupBusy = createWorkbenchGroupMutation.isPending || updateWorkbenchGroupMutation.isPending || deleteWorkbenchGroupMutation.isPending;
    const groups = inventory?.groups ?? [];
    const roles = inventory?.roles ?? [];
    const filteredLocalGroups = normalizedSearch
      ? localGroups.filter((group) =>
          [group.name, group.description, ...group.users]
            .join(" ")
            .toLowerCase()
            .includes(normalizedSearch),
        )
      : localGroups;
    const filteredGroups = normalizedSearch
      ? groups.filter((group) => inventoryRecordSearchText(group).includes(normalizedSearch))
      : groups;
    const filteredRoles = normalizedSearch
      ? roles.filter((role) => inventoryRecordSearchText(role).includes(normalizedSearch))
      : roles;

    return (
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
            <Box>
              <Typography variant="h5">Groups</Typography>
              <Typography variant="body2" color="text.secondary">
                Manage local Workbench groups. Administrators can also import TWC users, groups, roles, and scoped project permissions.
              </Typography>
            </Box>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
              <Chip label={`${localGroups.length} local groups`} variant="outlined" />
              {isAdmin ? <Chip label={`${status?.group_count ?? groups.length} TWC groups`} variant="outlined" /> : null}
              {isAdmin ? <Chip label={`${status?.role_count ?? roles.length} TWC roles`} variant="outlined" /> : null}
              {status ? <Chip label={status.state.toUpperCase()} color={status.state === "clean" ? "success" : status.state === "failed" ? "error" : "warning"} /> : null}
            </Stack>
          </Stack>

          <Alert severity="info">
            Local Workbench groups organize local users. Group managers can only manage groups they are already assigned to.
          </Alert>
          {workbenchGroupsQuery.error ? <Alert severity="error">{errorMessage(workbenchGroupsQuery.error)}</Alert> : null}
          {isAdmin && permissionInventoryStatusQuery.error ? <Alert severity="error">{errorMessage(permissionInventoryStatusQuery.error)}</Alert> : null}
          {isAdmin && permissionInventoryDetailsQuery.error ? <Alert severity="error">{errorMessage(permissionInventoryDetailsQuery.error)}</Alert> : null}
          {isAdmin && status?.message ? <Alert severity={status.state === "failed" ? "error" : "info"}>{status.message}</Alert> : null}

          {isAdmin ? (
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Stack spacing={1.5}>
              <Typography variant="subtitle1">Create local Workbench group</Typography>
              <Grid container spacing={1.5}>
                <Grid item xs={12} md={3}>
                  <TextField
                    label="Group name"
                    value={newWorkbenchGroup.name}
                    onChange={(event) => setNewWorkbenchGroup((current) => ({ ...current, name: event.target.value }))}
                    fullWidth
                  />
                </Grid>
                <Grid item xs={12} md={5}>
                  <TextField
                    label="Description"
                    value={newWorkbenchGroup.description}
                    onChange={(event) => setNewWorkbenchGroup((current) => ({ ...current, description: event.target.value }))}
                    fullWidth
                  />
                </Grid>
                <Grid item xs={12} md={3}>
                  <TextField
                    select
                    label="Add initial user"
                    value=""
                    onChange={(event) => {
                      const username = event.target.value;
                      setNewWorkbenchGroup((current) => ({
                        ...current,
                        users: current.users.includes(username) ? current.users : [...current.users, username],
                      }));
                    }}
                    disabled={!localUsers.length}
                    fullWidth
                  >
                    <MenuItem value="">
                      <em>Select user</em>
                    </MenuItem>
                    {localUsers.map((user) => (
                      <MenuItem key={`new-group-user-${user.username}`} value={user.username}>
                        {user.display_name || user.username}
                      </MenuItem>
                    ))}
                  </TextField>
                </Grid>
                <Grid item xs={12} md={1}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={newWorkbenchGroup.enabled}
                        onChange={(event) => setNewWorkbenchGroup((current) => ({ ...current, enabled: event.target.checked }))}
                      />
                    }
                    label="Enabled"
                  />
                </Grid>
              </Grid>
              {newWorkbenchGroup.users.length ? (
                <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                  {newWorkbenchGroup.users.map((username) => (
                    <Chip
                      key={`new-group-selected-${username}`}
                      label={username}
                      onDelete={() => setNewWorkbenchGroup((current) => ({ ...current, users: current.users.filter((item) => item !== username) }))}
                    />
                  ))}
                </Stack>
              ) : null}
              <Button
                variant="contained"
                disabled={!csrfToken || !newWorkbenchGroup.name.trim() || groupBusy}
                onClick={() => createWorkbenchGroupMutation.mutate(newWorkbenchGroup)}
              >
                Create Workbench Group
              </Button>
            </Stack>
          </Paper>
          ) : (
            <Alert severity="info">Group managers can edit membership for groups they already belong to. Creating or deleting groups is administrator-only.</Alert>
          )}

          <TextField
            label="Search groups and roles"
            value={twcGroupSearch}
            onChange={(event) => setTwcGroupSearch(event.target.value)}
            helperText={isAdmin ? "Search local groups, TWC group names, role names, ids, descriptions, members, or raw TWC fields." : "Search groups you are assigned to."}
            fullWidth
          />

          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Stack spacing={1.5}>
              <Typography variant="subtitle1">Local Workbench Groups</Typography>
              {workbenchGroupsQuery.isLoading ? <CircularProgress size={24} /> : null}
              {filteredLocalGroups.length ? (
                filteredLocalGroups.map((group: WorkbenchGroupSummary) => {
                  const draftUser = workbenchGroupUserDrafts[group.name] ?? "";
                  return (
                    <Paper key={group.name} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                      <Stack spacing={1.25}>
                        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
                          <Box>
                            <Typography variant="subtitle2">{group.name}</Typography>
                            <Typography variant="caption" color="text.secondary">
                              {group.description || "No description"} · {group.users.length} user{group.users.length === 1 ? "" : "s"} · updated {new Date(group.updated_at).toLocaleString()}
                            </Typography>
                          </Box>
                          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                            <Chip label={group.enabled ? "enabled" : "disabled"} color={group.enabled ? "success" : "warning"} variant="outlined" size="small" />
                            <Button
                              size="small"
                              variant="outlined"
                              disabled={!csrfToken || groupBusy}
                              onClick={() => updateWorkbenchGroupMutation.mutate({ name: group.name, payload: { enabled: !group.enabled } })}
                            >
                              {group.enabled ? "Disable" : "Enable"}
                            </Button>
                            {isAdmin ? (
                              <Button
                                size="small"
                                color="warning"
                                disabled={!csrfToken || groupBusy}
                                onClick={() => deleteWorkbenchGroupMutation.mutate(group.name)}
                              >
                                Delete
                              </Button>
                            ) : null}
                          </Stack>
                        </Stack>
                        <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
                          {group.users.length ? group.users.map((username) => (
                            <Chip
                              key={`${group.name}-${username}`}
                              label={username}
                              size="small"
                              onDelete={
                                csrfToken && !groupBusy
                                  ? () => updateWorkbenchGroupMutation.mutate({
                                      name: group.name,
                                      payload: { users: group.users.filter((item) => item !== username) },
                                    })
                                  : undefined
                              }
                            />
                          )) : <Typography variant="caption" color="text.secondary">No users added yet.</Typography>}
                        </Stack>
                        <Stack direction={{ xs: "column", sm: "row" }} spacing={1} alignItems={{ xs: "stretch", sm: "center" }}>
                          <TextField
                            select
                            size="small"
                            label="Add user"
                            value={draftUser}
                            onChange={(event) => setWorkbenchGroupUserDrafts((current) => ({ ...current, [group.name]: event.target.value }))}
                            sx={{ minWidth: 240 }}
                          >
                            <MenuItem value="">
                              <em>Select user</em>
                            </MenuItem>
                            {localUsers
                              .filter((user) => !group.users.includes(user.username))
                              .map((user) => (
                                <MenuItem key={`${group.name}-available-${user.username}`} value={user.username}>
                                  {user.display_name || user.username}
                                </MenuItem>
                              ))}
                          </TextField>
                          <Button
                            variant="outlined"
                            disabled={!csrfToken || !draftUser || groupBusy}
                            onClick={() => updateWorkbenchGroupMutation.mutate({ name: group.name, payload: { users: [...group.users, draftUser] } })}
                          >
                            Add User
                          </Button>
                        </Stack>
                      </Stack>
                    </Paper>
                  );
                })
              ) : (
                <Typography variant="body2" color="text.secondary">
                  {localGroups.length ? "No local Workbench groups match that search." : "No local Workbench groups exist yet."}
                </Typography>
              )}
            </Stack>
          </Paper>

          {isAdmin ? (
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
            <Button
              variant="contained"
              startIcon={<RefreshRoundedIcon />}
              disabled={!csrfToken || !status?.current_user_can_refresh || status?.state === "refreshing" || retryPermissionInventoryMutation.isPending}
              onClick={() => retryPermissionInventoryMutation.mutate()}
            >
              Import TWC Users & Groups
            </Button>
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              disabled={permissionInventoryStatusQuery.isFetching || permissionInventoryDetailsQuery.isFetching}
              onClick={() => {
                void permissionInventoryStatusQuery.refetch();
                void permissionInventoryDetailsQuery.refetch();
              }}
            >
              Refresh List
            </Button>
            {retryPermissionInventoryMutation.isPending || permissionInventoryDetailsQuery.isLoading ? <CircularProgress size={22} /> : null}
          </Stack>
          ) : null}

          {isAdmin ? (
          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, height: "100%" }}>
                <Stack spacing={1.5}>
                  <Typography variant="subtitle1">Imported TWC Groups</Typography>
                  {filteredGroups.length ? (
                    filteredGroups.slice(0, 50).map((group, index) => {
                      const memberCount = inventoryMemberCount(group);
                      return (
                        <Paper key={`group-${index}-${inventoryRecordTitle(group, "group")}`} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                          <Typography variant="subtitle2">{inventoryRecordTitle(group, `Group ${index + 1}`)}</Typography>
                          {inventoryRecordSubtitle(group) ? (
                            <Typography variant="caption" color="text.secondary">{inventoryRecordSubtitle(group)}</Typography>
                          ) : null}
                          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                            {memberCount !== null ? <Chip label={`${memberCount} direct entries`} size="small" variant="outlined" /> : null}
                            {inventoryTextValue(group, ["ID", "id", "key"]) ? <Chip label={inventoryTextValue(group, ["ID", "id", "key"])} size="small" variant="outlined" /> : null}
                          </Stack>
                        </Paper>
                      );
                    })
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      {groups.length ? "No groups match that search." : "No imported groups are stored yet. Run Import TWC Users & Groups as a TWC Server Administrator."}
                    </Typography>
                  )}
                  {filteredGroups.length > 50 ? <Typography variant="caption" color="text.secondary">Showing first 50 matching groups. Narrow the search for more precision.</Typography> : null}
                </Stack>
              </Paper>
            </Grid>
            <Grid item xs={12} md={6}>
              <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, height: "100%" }}>
                <Stack spacing={1.5}>
                  <Typography variant="subtitle1">Imported TWC Roles</Typography>
                  {filteredRoles.length ? (
                    filteredRoles.slice(0, 50).map((role, index) => (
                      <Paper key={`role-${index}-${inventoryRecordTitle(role, "role")}`} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                        <Typography variant="subtitle2">{inventoryRecordTitle(role, `Role ${index + 1}`)}</Typography>
                        {inventoryRecordSubtitle(role) ? (
                          <Typography variant="caption" color="text.secondary">{inventoryRecordSubtitle(role)}</Typography>
                        ) : null}
                        <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap" sx={{ mt: 1 }}>
                          {inventoryTextValue(role, ["ID", "id", "key"]) ? <Chip label={inventoryTextValue(role, ["ID", "id", "key"])} size="small" variant="outlined" /> : null}
                          {inventoryTextValue(role, ["resourceID", "resourceId", "scope"]) ? <Chip label={inventoryTextValue(role, ["resourceID", "resourceId", "scope"])} size="small" variant="outlined" /> : null}
                        </Stack>
                      </Paper>
                    ))
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      {roles.length ? "No roles match that search." : "No imported roles are stored yet. Run Import TWC Users & Groups as a TWC Server Administrator."}
                    </Typography>
                  )}
                  {filteredRoles.length > 50 ? <Typography variant="caption" color="text.secondary">Showing first 50 matching roles. Narrow the search for more precision.</Typography> : null}
                </Stack>
              </Paper>
            </Grid>
          </Grid>
          ) : null}
        </Stack>
      </Paper>
    );
  };

  const renderTombstoneAudit = () => {
    const records: Array<
      | { kind: "Branch"; created_at: string; record: BranchTombstoneRecord }
      | { kind: "Project"; created_at: string; record: ProjectTombstoneRecord }
    > = [
      ...(branchTombstonesQuery.data ?? []).map((record) => ({ kind: "Branch" as const, created_at: record.created_at, record })),
      ...(projectTombstonesQuery.data ?? []).map((record) => ({ kind: "Project" as const, created_at: record.created_at, record })),
    ].sort((left, right) => right.created_at.localeCompare(left.created_at));
    return (
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
            <Box>
              <Typography variant="h5">Stored Project Removal Audit</Typography>
              <Typography variant="body2" color="text.secondary">
                Revision-guarded tombstones remove cached branches and their stored grants atomically. These audit records remain after removal.
              </Typography>
            </Box>
            <Button
              variant="outlined"
              startIcon={<RefreshRoundedIcon />}
              disabled={branchTombstonesQuery.isFetching || projectTombstonesQuery.isFetching}
              onClick={() => {
                void branchTombstonesQuery.refetch();
                void projectTombstonesQuery.refetch();
              }}
            >
              Refresh Audit
            </Button>
          </Stack>
          {branchTombstonesQuery.error ? <Alert severity="error">{errorMessage(branchTombstonesQuery.error)}</Alert> : null}
          {projectTombstonesQuery.error ? <Alert severity="error">{errorMessage(projectTombstonesQuery.error)}</Alert> : null}
          {records.length ? (
            <Stack spacing={1}>
              {records.slice(0, 10).map((item) => (
                <Paper key={`${item.kind}-${item.record.id}`} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
                  <Typography variant="subtitle2">
                    {item.kind}: {item.record.project_name || item.record.project_id}
                    {item.kind === "Branch" ? ` / ${item.record.branch_name || item.record.branch_id}` : ` / ${item.record.branch_ids.length} branches`}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {new Date(item.created_at).toLocaleString()} · {item.record.source_user} · {item.record.reason}
                  </Typography>
                </Paper>
              ))}
            </Stack>
          ) : branchTombstonesQuery.isLoading || projectTombstonesQuery.isLoading ? <CircularProgress size={24} /> : (
            <Typography variant="body2" color="text.secondary">No stored project or branch removals have been recorded.</Typography>
          )}
        </Stack>
      </Paper>
    );
  };

  const renderDeveloperApi = () => (
    <Stack spacing={2}>
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Typography variant="h5">Developer API</Typography>
          <Typography variant="body2" color="text.secondary">
            Workbench exposes a stored-model API for scripts, notebooks, AI agents, and integration services. Use a personal API key from this page or from Settings, then call the cache manifest first to discover the available route set.
          </Typography>
          <Alert severity="info">
            Cameo plugin snapshots are the model source. TWC REST is used for permission validation only; Workbench does not build partial model or element caches from REST.
          </Alert>
          <Typography variant="caption" color="text.secondary">
            These are full standalone Python scripts, not snippets. The current Workbench host and selected project context are prefilled when available. The matching repository files live under the examples folder too.
          </Typography>
          <Stack spacing={1.25}>
            {developerApiExamples.map((example) => (
              <Accordion
                key={example.title}
                disableGutters
                sx={{
                  border: 1,
                  borderColor: "divider",
                  borderRadius: 2,
                  "&:before": { display: "none" },
                }}
              >
                <AccordionSummary expandIcon={<ExpandMoreRoundedIcon />}>
                  <Stack direction={{ xs: "column", md: "row" }} spacing={1} alignItems={{ xs: "flex-start", md: "center" }} sx={{ width: "100%" }}>
                    <Stack spacing={0.25} sx={{ flex: 1 }}>
                      <Typography variant="subtitle1">{example.title}</Typography>
                      <Typography variant="caption" color="text.secondary">
                        {example.description}
                      </Typography>
                    </Stack>
                    <Chip label="Full Python example" size="small" variant="outlined" />
                  </Stack>
                </AccordionSummary>
                <AccordionDetails>
                  <TextField
                    label={`Python script: ${example.title}`}
                    value={example.value}
                    fullWidth
                    multiline
                    minRows={example.minRows}
                    InputProps={{ readOnly: true }}
                  />
                </AccordionDetails>
              </Accordion>
            ))}
          </Stack>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip label="read -> cache reads" />
            <Chip label="write -> cache ingest" variant="outlined" />
            <Chip label="edit -> plugin-backed cache edits" variant="outlined" />
          </Stack>
        </Stack>
      </Paper>
      {renderCacheApiKeys()}
    </Stack>
  );

  const renderWorkbenchAgentSettings = () => (
    <Paper sx={{ p: 3, borderRadius: 2 }}>
      <Stack spacing={2}>
        <Box>
          <Typography variant="h5">Workbench Agent Connection</Typography>
          <Typography variant="body2" color="text.secondary">
            Map an Open WebUI model into Workbench Agent. Every chat uses integrity-validated, query-routed evidence from the single authoritative 3DS_KB plus the current user&apos;s permission-scoped branch model snapshot.
          </Typography>
        </Box>
        {workbenchAgentStatusQuery.error ? <Alert severity="error">{errorMessage(workbenchAgentStatusQuery.error)}</Alert> : null}
        {workbenchAgentModelsQuery.error ? <Alert severity="error">{errorMessage(workbenchAgentModelsQuery.error)}</Alert> : null}
        <Alert severity="info">
          Workbench Agent uses your current Workbench permissions. It waits for both files to finish processing, explicitly instructs the selected model to retrieve 3DS guidance before answering Workbench/Cameo questions, and keeps branch facts scoped to data this user can read.
        </Alert>
        <Grid container spacing={2}>
          <Grid item xs={12} md={6}>
            <TextField
              label="Open WebUI Base URL"
              value={agentBaseUrlDraft}
              onChange={(event) => setAgentBaseUrlDraft(event.target.value)}
              helperText="Use the root Open WebUI host, like https://openwebui.company.com"
              fullWidth
            />
          </Grid>
          <Grid item xs={12} md={6}>
            <TextField
              label="Open WebUI API Key"
              type="password"
              value={agentApiKeyDraft}
              onChange={(event) => setAgentApiKeyDraft(event.target.value)}
              helperText={workbenchAgentStatus?.has_api_key ? "Leave blank to keep the saved API key, or paste a new one to rotate it." : "Required the first time you save this Open WebUI connection."}
              fullWidth
            />
          </Grid>
        </Grid>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
          <Button
            variant="contained"
            startIcon={<SaveRoundedIcon />}
            disabled={!csrfToken || saveWorkbenchAgentConfigMutation.isPending || !agentBaseUrlDraft.trim()}
            onClick={() => saveWorkbenchAgentConfigMutation.mutate()}
          >
            {workbenchAgentStatus?.configured ? "Save Mapping" : "Save Connection"}
          </Button>
          <Button
            variant="outlined"
            startIcon={<RefreshRoundedIcon />}
            disabled={!workbenchAgentStatus?.configured || workbenchAgentModelsQuery.isFetching}
            onClick={() => void workbenchAgentModelsQuery.refetch()}
          >
            Load Models
          </Button>
          <Button
            color="error"
            variant="outlined"
            disabled={!workbenchAgentStatus?.configured || clearWorkbenchAgentConfigMutation.isPending || !csrfToken}
            onClick={() => clearWorkbenchAgentConfigMutation.mutate()}
          >
            Clear Mapping
          </Button>
          {saveWorkbenchAgentConfigMutation.isPending || clearWorkbenchAgentConfigMutation.isPending || workbenchAgentModelsQuery.isFetching ? (
            <CircularProgress size={22} />
          ) : null}
        </Stack>
        <TextField
          select
          label="Mapped Open WebUI Agent / Model"
          value={agentSelectedModelId}
          onChange={(event) => {
            const nextId = event.target.value;
            const entry = workbenchAgentModels.find((candidate) => candidate.id === nextId) ?? null;
            setAgentSelectedModelId(nextId);
            setAgentSelectedModelName(entry?.name ?? "");
          }}
          fullWidth
          disabled={!workbenchAgentStatus?.configured || (!workbenchAgentModels.length && !workbenchAgentModelsQuery.isFetching)}
          helperText={
            selectedWorkbenchAgentModel?.description ||
            workbenchAgentStatus?.model_name ||
            "Load models after saving the Open WebUI connection, then choose the mapped agent/model here."
          }
        >
          <MenuItem value="">
            <em>Select an Open WebUI model</em>
          </MenuItem>
          {workbenchAgentModels.map((entry) => (
            <MenuItem key={entry.id} value={entry.id}>
              {entry.name} ({entry.id})
            </MenuItem>
          ))}
        </TextField>
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          <Chip label={workbenchAgentStatus?.configured ? "Connection saved" : "Connection not saved"} color={workbenchAgentStatus?.configured ? "success" : "default"} />
          <Chip label={workbenchAgentStatus?.model_name || "No mapped model yet"} variant="outlined" />
          <Chip label={workbenchAgentStatus?.knowledge_file_name || "Knowledge not synced"} variant="outlined" />
          <Chip label={workbenchAgentStatus?.reference_file_count ? `${workbenchAgentStatus.reference_file_count} Workbench + 3DS reference files` : "Workbench + 3DS references not synced"} variant="outlined" />
          <Chip
            label={
              workbenchAgentStatus?.three_ds_kb_available
                ? `3DS KB: ${workbenchAgentStatus.three_ds_kb_page_count} documents / ${workbenchAgentStatus.three_ds_kb_chunk_count} integrity-gated evidence records`
                : "3DS KB not configured"
            }
            color={workbenchAgentStatus?.three_ds_kb_available ? "success" : "warning"}
            variant="outlined"
          />
        </Stack>
        {workbenchAgentStatus?.updated_at ? (
          <Typography variant="caption" color="text.secondary">
            Mapping updated {new Date(workbenchAgentStatus.updated_at).toLocaleString()}.
          </Typography>
        ) : null}
      </Stack>
    </Paper>
  );

  const renderWorkbenchAgent = () => (
    <Stack spacing={2}>
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Box>
            <Typography variant="h5">Workbench Agent</Typography>
            <Typography variant="body2" color="text.secondary">
              Chat with the mapped Open WebUI model against the selected project branch. Configure the Open WebUI connection in Settings → Authentication.
            </Typography>
          </Box>
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip label={workbenchAgentStatus?.configured ? "Connection saved" : "Connection not saved"} color={workbenchAgentStatus?.configured ? "success" : "default"} />
            <Chip label={workbenchAgentStatus?.model_name || "No mapped model yet"} variant="outlined" />
            <Chip label={workbenchAgentStatus?.knowledge_file_name || "Knowledge not synced"} variant="outlined" />
          </Stack>
          {isAdmin ? (
            <Button
              variant="outlined"
              startIcon={<SettingsRoundedIcon />}
              onClick={() => {
                setSettingsSubtab("auth");
                setTab("settings");
              }}
            >
              Open Authentication Settings
            </Button>
          ) : null}
        </Stack>
      </Paper>

      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Box>
            <Typography variant="h6">Knowledge Push</Typography>
            <Typography variant="body2" color="text.secondary">
              Process the persistent Workbench + 3DS reference when its fingerprint changes, then push the selected branch separately with its complete tree and native Cameo specification records.
            </Typography>
          </Box>
          {!selectedProjectId || !selectedBranchId ? (
            <Alert severity="warning">Select a project and branch first so Workbench Agent knows which stored branch knowledge to upload.</Alert>
          ) : null}
          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
            <Chip label={`Project: ${workbenchAgentProjectLabel}`} />
            <Chip label={`Branch: ${workbenchAgentBranchLabel}`} variant="outlined" />
            {branchAccessManifestStatus ? (
              <Chip
                label={`${branchAccessManifestStatus.accessible_user_count} accessible users`}
                variant="outlined"
              />
            ) : null}
          </Stack>
          {workbenchAgentStatus?.knowledge_project_id && workbenchAgentStatus?.knowledge_branch_id ? (
            <Alert severity="success">
              Current synced knowledge: {workbenchAgentStatus.knowledge_file_name || workbenchAgentStatus.knowledge_file_id} for {workbenchAgentStatus.knowledge_project_id} / {workbenchAgentStatus.knowledge_branch_id}
              {workbenchAgentStatus.knowledge_synced_at ? ` at ${new Date(workbenchAgentStatus.knowledge_synced_at).toLocaleString()}` : ""}.
            </Alert>
          ) : null}
          {workbenchAgentStatus?.reference_file_id ? (
            <Alert severity="success">
              Persistent Agent controls: {workbenchAgentStatus.reference_file_count || 1} processed files. Relevant evidence is routed from the validated corpus for each question.
              {workbenchAgentStatus.reference_synced_at ? ` at ${new Date(workbenchAgentStatus.reference_synced_at).toLocaleString()}` : ""}. The complete set is attached before the branch file for every mapped model used in Workbench Agent.
            </Alert>
          ) : null}
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
            <Button
              variant="contained"
              disabled={!selectedProjectId || !selectedBranchId || !workbenchAgentStatus?.configured || !csrfToken || syncWorkbenchAgentKnowledgeMutation.isPending}
              onClick={() => syncWorkbenchAgentKnowledgeMutation.mutate()}
            >
              Push Current Branch Knowledge
            </Button>
            {syncWorkbenchAgentKnowledgeMutation.isPending ? <CircularProgress size={22} /> : null}
          </Stack>
          {agentKnowledgeSyncProgress ? <Alert severity={syncWorkbenchAgentKnowledgeMutation.isError ? "error" : "info"}>{agentKnowledgeSyncProgress}</Alert> : null}
        </Stack>
      </Paper>

      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Box>
            <Typography variant="h6">Agent Chat</Typography>
            <Typography variant="body2" color="text.secondary">
              Use any mapped Open WebUI model against the selected stored branch. Every turn attaches the persistent Workbench + 3DS reference first and the permission-scoped branch model second.
            </Typography>
          </Box>
          {!workbenchAgentStatus?.configured ? (
            <Alert severity="warning">Save the Open WebUI connection and mapped model before starting a Workbench Agent conversation.</Alert>
          ) : null}
          <FormControlLabel
            control={
              <Checkbox
                checked={agentSyncKnowledgeBeforeChat}
                onChange={(event) => setAgentSyncKnowledgeBeforeChat(event.target.checked)}
              />
            }
            label="Auto-push when the selected project or branch differs from the processed knowledge file"
          />
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2, minHeight: 220 }}>
            <Stack spacing={1.5}>
              {agentMessages.length ? (
                agentMessages.map((message, index) => (
                  <Paper
                    key={`${message.role}-${index}`}
                    variant="outlined"
                    sx={{
                      p: 1.5,
                      borderRadius: 2,
                      bgcolor: message.role === "assistant" ? "action.hover" : "background.paper",
                    }}
                  >
                    <Typography variant="subtitle2" sx={{ textTransform: "capitalize", mb: 0.5 }}>
                      {message.role}
                    </Typography>
                    <Typography variant="body2" sx={{ whiteSpace: "pre-wrap" }}>
                      {message.content}
                    </Typography>
                  </Paper>
                ))
              ) : (
                <Typography color="text.secondary">
                  Start a conversation once a model is mapped. The agent is instructed to retrieve Workbench and 3DS usage guidance from the persistent reference and project facts from the selected branch file.
                </Typography>
              )}
            </Stack>
          </Paper>
          <TextField
            label="Prompt"
            value={agentChatInput}
            onChange={(event) => setAgentChatInput(event.target.value)}
            fullWidth
            multiline
            minRows={5}
            helperText="Ask for scripts, model searches, stereotype reports, diagram-related questions, or analysis of the selected stored project branch."
          />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
            <Button
              variant="contained"
              disabled={
                !workbenchAgentStatus?.configured ||
                !selectedProjectId ||
                !selectedBranchId ||
                !agentChatInput.trim() ||
                !csrfToken ||
                workbenchAgentChatMutation.isPending
              }
              onClick={sendWorkbenchAgentPrompt}
            >
              Send to Workbench Agent
            </Button>
            <Button
              variant="outlined"
              disabled={!agentMessages.length}
              onClick={() => setAgentMessages([])}
            >
              Clear Conversation
            </Button>
            {workbenchAgentChatMutation.isPending ? <CircularProgress size={22} /> : null}
          </Stack>
        </Stack>
      </Paper>
    </Stack>
  );

  const renderWorkspacePreferences = () => {
    const setPreferenceField = <K extends keyof SessionPreferences>(key: K, value: SessionPreferences[K]) => {
      setPreferencesDraft((current) => ({ ...current, [key]: value }));
    };
    const detailViewOptions: Array<{ value: ItemDetailViewMode; label: string }> = [
      { value: "standard", label: "Standard" },
      { value: "expert", label: "Expert" },
      { value: "all", label: "All" },
    ];

    return (
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Box>
            <Typography variant="h5">Workspace Preferences</Typography>
            <Typography variant="body2" color="text.secondary">
              User-facing workspace behavior. These settings are saved to your Workbench profile, not the deployment environment file.
            </Typography>
          </Box>
          <TextField
            select
            label="Theme"
            value={preferencesDraft.theme_mode}
            onChange={(event) => setPreferenceField("theme_mode", event.target.value as ThemeMode)}
            fullWidth
          >
            <MenuItem value="light">Light</MenuItem>
            <MenuItem value="dark">Dark</MenuItem>
            <MenuItem value="system">System</MenuItem>
          </TextField>
          <Grid container spacing={2}>
            <Grid item xs={12}>
              <Typography gutterBottom fontWeight={600}>Font Scale</Typography>
              <Slider
                value={preferencesDraft.font_scale}
                min={0.85}
                max={1.4}
                step={0.05}
                marks
                onChange={(_, value) => setPreferenceField("font_scale", value as number)}
                valueLabelDisplay="auto"
              />
            </Grid>
            <Grid item xs={12}>
              <Typography gutterBottom fontWeight={600}>Presentation Font Scale</Typography>
              <Slider
                value={preferencesDraft.presentation_font_scale}
                min={1}
                max={2}
                step={0.05}
                marks
                onChange={(_, value) => setPreferenceField("presentation_font_scale", value as number)}
                valueLabelDisplay="auto"
              />
            </Grid>
          </Grid>
          <Grid container spacing={2}>
            <Grid item xs={12} md={6}>
              <TextField
                select
                label="Specification View Mode"
                value={preferencesDraft.item_detail_view_mode}
                onChange={(event) => setPreferenceField("item_detail_view_mode", event.target.value as ItemDetailViewMode)}
                fullWidth
              >
                {detailViewOptions.map((option) => (
                  <MenuItem key={option.value} value={option.value}>
                    {option.label}
                  </MenuItem>
                ))}
              </TextField>
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                label="Request Timeout (seconds)"
                type="number"
                fullWidth
                value={preferencesDraft.request_timeout_seconds}
                onChange={(event) => setPreferenceField("request_timeout_seconds", Number(event.target.value))}
              />
            </Grid>
            <Grid item xs={12} md={6}>
              <TextField
                label="Live Log Polling (ms)"
                type="number"
                fullWidth
                value={preferencesDraft.live_log_poll_interval_ms}
                onChange={(event) => setPreferenceField("live_log_poll_interval_ms", Number(event.target.value))}
              />
            </Grid>
          </Grid>
          <FormControlLabel
            control={
              <Checkbox
                checked={preferencesDraft.compact_ui}
                onChange={(event) => setPreferenceField("compact_ui", event.target.checked)}
              />
            }
            label="Use compact workspace layout"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={Boolean(preferencesDraft.show_hidden_packages_in_tree || preferencesDraft.show_auxiliary_resources_in_tree)}
                onChange={(event) => {
                  setPreferenceField("show_hidden_packages_in_tree", event.target.checked);
                  setPreferenceField("show_auxiliary_resources_in_tree", event.target.checked);
                }}
              />
            }
            label="Show Auxiliary Resources in containment tree"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={Boolean(preferencesDraft.show_applied_stereotypes_in_tree)}
                onChange={(event) => setPreferenceField("show_applied_stereotypes_in_tree", event.target.checked)}
              />
            }
            label="Show Applied Stereotypes in containment tree"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={Boolean(preferencesDraft.show_full_types_in_tree)}
                onChange={(event) => setPreferenceField("show_full_types_in_tree", event.target.checked)}
              />
            }
            label="Show Full Types in containment tree"
          />
          <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
            <Button
              variant="contained"
              startIcon={<SaveRoundedIcon />}
              disabled={!csrfToken || settingsMutation.isPending}
              onClick={() => settingsMutation.mutate(preferencesDraft)}
            >
              Save Workspace Preferences
            </Button>
            {settingsMutation.isPending ? <CircularProgress size={22} /> : null}
          </Stack>
        </Stack>
      </Paper>
    );
  };

  const renderDebugSettings = () => (
    <Paper sx={{ p: 3, borderRadius: 2 }}>
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
          <Box>
            <Typography variant="h5">Debug Export</Typography>
            <Typography variant="body2" color="text.secondary">
              Export one stored project branch as a full JSON digest or a Tableau-safe SQLite database. This is admin-only and reads the plugin-backed Workbench cache.
            </Typography>
          </Box>
          <Chip label="Admin debug" color="warning" variant="outlined" />
        </Stack>
        <Alert severity="info">
          Use JSON when you need the raw factual package for debugging. Use the Tableau database when admins need reporting tables for models, containment, relationships, specifications, and access records without exporting Workbench secrets.
        </Alert>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5}>
          <TextField
            select
            label="Project"
            value={debugProjectId}
            onChange={(event) => {
              setDebugProjectId(event.target.value);
              setDebugBranchId("trunk");
              setDebugDumpDigest(null);
            }}
            fullWidth
            helperText={projectsQuery.isFetching ? "Loading stored projects..." : "Admins can export any Workbench-visible stored project."}
          >
            <MenuItem value=""><em>Select project</em></MenuItem>
            {projects.map((project) => (
              <MenuItem key={project.id} value={project.id}>
                {project.name || project.id}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Branch"
            value={debugBranchId}
            onChange={(event) => {
              setDebugBranchId(event.target.value || "trunk");
              setDebugDumpDigest(null);
            }}
            fullWidth
            helperText={debugBranchesQuery.isFetching ? "Loading branches..." : "Defaults to trunk; branch name/id is resolved by Workbench."}
          >
            <MenuItem value="trunk"><em>trunk</em></MenuItem>
            {debugBranches.map((branch) => (
              <MenuItem key={branch.id} value={branch.id}>
                {branch.name || branch.id}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        {projectsQuery.error ? <Alert severity="error">{errorMessage(projectsQuery.error)}</Alert> : null}
        {debugBranchesQuery.error ? <Alert severity="error">{errorMessage(debugBranchesQuery.error)}</Alert> : null}
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
          <Button
            variant="outlined"
            startIcon={<RefreshRoundedIcon />}
            disabled={projectsQuery.isFetching}
            onClick={() => void projectsQuery.refetch()}
          >
            Refresh Projects
          </Button>
          <Button
            variant="contained"
            startIcon={<SaveRoundedIcon />}
            disabled={!debugProjectId || exportDebugProjectDumpMutation.isPending || exportTableauProjectDbMutation.isPending}
            onClick={() => exportDebugProjectDumpMutation.mutate()}
          >
            Export Full Digest
          </Button>
          <Button
            variant="contained"
            color="success"
            startIcon={<SaveRoundedIcon />}
            disabled={!debugProjectId || exportDebugProjectDumpMutation.isPending || exportTableauProjectDbMutation.isPending}
            onClick={() => exportTableauProjectDbMutation.mutate()}
          >
            Download Tableau DB
          </Button>
          {exportDebugProjectDumpMutation.isPending || exportTableauProjectDbMutation.isPending ? <CircularProgress size={22} /> : null}
        </Stack>
        {debugDumpDigest ? (
          <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
            <Stack spacing={1.25}>
              <Typography variant="subtitle1">Last export request</Typography>
              <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                {debugDumpDigest.export_type ? <Chip label={`Type: ${String(debugDumpDigest.export_type)}`} color="success" variant="outlined" /> : null}
                <Chip label={`Project: ${String(debugDumpDigest.project_name ?? debugDumpDigest.project_id ?? "unknown")}`} />
                <Chip label={`Branch: ${String(debugDumpDigest.branch_name ?? debugDumpDigest.branch_id ?? "trunk")}`} variant="outlined" />
                {debugDumpDigest.export_started_at ? <Chip label={`Started: ${new Date(String(debugDumpDigest.export_started_at)).toLocaleString()}`} variant="outlined" /> : null}
              </Stack>
              <TextField
                label="Download request summary"
                value={JSON.stringify(debugDumpDigest, null, 2)}
                multiline
                minRows={8}
                fullWidth
                InputProps={{ readOnly: true }}
              />
            </Stack>
          </Paper>
        ) : null}
      </Stack>
    </Paper>
  );

  const renderSettingsPage = () => (
    <Stack spacing={2}>
      <Paper sx={{ p: 3, borderRadius: 2 }}>
        <Stack spacing={2}>
          <Box>
            <Typography variant="h5">Workbench Settings</Typography>
            <Typography variant="body2" color="text.secondary">
              Organized admin and personal settings. Workspace project/branch context is hidden here so setup work stays focused.
            </Typography>
          </Box>
          {canManageGroups || isAdmin ? (
            <Tabs
              value={settingsSubtab}
              onChange={(_event: SyntheticEvent, value: SettingsSubtab) => setSettingsSubtab(value)}
              variant="scrollable"
              scrollButtons="auto"
              aria-label="Workbench settings sections"
            >
              {canManageGroups || canAssignProjectAccess ? <Tab value="users" label="Users" /> : null}
              {canManageGroups || canAssignProjectAccess ? <Tab value="groups" label="Groups" /> : null}
              {isAdmin ? <Tab value="servers" label="Servers" /> : null}
              {isAdmin ? <Tab value="auth" label="Authentication" /> : null}
              {isAdmin ? <Tab value="api-keys" label="API Access Keys" /> : null}
              {isAdmin ? <Tab value="debug" label="Debug" /> : null}
            </Tabs>
          ) : null}
        </Stack>
      </Paper>

      {!canManageGroups && !isAdmin && !canAssignProjectAccess ? (
        <Alert severity="info">
          Settings are available to Workbench administrators, group managers, and project access administrators for their selected project branch.
        </Alert>
      ) : null}

      {settingsSubtab === "users" ? (
        <Stack spacing={2}>
          {canAssignProjectAccess ? renderWorkbenchProjectAccessAssignment() : null}
          {canManageGroups ? renderWorkbenchUserManagement() : (
            <Alert severity="info">User management is available to Workbench administrators and group managers.</Alert>
          )}
        </Stack>
      ) : null}

      {settingsSubtab === "groups" ? (
        <Stack spacing={2}>
          {canAssignProjectAccess ? renderWorkbenchProjectAccessAssignment() : null}
          {canManageGroups ? renderWorkbenchGroupManagement() : (
            <Alert severity="info">Group management is available to Workbench administrators and group managers.</Alert>
          )}
          {isAdmin ? renderPermissionInventoryStatus() : null}
        </Stack>
      ) : null}

      {settingsSubtab === "auth" ? (
        <Stack spacing={2}>
          {isAdmin ? (
            <>
              {renderAuthenticationSettings()}
              {renderWorkspacePreferences()}
              {renderCacheIngestToken()}
              {renderWorkbenchAgentSettings()}
              {renderTombstoneAudit()}
            </>
          ) : (
            <Alert severity="info">Authentication settings are administrator-only.</Alert>
          )}
        </Stack>
      ) : null}

      {settingsSubtab === "servers" ? (
        <Stack spacing={2}>
          {isAdmin ? renderServerPresetManagement() : (
            <Alert severity="info">Server management is administrator-only.</Alert>
          )}
        </Stack>
      ) : null}

      {settingsSubtab === "api-keys" ? (
        <Stack spacing={2}>
          {isAdmin ? renderCacheApiKeys() : (
            <Alert severity="info">API access keys are administrator-only.</Alert>
          )}
        </Stack>
      ) : null}

      {settingsSubtab === "debug" ? (
        <Stack spacing={2}>
          {isAdmin ? renderDebugSettings() : (
            <Alert severity="info">Debug exports are administrator-only.</Alert>
          )}
        </Stack>
      ) : null}

    </Stack>
  );

  const renderApiExplorer = () => {
    const response = apiOperationMutation.data ?? null;
    return (
      <Stack spacing={2}>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} justifyContent="space-between" alignItems={{ xs: "stretch", sm: "center" }}>
          <Box>
            <Typography variant="h5">API Explorer</Typography>
            <Typography variant="body2" color="text.secondary">
              Browse every operation, parameter, request body, response, and schema declared by RealSwagger.json. Executing requests remains an administrator-only action.
            </Typography>
          </Box>
          <Button variant="outlined" startIcon={<RefreshRoundedIcon />} onClick={() => queryClient.invalidateQueries({ queryKey: ["workspace-contract", ...sessionCacheKey] })}>
            Refresh Contract
          </Button>
        </Stack>
        {!isAdmin ? (
          <Alert severity="info">
            Read-only API documentation is available to every authenticated Workbench user. Ask an administrator only when a declared operation needs to be executed against Teamwork Cloud.
          </Alert>
        ) : null}
        {contractQuery.isLoading ? <CircularProgress size={28} /> : null}
        {contractQuery.error ? <Alert severity="error">{errorMessage(contractQuery.error)}</Alert> : null}
        {contractManifest ? (
          <Grid container spacing={2}>
            <Grid item xs={12} md={4}>
              <Paper sx={{ p: 2, borderRadius: 2 }}>
                <Stack spacing={2}>
                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label={contractManifest.version || contractManifest.title} />
                    <Chip label={`${contractManifest.operations.length} operations`} variant="outlined" />
                    <Chip label={`${contractManifest.schemas.length} schemas`} variant="outlined" />
                  </Stack>
                  <TextField select label="Functional Area" value={selectedApiTag} onChange={(event) => setSelectedApiTag(event.target.value)} fullWidth>
                    {apiTags.map((tag) => (
                      <MenuItem key={tag} value={tag}>
                        {tag} ({contractManifest.tag_counts[tag]})
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField label="Filter operations" value={apiSearch} onChange={(event) => setApiSearch(event.target.value)} fullWidth />
                  <List dense disablePadding sx={{ maxHeight: 560, overflow: "auto" }}>
                    {filteredApiOperations.map((operation) => (
                      <ListItemButton
                        key={operation.key}
                        selected={selectedOperation?.key === operation.key}
                        onClick={() => setSelectedOperationKey(operation.key)}
                      >
                        <ListItemText
                          primary={
                            <Stack direction="row" spacing={1} alignItems="center">
                              <Chip label={operation.method} size="small" color={operation.destructive ? "warning" : "default"} />
                              <Typography variant="body2" sx={{ wordBreak: "break-all" }}>
                                {operation.path}
                              </Typography>
                            </Stack>
                          }
                          secondary={operation.summary || operation.description || operation.key}
                        />
                      </ListItemButton>
                    ))}
                  </List>
                  {!filteredApiOperations.length ? <Typography color="text.secondary">No operations match this filter.</Typography> : null}
                </Stack>
              </Paper>
            </Grid>
            <Grid item xs={12} md={8}>
              {selectedOperation ? (
                <Stack spacing={2}>
                  <Paper sx={{ p: 3, borderRadius: 2 }}>
                    <Stack spacing={2}>
                      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
                        <Chip label={selectedOperation.method} color={selectedOperation.destructive ? "warning" : "default"} />
                        <Typography variant="h6" sx={{ wordBreak: "break-all" }}>
                          {selectedOperation.path}
                        </Typography>
                      </Stack>
                      {selectedOperation.summary || selectedOperation.description ? (
                        <Typography color="text.secondary">{selectedOperation.summary || selectedOperation.description}</Typography>
                      ) : null}
                      <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                        {selectedOperation.request_body?.content_types.map((contentType) => (
                          <Chip key={contentType} label={contentType} variant="outlined" />
                        ))}
                        {selectedOperation.supports_file_upload ? <Chip label="File upload" color="info" variant="outlined" /> : null}
                        {selectedOperation.supports_download ? <Chip label="Download-capable" color="info" variant="outlined" /> : null}
                        {selectedOperation.responses.map((apiResponse) => (
                          <Chip
                            key={`${apiResponse.status_code}-${apiResponse.schema_ref ?? "response"}`}
                            label={`${apiResponse.status_code}${apiResponse.schema_ref ? ` ${apiResponse.schema_ref}` : ""}`}
                            size="small"
                            variant="outlined"
                          />
                        ))}
                      </Stack>
                      {selectedOperation.destructive ? (
                        <Alert severity="warning">
                          This operation can change or delete data. It is still executed only against the Swagger-declared TWC endpoint and will use the current authenticated TWC session.
                        </Alert>
                      ) : null}
                    </Stack>
                  </Paper>
                  <Paper sx={{ p: 3, borderRadius: 2 }}>
                    <Stack spacing={2}>
                      {renderParameterControls("Path Parameters", selectedOperation.path_parameters, apiPathParams, (name, value) =>
                        setApiPathParams((current) => ({ ...current, [name]: value })),
                      )}
                      <Divider />
                      {renderParameterControls("Query Parameters", selectedOperation.query_parameters, apiQueryParams, (name, value) =>
                        setApiQueryParams((current) => ({ ...current, [name]: value })),
                      )}
                      {selectedOperation.request_body && !selectedOperation.supports_file_upload ? (
                        <>
                          <Divider />
                          <Stack spacing={1.5}>
                            <Typography variant="subtitle2">Request Body</Typography>
                            <TextField
                              select
                              label="Content-Type"
                              value={apiContentType}
                              onChange={(event) => {
                                setApiContentType(event.target.value);
                                setApiBodyText(event.target.value === "text/plain" ? "" : requestBodyTemplate(selectedOperation, contractManifest));
                              }}
                              fullWidth
                            >
                              {selectedOperation.request_body.content_types.map((contentType) => (
                                <MenuItem key={contentType} value={contentType}>
                                  {contentType}
                                </MenuItem>
                              ))}
                            </TextField>
                            <TextField
                              label={apiContentType === "text/plain" ? "Text payload" : "JSON payload"}
                              value={apiBodyText}
                              onChange={(event) => setApiBodyText(event.target.value)}
                              fullWidth
                              multiline
                              minRows={8}
                              helperText={selectedOperation.request_body.description || "Payload shape is derived from the Swagger requestBody schema."}
                            />
                          </Stack>
                        </>
                      ) : null}
                      {selectedOperation.supports_file_upload ? (
                        <>
                          <Divider />
                          <Stack spacing={1.5}>
                            <Typography variant="subtitle2">File Upload</Typography>
                            <Button variant="outlined" component="label" disabled={!isAdmin}>
                              Choose File
                              <input
                                hidden
                                type="file"
                                onChange={(event) => setApiUploadFile(event.target.files?.[0] ?? null)}
                              />
                            </Button>
                            <Typography variant="body2" color="text.secondary">
                              {apiUploadFile ? `${apiUploadFile.name} (${apiUploadFile.size} bytes)` : "No file selected."}
                            </Typography>
                          </Stack>
                        </>
                      ) : null}
                      <Stack direction={{ xs: "column", sm: "row" }} spacing={1.5} alignItems={{ xs: "stretch", sm: "center" }}>
                        <Button
                          variant="contained"
                          disabled={!isAdmin || !selectedOperation || !csrfToken || apiOperationMutation.isPending}
                          onClick={() => apiOperationMutation.mutate()}
                        >
                          {isAdmin ? "Execute Operation" : "Administrator required to execute"}
                        </Button>
                        {apiOperationMutation.isPending ? <CircularProgress size={24} /> : null}
                      </Stack>
                    </Stack>
                  </Paper>
                  {response ? (
                    <Paper sx={{ p: 3, borderRadius: 2 }}>
                      <Stack spacing={2}>
                        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" alignItems="center">
                          <Typography variant="h6">Response</Typography>
                          <Chip label={`${response.status_code}`} color={response.ok ? "success" : "error"} />
                          <Chip label={response.content_type || "no content type"} variant="outlined" />
                          <Chip label={`${response.size_bytes} bytes`} variant="outlined" />
                        </Stack>
                        <Typography variant="body2" color="text.secondary" sx={{ wordBreak: "break-all" }}>
                          {response.method} {response.requested_path}
                        </Typography>
                        {response.body_base64 ? (
                          <Button variant="outlined" onClick={() => downloadSwaggerResponse(response)}>
                            Download Response Body
                          </Button>
                        ) : null}
                        <TextField
                          label="Response body"
                          value={responseContent(response)}
                          fullWidth
                          multiline
                          minRows={10}
                          InputProps={{ readOnly: true }}
                        />
                        <TextField
                          label="Response headers"
                          value={JSON.stringify(response.headers, null, 2)}
                          fullWidth
                          multiline
                          minRows={4}
                          InputProps={{ readOnly: true }}
                        />
                      </Stack>
                    </Paper>
                  ) : null}
                </Stack>
              ) : (
                <Paper sx={{ p: 4, borderRadius: 2, textAlign: "center" }}>
                  <Typography color="text.secondary">Select an operation to build a Swagger-backed request.</Typography>
                </Paper>
              )}
            </Grid>
          </Grid>
        ) : null}
      </Stack>
    );
  };

  return (
    <Box sx={{ minHeight: "100vh", bgcolor: "background.default" }}>
      <AppBar position="sticky" color="default" elevation={1}>
        <Toolbar sx={{ gap: compactUi ? 1.25 : 2 }}>
          <Box sx={{ flexGrow: 1, minWidth: 0 }}>
            <WorkbenchBrandMark size={34} titleVariant="h6" />
          </Box>
          {session?.capabilities ? <CapabilityBadges capabilities={session.capabilities.capabilities} /> : null}
          <Tooltip title="Refresh capabilities, projects, and permissions">
            <span>
              <IconButton onClick={() => capabilityMutation.mutate()} disabled={!csrfToken || capabilityMutation.isPending}>
                <RefreshRoundedIcon />
              </IconButton>
            </span>
          </Tooltip>
          <Button
            size="small"
            variant="text"
            startIcon={<AccountCircleRoundedIcon />}
            endIcon={<KeyboardArrowDownRoundedIcon />}
            onClick={openUserMenu}
            sx={{ minWidth: 0, textTransform: "none" }}
          >
            {userMenuLabel}
          </Button>
          <Menu
            anchorEl={userMenuAnchorEl}
            open={Boolean(userMenuAnchorEl)}
            onClose={closeUserMenu}
            keepMounted
          >
            <MenuItem disabled>{userMenuLabel}</MenuItem>
            {canOpenSettings ? (
              <MenuItem
                onClick={() => {
                  closeUserMenu();
                  setTab("settings");
                  if (!isAdmin && settingsSubtab !== "users" && settingsSubtab !== "groups") {
                    setSettingsSubtab("users");
                  }
                }}
              >
                <SettingsRoundedIcon sx={{ mr: 1, fontSize: 18 }} />
                Settings
              </MenuItem>
            ) : null}
            <MenuItem
              onClick={() => {
                closeUserMenu();
                logoutMutation.mutate();
              }}
              disabled={!csrfToken || logoutMutation.isPending}
            >
              <LogoutRoundedIcon sx={{ mr: 1, fontSize: 18 }} />
              Sign out
            </MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: {
            xs: "1fr",
            lg: settingsTabActive ? "minmax(0, 1fr)" : `${navPaneWidth}px 12px minmax(0, 1fr)`,
          },
          gap: 0,
          p: workspaceOuterPadding,
        }}
      >
        {!settingsTabActive ? (
        <Paper
          component="aside"
          sx={{
            p: compactUi ? 1.5 : 2,
            borderRadius: 2,
            minWidth: 0,
            display: "flex",
            flexDirection: "column",
            maxHeight: { xs: "none", lg: "calc(100vh - 110px)" },
            overflow: "hidden",
          }}
        >
          <Stack spacing={sectionSpacing} sx={{ minHeight: 0, flex: 1 }}>
            <TextField
              select
              label="Project"
              value={selectedProjectId}
              onChange={(event) => selectProject(event.target.value)}
              fullWidth
              disabled={!projects.length}
            >
              <MenuItem value="">
                <em>Select a project</em>
              </MenuItem>
              {projects.map((project) => (
                <MenuItem key={project.id} value={project.id}>
                  {project.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Branch"
              value={selectedBranchId}
              onChange={(event) => setSelectedBranchId(event.target.value)}
              fullWidth
              disabled={!selectedProjectId || branchesQuery.isLoading || !selectedProjectBranches.length}
            >
              {!selectedProjectId ? (
                <MenuItem value="" disabled>
                  Select a project first
                </MenuItem>
              ) : selectedProjectBranches.length ? (
                selectedProjectBranches.map((branch) => (
                  <MenuItem key={branch.id} value={branch.id}>
                    {branch.name}
                  </MenuItem>
                ))
              ) : branchesQuery.isLoading ? (
                <MenuItem value="" disabled>
                  Loading branches...
                </MenuItem>
              ) : (
                <MenuItem value="">Default</MenuItem>
              )}
            </TextField>
            <Paper variant="outlined" sx={{ p: compactUi ? 1.5 : 2, borderRadius: 2 }}>
              <Stack spacing={0.75}>
                <Typography variant="overline" color="text.secondary">
                  Workspace Context
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  Choose the published project and branch here. The containment tree and specification workspace appear together inside Model Browser.
                </Typography>
              </Stack>
            </Paper>
            {selectedWorkspaceItem ? (
              <Paper variant="outlined" sx={{ p: compactUi ? 1.5 : 2, borderRadius: 2 }}>
                <Stack spacing={compactUi ? 0.5 : 0.75}>
                  <Typography variant="overline" color="text.secondary">
                    Current Selection
                  </Typography>
                  <Typography variant="subtitle2">{selectedWorkspaceItemName}</Typography>
                  <Typography variant="caption" color="text.secondary">
                    {selectedWorkspaceItemPath || (selectedProject ? `${selectedProject.name} / ${branchLabel(selectedProjectBranches, selectedBranchId)}` : humanizeFieldLabel(selectedWorkspaceItem.item_type))}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {humanizeFieldLabel(selectedWorkspaceItem.item_type)}
                  </Typography>
                  {selectedContainmentSegments.length ? (
                    <Stack direction="row" spacing={0.5} useFlexGap flexWrap="wrap">
                      {selectedContainmentSegments.map((segment, index) => (
                        <Chip
                          key={`${segment}-${index}`}
                          label={segment}
                          size="small"
                          variant={index === selectedContainmentSegments.length - 1 ? "filled" : "outlined"}
                        />
                      ))}
                    </Stack>
                  ) : null}
                </Stack>
              </Paper>
            ) : null}
          </Stack>
        </Paper>
        ) : null}
        {!settingsTabActive ? (
        <Box
          role="separator"
          aria-orientation="vertical"
          sx={resizeHandleStyles()}
          onMouseDown={(event) => beginHorizontalResize(event, navPaneWidth, setNavPaneWidth, 260, 520)}
        />
        ) : null}
        <Stack spacing={sectionSpacing} component="main" sx={{ minWidth: 0, pl: { xs: 0, lg: settingsTabActive ? 0 : compactUi ? 1.5 : 2 } }}>
          {notice ? <Alert severity={notice.severity} onClose={() => setNotice(null)}>{notice.message}</Alert> : null}
          {session?.permission_snapshot_warning ? <Alert severity="warning">{session.permission_snapshot_warning}</Alert> : null}
          {!settingsTabActive && projectsQuery.error ? <Alert severity="error">{errorMessage(projectsQuery.error)}</Alert> : null}
          <Paper sx={{ borderRadius: 2 }}>
            <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ p: compactUi ? 1 : 1.25 }}>
              <Button
                size="small"
                variant={currentMenuGroup === "views" ? "contained" : "text"}
                endIcon={<KeyboardArrowDownRoundedIcon />}
                onClick={openWorkspaceMenu("views")}
              >
                Views
              </Button>
              <Button
                size="small"
                variant={currentMenuGroup === "diagrams" ? "contained" : "text"}
                endIcon={<KeyboardArrowDownRoundedIcon />}
                onClick={openWorkspaceMenu("diagrams")}
              >
                Diagrams
              </Button>
              {isAdmin ? (
                <Button
                  size="small"
                  variant={currentMenuGroup === "api" ? "contained" : "text"}
                  endIcon={<KeyboardArrowDownRoundedIcon />}
                  onClick={openWorkspaceMenu("api")}
                >
                  API
                </Button>
              ) : null}
              <Button
                size="small"
                variant={tab === "agent" ? "contained" : "text"}
                onClick={() => setTab("agent")}
              >
                Agent
              </Button>
              {canOpenSettings ? (
                <Button
                  size="small"
                  variant={tab === "settings" ? "contained" : "text"}
                  startIcon={<SettingsRoundedIcon />}
                  onClick={() => {
                    setTab("settings");
                    if (!isAdmin && settingsSubtab !== "users" && settingsSubtab !== "groups") {
                      setSettingsSubtab("users");
                    }
                  }}
                >
                  Settings
                </Button>
              ) : null}
            </Stack>
            <Menu
              anchorEl={workspaceMenuAnchorEl}
              open={Boolean(workspaceMenuGroup)}
              onClose={closeWorkspaceMenu}
              keepMounted
            >
              {workspaceMenuGroup === "views" ? (
                [
                  <MenuItem key="dashboard" selected={tab === "dashboard"} onClick={() => { setTab("dashboard"); closeWorkspaceMenu(); }}>Dashboard</MenuItem>,
                  <MenuItem key="projects" selected={tab === "projects"} onClick={() => { setTab("projects"); closeWorkspaceMenu(); }}>Project Browser</MenuItem>,
                  <MenuItem key="models" selected={tab === "models"} onClick={() => { setTab("models"); closeWorkspaceMenu(); }}>Model Browser</MenuItem>,
                  <MenuItem key="search" selected={tab === "search"} onClick={() => { setTab("search"); closeWorkspaceMenu(); }}>Element Search</MenuItem>,
                  <MenuItem key="compare" selected={tab === "compare"} onClick={() => { setTab("compare"); closeWorkspaceMenu(); }}>Compare</MenuItem>,
                  <MenuItem key="agent" selected={tab === "agent"} onClick={() => { setTab("agent"); closeWorkspaceMenu(); }}>Workbench Agent</MenuItem>,
                ]
              ) : null}
              {workspaceMenuGroup === "diagrams" ? (
                [
                  <MenuItem
                    key="diagram-viewer"
                    selected={tab === "diagram-viewer"}
                    disabled={!selectedWorkspaceItemDiagramPreviewUrl && !selectedWorkspaceItemIsDiagram}
                    onClick={() => {
                      openDiagramViewer();
                      closeWorkspaceMenu();
                    }}
                  >
                    Diagram Viewer
                  </MenuItem>,
                  <MenuItem
                    key="diagram-details"
                    disabled={!selectedWorkspaceItemIsDiagram}
                    onClick={() => {
                      openDiagramDetails();
                      closeWorkspaceMenu();
                    }}
                  >
                    Diagram Details
                  </MenuItem>,
                ]
              ) : null}
              {workspaceMenuGroup === "api" && isAdmin ? (
                [
                  <MenuItem key="developer" selected={tab === "developer"} onClick={() => { setTab("developer"); closeWorkspaceMenu(); }}>Developer API</MenuItem>,
                  <MenuItem key="api-explorer" selected={tab === "api"} onClick={() => { setTab("api"); closeWorkspaceMenu(); }}>
                    API Explorer
                  </MenuItem>,
                ]
              ) : null}
            </Menu>
          </Paper>
          <Box>
            {tab === "dashboard" ? renderDashboard() : null}
            {tab === "projects" ? renderProjects() : null}
            {tab === "models" ? renderModels() : null}
            {tab === "search" ? renderElementSearch() : null}
            {tab === "diagram-viewer" ? renderDiagramViewer() : null}
            {tab === "compare" ? renderCompare() : null}
            {tab === "agent" ? renderWorkbenchAgent() : null}
            {tab === "developer" && isAdmin ? renderDeveloperApi() : null}
            {tab === "api" && isAdmin ? renderApiExplorer() : null}
            {tab === "settings" ? renderSettingsPage() : null}
          </Box>
        </Stack>
      </Box>
    </Box>
  );
}
