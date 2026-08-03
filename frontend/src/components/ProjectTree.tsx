// Created by: Raymond Reeves Engineering Tech 4 2026
import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Box,
  CircularProgress,
  Collapse,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import AccountTreeRoundedIcon from "@mui/icons-material/AccountTreeRounded";
import ArticleRoundedIcon from "@mui/icons-material/ArticleRounded";
import CategoryRoundedIcon from "@mui/icons-material/CategoryRounded";
import ChevronRightRoundedIcon from "@mui/icons-material/ChevronRightRounded";
import ClassRoundedIcon from "@mui/icons-material/ClassRounded";
import CommentRoundedIcon from "@mui/icons-material/CommentRounded";
import DescriptionRoundedIcon from "@mui/icons-material/DescriptionRounded";
import DeviceHubRoundedIcon from "@mui/icons-material/DeviceHubRounded";
import ExpandMoreRoundedIcon from "@mui/icons-material/ExpandMoreRounded";
import ExtensionRoundedIcon from "@mui/icons-material/ExtensionRounded";
import FolderRoundedIcon from "@mui/icons-material/FolderRounded";
import FolderSpecialRoundedIcon from "@mui/icons-material/FolderSpecialRounded";
import HubRoundedIcon from "@mui/icons-material/HubRounded";
import PolylineRoundedIcon from "@mui/icons-material/PolylineRounded";
import SchemaRoundedIcon from "@mui/icons-material/SchemaRounded";
import TableChartRoundedIcon from "@mui/icons-material/TableChartRounded";
import ViewQuiltRoundedIcon from "@mui/icons-material/ViewQuiltRounded";
import DatasetLinkedRoundedIcon from "@mui/icons-material/DatasetLinkedRounded";

import { TreeNode } from "../models/api";

interface ProjectTreeProps {
  nodes: TreeNode[];
  selectedId?: string;
  filter: string;
  onSelect: (node: TreeNode) => void;
  onExpand?: (node: TreeNode) => void | Promise<void>;
  loadingIds?: string[];
  expandedIds?: string[];
  onExpandedChange?: (expandedIds: string[]) => void;
  showFullTypes?: boolean;
}

function iconForNode(node: TreeNode) {
  const nodeType = node.node_type || "";
  const metaclass = typeof node.metadata.metaclass === "string" ? node.metadata.metaclass : "";
  const subtitle = typeof node.metadata.subtitle === "string" ? node.metadata.subtitle : "";
  const label = node.label || "";
  const normalized = `${nodeType} ${metaclass} ${subtitle} ${label}`.toLowerCase();
  const iconSx = { fontSize: 18 };

  if (node.metadata.cameo_virtual_folder === "relations" || label.toLowerCase() === "relations") {
    return <HubRoundedIcon sx={{ ...iconSx, color: "#b48cff" }} />;
  }
  if (normalized.includes("package import") || normalized.includes("element import") || normalized.includes("imported")) {
    return <FolderSpecialRoundedIcon sx={{ ...iconSx, color: "#d7b35f" }} />;
  }
  if (normalized.includes("profile") || normalized.includes("stereotype")) {
    return <ExtensionRoundedIcon sx={{ ...iconSx, color: "#c7a7ff" }} />;
  }
  if (normalized === "model" || nodeType.toLowerCase() === "model") {
    return <FolderRoundedIcon sx={{ ...iconSx, color: "#e7c466" }} />;
  }
  if (normalized.includes("package") || nodeType.toLowerCase() === "group") {
    return <FolderRoundedIcon sx={{ ...iconSx, color: "#f1c75b" }} />;
  }
  if (normalized.includes("diagram")) {
    return <SchemaRoundedIcon sx={{ ...iconSx, color: "#78b7ff" }} />;
  }
  if (normalized.includes("table") || normalized.includes("matrix")) {
    return <TableChartRoundedIcon sx={{ ...iconSx, color: "#80d8ff" }} />;
  }
  if (normalized.includes("block") || normalized.includes("class")) {
    return <ClassRoundedIcon sx={{ ...iconSx, color: "#9ee493" }} />;
  }
  if (normalized.includes("activity")) {
    return <DeviceHubRoundedIcon sx={{ ...iconSx, color: "#91d5ff" }} />;
  }
  if (normalized.includes("requirement")) {
    return <ViewQuiltRoundedIcon sx={{ ...iconSx, color: "#ffcf7a" }} />;
  }
  if (normalized.includes("part") || normalized.includes("property") || normalized.includes("port")) {
    return <CategoryRoundedIcon sx={{ ...iconSx, color: "#8ee6c8" }} />;
  }
  if (normalized.includes("connector") || normalized.includes("association") || normalized.includes("relationship")) {
    return <PolylineRoundedIcon sx={{ ...iconSx, color: "#b48cff" }} />;
  }
  if (normalized.includes("comment")) {
    return <CommentRoundedIcon sx={{ ...iconSx, color: "#c5ccd8" }} />;
  }
  if (normalized.includes("document") || normalized.includes("text")) {
    return <ArticleRoundedIcon sx={{ ...iconSx, color: "#c5ccd8" }} />;
  }
  if (normalized.includes("reference") || normalized.includes("dependency")) {
    return <DatasetLinkedRoundedIcon sx={{ ...iconSx, color: "#b48cff" }} />;
  }
  if (normalized.includes("constraint") || normalized.includes("value")) {
    return <AccountTreeRoundedIcon sx={{ ...iconSx, color: "#f3a6ff" }} />;
  }
  return <DescriptionRoundedIcon sx={{ ...iconSx, color: "#c5ccd8" }} />;
}

