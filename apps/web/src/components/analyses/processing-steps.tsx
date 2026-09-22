import type { AnalysisStepResponse, StepStatus } from "@verixa/shared-types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Human labels for pipeline step names; unknown names fall back to the raw name. */
const STEP_LABELS: Record<string, string> = {
  validate: "Validating file",
  metadata: "Extracting metadata",
  provenance: "Checking provenance",
  fingerprints: "Computing fingerprints",
  forensics: "Running forensics",
  ai: "Checking AI signals",
  search: "Searching sources",
  evidence: "Building evidence",
  report: "Generating report",
};

const STATUS: Record<StepStatus, { label: string; className: string }> = {
  running: {
    label: "Running",
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
  skipped: { label: "Skipped", className: "bg-muted text-muted-foreground" },
};

export function ProcessingSteps({ steps }: { steps: AnalysisStepResponse[] }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Processing</CardTitle>
        <CardDescription>
          Real step status from the pipeline. Nothing here is estimated.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {steps.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            Processing has not started yet. This page does not auto-refresh; reload to check.
          </p>
        ) : (
          <ol className="divide-y">
            {steps.map((s) => {
              const st = STATUS[s.status];
              return (
                <li
                  key={s.name}
                  className="flex flex-wrap items-center gap-x-4 gap-y-1 py-2 text-sm"
                >
                  <span className="min-w-48 font-medium">{STEP_LABELS[s.name] ?? s.name}</span>
                  <Badge variant="outline" className={`border-transparent ${st.className}`}>
                    {st.label}
                  </Badge>
                  {s.duration_ms != null ? (
                    <span className="tabular-nums text-xs text-muted-foreground">
                      {s.duration_ms} ms
                    </span>
                  ) : null}
                  {s.status === "failed" && s.error_message ? (
                    <span className="basis-full text-xs text-destructive">
                      {s.error_code ? `${s.error_code}: ` : ""}
                      {s.error_message}
                    </span>
                  ) : null}
                  {s.status === "skipped" && s.details?.reason ? (
                    <span className="basis-full text-xs text-muted-foreground">
                      {String(s.details.reason)}
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}
