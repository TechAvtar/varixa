import type { AnalysisStatus } from "@verixa/shared-types";
import { Badge } from "@/components/ui/badge";

/** Status is conveyed by text as well as color (no color-only meaning). */
const STYLES: Record<AnalysisStatus, { label: string; className: string }> = {
  queued: { label: "Queued", className: "bg-muted text-muted-foreground" },
  processing: {
    label: "Processing",
    className: "bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200",
  },
  completed: {
    label: "Completed",
    className: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  },
  failed: {
    label: "Failed",
    className: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
  },
};

export function AnalysisStatusBadge({ status }: { status: AnalysisStatus }) {
  const { label, className } = STYLES[status];
  return (
    <Badge variant="outline" className={`border-transparent ${className}`}>
      {label}
    </Badge>
  );
}
