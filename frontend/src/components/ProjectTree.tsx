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
import ChevronRightRoundedIcon from "@mui/icons-material/ChevronRightRounded";
import DescriptionRoundedIcon from "@mui/icons-material/DescriptionRounded";
import ExpandMoreRoundedIcon from "@mui/icons-material/ExpandMoreRounded";
import FolderRoundedIcon from "@mui/icons-material/FolderRounded";
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
}

function iconForNode(nodeType: string) {
  const normalized = nodeType.toLowerCase();
  if (normalized === "package" || normalized === "group" || normalized === "model") {
    return <FolderRoundedIcon fontSize="small" />;
  }
  if (normalized.includes("diagram")) {
    return <SchemaRoundedIcon fontSize="small" />;
  }
  if (normalized.includes("table") || normalized.includes("matrix")) {
    return <TableChartRoundedIcon fontSize="small" />;
  }
  if (normalized.includes("block") || normalized.includes("class")) {
    return <AccountTreeRoundedIcon fontSize="small" />;
  }
  if (normalized.includes("activity") || normalized.includes("requirement") || normalized.includes("part")) {
    return <ViewQuiltRoundedIcon fontSize="small" />;
  }
  if (normalized.includes("connector") || normalized.includes("association") || normalized.includes("relationship")) {
    return <DatasetLinkedRoundedIcon fontSize="small" />;
  }
  return <DescriptionRoundedIcon fontSize="small" />;
}

function matchesFilter(node: TreeNode, filter: string): boolean {
  if (!filter) {
    return true;
  }
  const query = filter.toLowerCase();
  if (`${node.label} ${node.path}`.toLowerCase().includes(query)) {
    return true;
  }
  return node.children.some((child) => matchesFilter(child, filter));
}

function humanizeNodeType(nodeType: string): string {
  return nodeType
    .replace(/[_:.-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function declaredChildCount(node: TreeNode): number {
  return typeof node.metadata.child_count === "number"
    ? node.metadata.child_count
    : typeof node.metadata.child_count === "string"
      ? Number.parseInt(node.metadata.child_count, 10)
      : node.children.length;
}

export default function ProjectTree({ nodes, selectedId, filter, onSelect, onExpand, loadingIds = [] }: ProjectTreeProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const visibleNodes = useMemo(() => nodes.filter((node) => matchesFilter(node, filter)), [filter, nodes]);

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
      return changed ? next : current;
    });
  }, [nodes, selectedId]);

  const secondaryText = (node: TreeNode) => {
    const subtitle = typeof node.metadata.subtitle === "string" ? node.metadata.subtitle.trim() : "";
    const childCount = declaredChildCount(node);
    const stereotypes = Array.isArray(node.metadata.stereotypes)
      ? (node.metadata.stereotypes as unknown[]).filter((value) => typeof value === "string" && value.trim()).slice(0, 2) as string[]
      : [];
    const details = [
      humanizeNodeType(node.node_type),
      Number.isFinite(childCount) && childCount > 0 ? `${childCount} children` : "",
      ...stereotypes,
    ].filter(Boolean);
    if (subtitle && !details.includes(subtitle)) {
      details.push(subtitle);
    }
    return details.join(" · ");
  };

  const renderNode = (node: TreeNode, depth = 0) => {
    if (!matchesFilter(node, filter)) {
      return null;
    }
    const childCount = declaredChildCount(node);
    const childrenLoaded = node.metadata.children_loaded === true;
    const hasChildren = node.children.length > 0 || (!childrenLoaded && childCount > 0);
    const isOpen = hasChildren ? (expanded[node.id] ?? true) : false;
    const isLoading = loadingIds.includes(node.id);

    return (
      <Fragment key={node.id}>
        <ListItemButton
          selected={selectedId === node.id}
          onClick={() => onSelect(node)}
          sx={{
            pl: 1 + depth * 2,
            borderRadius: 2,
            mb: 0.25,
            alignItems: "flex-start",
            "&::before": depth
              ? {
                  content: '""',
                  position: "absolute",
                  left: 12 + (depth - 1) * 16,
                  top: 0,
                  bottom: 0,
                  borderLeft: "1px solid",
                  borderColor: "divider",
                }
              : undefined,
          }}
        >
          <Box sx={{ width: 24, display: "flex", alignItems: "center", justifyContent: "center", mr: 0.5 }}>
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
                  setExpanded((current) => ({ ...current, [node.id]: nextOpen }));
                }}
              >
                {isLoading ? <CircularProgress size={16} /> : isOpen ? <ExpandMoreRoundedIcon fontSize="small" /> : <ChevronRightRoundedIcon fontSize="small" />}
              </IconButton>
            ) : null}
          </Box>
          <ListItemIcon sx={{ minWidth: 30 }}>{iconForNode(node.node_type)}</ListItemIcon>
          <ListItemText
            primary={node.label}
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
          <Collapse in={isOpen}>
            <Box sx={{ ml: 1 }}>{node.children.map((child) => renderNode(child, depth + 1))}</Box>
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
