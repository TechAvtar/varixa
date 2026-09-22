import type { EvidenceLevel } from "@verixa/shared-types";
import { Badge } from "@/components/ui/badge";
import { LEVEL_STYLES } from "@/lib/evidence";

/** Level is always spelled out in text; colour is reinforcement only. */
export function EvidenceLevelBadge({ level }: { level: EvidenceLevel }) {
  const s = LEVEL_STYLES[level];
  return (
    <Badge variant="outline" className={`border-transparent font-mono text-[11px] ${s.className}`}>
      {s.label}
    </Badge>
  );
}
