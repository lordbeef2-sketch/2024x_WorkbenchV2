import { Chip, Stack, Tooltip } from "@mui/material";

import { Capability } from "../models/api";
import { capabilityColor } from "../utils/format";

interface CapabilityBadgesProps {
  capabilities: Capability[] | Record<string, Capability>;
  size?: "small" | "medium";
}

export default function CapabilityBadges({ capabilities, size = "small" }: CapabilityBadgesProps) {
  const items = Array.isArray(capabilities) ? capabilities : Object.values(capabilities);

  return (
    <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
      {items.map((capability) => (
        <Tooltip key={capability.name} title={capability.reason || capability.source}>
          <Chip
            size={size}
            label={`${capability.name.replaceAll("_", " ")}: ${capability.state}`}
            color={capabilityColor(capability.state)}
            variant={capability.state === "unknown" ? "outlined" : "filled"}
          />
        </Tooltip>
      ))}
    </Stack>
  );
}