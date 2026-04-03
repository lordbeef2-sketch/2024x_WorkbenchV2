import { Fragment, useMemo, useState } from "react";
import {
  Box,
  Collapse,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Typography,
} from "@mui/material";
import AccountTreeRoundedIcon from "@mui/icons-material/AccountTreeRounded";
import ChevronRightRoundedIcon from "@mui/icons-material/ChevronRightRounded";
import DescriptionRoundedIcon from "@mui/icons-material/DescriptionRounded";
import ExpandMoreRoundedIcon from "@mui/icons-material/ExpandMoreRounded";
import FolderRoundedIcon from "@mui/icons-material/FolderRounded";
import PlayCircleOutlineRoundedIcon from "@mui/icons-material/PlayCircleOutlineRounded";
import SchemaRoundedIcon from "@mui/icons-material/SchemaRounded";

import { TreeNode } from "../models/api";

interface ProjectTreeProps {
  nodes: TreeNode[];
  selectedId?: string;
  filter: string;
  onSelect: (node: TreeNode) => void;
}

function iconForNode(nodeType: string) {
  if (nodeType === "package") {
    return <FolderRoundedIcon fontSize="small" />;
  }
  if (nodeType === "simulation") {
    return <PlayCircleOutlineRoundedIcon fontSize="small" />;
  }
  if (nodeType === "diagram") {
    return <SchemaRoundedIcon fontSize="small" />;
  }
  if (nodeType === "block") {
    return <AccountTreeRoundedIcon fontSize="small" />;
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

export default function ProjectTree({ nodes, selectedId, filter, onSelect }: ProjectTreeProps) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});

  const visibleNodes = useMemo(() => nodes.filter((node) => matchesFilter(node, filter)), [filter, nodes]);

  const renderNode = (node: TreeNode, depth = 0) => {
    if (!matchesFilter(node, filter)) {
      return null;
    }
    const hasChildren = node.children.length > 0;
    const isOpen = expanded[node.id] ?? true;

    return (
      <Fragment key={node.id}>
        <ListItemButton
          selected={selectedId === node.id}
          onClick={() => {
            if (hasChildren) {
              setExpanded((current) => ({ ...current, [node.id]: !isOpen }));
            }
            onSelect(node);
          }}
          sx={{ pl: 2 + depth * 2, borderRadius: 2, mb: 0.5 }}
        >
          <ListItemIcon sx={{ minWidth: 30 }}>{iconForNode(node.node_type)}</ListItemIcon>
          <ListItemText primary={node.label} secondary={node.node_type} />
          {hasChildren ? (isOpen ? <ExpandMoreRoundedIcon fontSize="small" /> : <ChevronRightRoundedIcon fontSize="small" />) : null}
        </ListItemButton>
        {hasChildren ? <Collapse in={isOpen}>{node.children.map((child) => renderNode(child, depth + 1))}</Collapse> : null}
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