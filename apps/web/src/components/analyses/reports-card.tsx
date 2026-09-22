import type { ReportResponse } from "@verixa/shared-types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatBytes, formatDateTime } from "@/lib/format";

export interface ReportWithLink extends ReportResponse {
  /** Short-lived signed URL, resolved server-side for completed reports. */
  url: string | null;
}

/** Export controls plus the list of reports already rendered for this analysis. */
export function ReportsCard({
  reports,
  canExport,
  action,
  error,
}: {
  reports: ReportWithLink[];
  canExport: boolean;
  action: (formData: FormData) => Promise<void>;
  error: string | null;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Export</CardTitle>
        <CardDescription>
          A PDF containing the summary, evidence, metadata, provenance, AI signal, forensics,
          matches, timeline and methodology. Rendered from stored records; stored privately with
          short-lived download links.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <form action={action} className="flex flex-wrap items-center gap-2">
          <input type="hidden" name="format" value="pdf" />
          <Button type="submit" size="sm" disabled={!canExport}>
            Generate PDF report
          </Button>
          {!canExport ? (
            <span className="text-xs text-muted-foreground">
              Available once the analysis has completed.
            </span>
          ) : null}
        </form>
        {error ? (
          <p role="alert" className="text-sm text-red-700 dark:text-red-300">
            {error}
          </p>
        ) : null}
        {reports.length === 0 ? (
          <p className="text-sm text-muted-foreground">No report has been generated yet.</p>
        ) : (
          <ul className="divide-y text-sm">
            {reports.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
                <Badge
                  variant="outline"
                  className={
                    r.status === "completed"
                      ? "border-transparent bg-muted text-muted-foreground"
                      : "border-transparent bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200"
                  }
                >
                  {r.status === "completed" ? r.format.toUpperCase() : "failed"}
                </Badge>
                <span className="font-mono text-xs">{formatDateTime(r.created_at)}</span>
                {r.size_bytes != null ? (
                  <span className="text-xs text-muted-foreground">
                    {formatBytes(r.size_bytes)}
                    {r.page_count ? ` · ${r.page_count} pages` : ""}
                  </span>
                ) : null}
                {r.status === "completed" && r.url ? (
                  <a
                    href={r.url}
                    className="ml-auto text-xs font-medium underline-offset-4 hover:underline"
                  >
                    Download
                  </a>
                ) : r.error_code ? (
                  <span className="ml-auto text-xs text-muted-foreground">{r.error_code}</span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