function pruneTreeForFilter(nodes: TreeNode[], filter: string): TreeNode[] {
  const query = filter.trim().toLowerCase();
  if (!query) {
    return nodes;
  }
  const visit = (node: TreeNode): TreeNode | null => {
    const matchingChildren = node.children
      .map((child) => visit(child))
      .filter((child): child is TreeNode => child !== null);
    const matchesSelf = `${node.label} ${node.path}`.toLowerCase().includes(query);
    if (!matchesSelf && !matchingChildren.length) {
      return null;
    }
    if (matchingChildren === node.children) {
      return node;
    }
    return {
      ...node,
      children: matchingChildren,
    };
  };
  return nodes
    .map((node) => visit(node))
    .filter((node): node is TreeNode => node !== null);
}

function declaredChildCount(node: TreeNode): number {
  return typeof node.metadata.child_count === "number"
    ? node.metadata.child_count
    : typeof node.metadata.child_count === "string"
      ? Number.parseInt(node.metadata.child_count, 10)
      : node.children.length;
}

export default function ProjectTree({
  nodes,
  selectedId,
  filter,
  onSelect,
  onExpand,
  loadingIds = [],
  expandedIds,
  onExpandedChange,
  showFullTypes = true,
}: ProjectTreeProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (!expandedIds) {
      return;
    }
    setExpanded(
      expandedIds.reduce<Record<string, boolean>>((lookup, nodeId) => {
        lookup[nodeId] = true;
        return lookup;
      }, {}),
    );
  }, [expandedIds]);

  const commitExpanded = (next: Record<string, boolean>) => {
    setExpanded(next);
    onExpandedChange?.(
      Object.entries(next)
        .filter(([, isOpen]) => isOpen)
        .map(([nodeId]) => nodeId),
    );
  };

  const visibleNodes = useMemo(() => pruneTreeForFilter(nodes, filter), [filter, nodes]);
  const loadingIdSet = useMemo(() => new Set(loadingIds), [loadingIds]);

  useEffect(() => {
    if (!selectedId) {
      return;
    }
    const ancestorTrail: string[] = [];
    const walk = (candidates: TreeNode[], trail: string[]): boolean => {
      for (const candidate of candidates) {
        if (candidate.id === selectedId) {
          ancestorTrail.push(...trail);
          return true;
        }
        if (walk(candidate.children, [...trail, candidate.id])) {
          return true;
        }
      }
      return false;
    };
    walk(nodes, []);
    if (!ancestorTrail.length) {
      return;
    }
    setExpanded((current) => {
      const next = { ...current };
      let changed = false;
      ancestorTrail.forEach((nodeId) => {
        if (!next[nodeId]) {
          next[nodeId] = true;
          changed = true;
        }
      });
      if (changed) {
        onExpandedChange?.(
          Object.entries(next)
            .filter(([, isOpen]) => isOpen)
            .map(([nodeId]) => nodeId),
        );
      }
      return changed ? next : current;
    });
  }, [nodes, onExpandedChange, selectedId]);

  const secondaryText = (node: TreeNode) => {
    const subtitle = typeof node.metadata.subtitle === "string" ? node.metadata.subtitle.trim() : "";
    const childCount = declaredChildCount(node);
    const stereotypes = Array.isArray(node.metadata.stereotypes)
      ? (node.metadata.stereotypes as unknown[]).filter((value) => typeof value === "string" && value.trim()).slice(0, 2) as string[]
      : [];
    const metaclass = typeof node.metadata.metaclass === "string" ? node.metadata.metaclass.trim() : "";
    const typeLabel = metaclass && metaclass !== node.node_type ? `${node.node_type} / ${metaclass}` : node.node_type;
    const details = [
      showFullTypes ? typeLabel : "",
      Number.isFinite(childCount) && childCount > 0 ? `${childCount} children` : "",
      ...stereotypes,
    ].filter(Boolean);
    if (subtitle && subtitle !== node.label && !details.includes(subtitle)) {
      details.push(subtitle);
    }
    return details.join(" · ");
  };

  const renderNode = (node: TreeNode, depth = 0) => {
    const childCount = declaredChildCount(node);
    const childrenLoaded = node.metadata.children_loaded === true;
    const hasChildren = node.children.length > 0 || (!childrenLoaded && childCount > 0);
    const isOpen = hasChildren ? (expanded[node.id] ?? Boolean(filter)) : false;
    const isLoading = loadingIdSet.has(node.id);
    const visibleChildren = hasChildren && isOpen ? node.children : [];

    return (
      <Fragment key={node.id}>
        <ListItemButton
          selected={selectedId === node.id}
          onClick={() => onSelect(node)}
          sx={{
            pl: 0.75 + depth * 1.5,
            borderRadius: 2,
            mb: 0.125,
            alignItems: "flex-start",
            "&::before": depth
              ? {
                  content: '""',
                  position: "absolute",
                  left: 10 + (depth - 1) * 12,
                  top: 0,
                  bottom: 0,
                  borderLeft: "1px solid",
                  borderColor: "divider",
                }
              : undefined,
          }}
        >
          <Box sx={{ width: 22, display: "flex", alignItems: "center", justifyContent: "center", mr: 0.25 }}>
            {hasChildren ? (
              <IconButton
                size="small"
                onClick={(event) => {
                  event.stopPropagation();
                  const nextOpen = !isOpen;
                  if (
                    nextOpen &&
                    onExpand &&
                    node.children.length === 0 &&
                    childCount > 0 &&
                    !childrenLoaded
                  ) {
                    void onExpand(node);
                  }
                  commitExpanded({ ...expanded, [node.id]: nextOpen });
                }}
              >
                {isLoading ? <CircularProgress size={16} /> : isOpen ? <ExpandMoreRoundedIcon fontSize="small" /> : <ChevronRightRoundedIcon fontSize="small" />}
              </IconButton>
            ) : null}
          </Box>
          <ListItemIcon sx={{ minWidth: 26, mt: 0.1 }}>{iconForNode(node)}</ListItemIcon>
          <ListItemText
            primary={node.label}
            primaryTypographyProps={{ variant: "body2", fontWeight: 500 }}
            secondary={
              <Stack spacing={0.25}>
                <Typography variant="caption" color="text.secondary">
                  {secondaryText(node)}
                </Typography>
              </Stack>
            }
          />
        </ListItemButton>
        {hasChildren ? (
          <Collapse in={isOpen} mountOnEnter unmountOnExit timeout="auto">
            <Box sx={{ ml: 1 }}>{visibleChildren.map((child) => renderNode(child, depth + 1))}</Box>
          </Collapse>
        ) : null}
      </Fragment>
    );
  };

  return visibleNodes.length ? (
    <List disablePadding>{visibleNodes.map((node) => renderNode(node))}</List>
  ) : (
    <Box sx={{ py: 4, textAlign: "center" }}>
      <Typography variant="body2" color="text.secondary">
        No model nodes match the current filter.
      </Typography>
    </Box>
  );
}

// Fully-commented edition notes:
// - File path: frontend/src/components/ProjectTree.tsx
// - This branch intentionally carries extra explanatory comments for handoff, review, and training.
// - Keep behavioral changes on main first, then rebase or regenerate this branch so comments never hide logic drift.
// - The normal main branch keeps the production-readable version with only provenance headers.