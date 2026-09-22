import type { ProviderCallsResponse } from "@verixa/shared-types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const STATUS: Record<string, string> = {
  success: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  cached: "bg-sky-100 text-sky-900 dark:bg-sky-950 dark:text-sky-200",
  failed: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
  timeout: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  skipped: "bg-muted text-muted-foreground",
};

export function ProviderCallsCard({ data }: { data: ProviderCallsResponse | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Engine &amp; provider calls</CardTitle>
        <CardDescription>
          Audit trail of every external provider and local engine used for this analysis, with
          status, latency and estimated cost. Request content is never stored — only its hash.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!data || data.calls.length === 0 ? (
          <p className="text-sm text-muted-foreground">No provider calls were recorded.</p>
        ) : (
          <>
            <ol className="divide-y text-xs">
              {data.calls.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1.5">
                  <Badge
                    variant="outline"
                    className={`border-transparent ${STATUS[c.status] ?? STATUS.skipped}`}
                  >
                    {c.status}
                  </Badge>
                  <span className="font-mono">
                    {c.provider} · {c.operation}
                  </span>
                  {c.model_version ? (
                    <span className="font-mono text-muted-foreground">{c.model_version}</span>
                  ) : null}
                  <span className="ml-auto tabular-nums text-muted-foreground">
                    {c.latency_ms != null ? `${c.latency_ms} ms` : "—"}
                    {c.estimated_cost != null ? ` · $${c.estimated_cost.toFixed(4)}` : ""}
                  </span>
                  {c.error_json ? (
                    <span className="basis-full text-destructive">
                      {String(c.error_json.type ?? "error")}: {String(c.error_json.message ?? "")}
                    </span>
                  ) : null}
                </li>
              ))}
            </ol>
            <p className="text-xs text-muted-foreground">
              Estimated total: {data.currency} {data.total_estimated_cost.toFixed(4)}
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
