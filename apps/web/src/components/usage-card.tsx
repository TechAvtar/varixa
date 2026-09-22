import type { UsagePeriodResponse } from "@verixa/shared-types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatBytes } from "@/lib/format";

function Meter({
  label,
  used,
  limit,
  format,
}: {
  label: string;
  used: number;
  limit: number;
  format: (n: number) => string;
}) {
  const unlimited = limit <= 0;
  const pct = unlimited ? 0 : Math.min(100, Math.round((used / limit) * 100));
  return (
    <div className="space-y-1">
      <div className="flex items-baseline justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono tabular-nums">
          {format(used)}
          {unlimited ? " · no limit" : ` of ${format(limit)} (${pct}%)`}
        </span>
      </div>
      {!unlimited ? (
        <div
          role="progressbar"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-valuenow={used}
          className="h-1.5 w-full overflow-hidden rounded bg-muted"
        >
          <span className="block h-full bg-foreground/60" style={{ width: `${pct}%` }} />
        </div>
      ) : null}
    </div>
  );
}

/** Dashboard usage card (docs/08): this month's activity, storage held, and the limits in force. */
export function UsageCard({ usage }: { usage: UsagePeriodResponse }) {
  const month = new Date(`${usage.period_start}T00:00:00Z`).toLocaleDateString("en-GB", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardDescription>Usage · {month}</CardDescription>
        <CardTitle className="text-3xl tabular-nums">
          {usage.analyses_count.toLocaleString()}
          <span className="ml-1 text-base font-normal text-muted-foreground">
            {usage.analyses_count === 1 ? "analysis" : "analyses"}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <Meter
          label="Analyses this month"
          used={usage.analyses_count}
          limit={usage.analysis_limit}
          format={(n) => n.toLocaleString()}
        />
        <Meter
          label="Storage held"
          used={usage.current_storage_bytes}
          limit={usage.storage_limit_bytes}
          format={formatBytes}
        />
        <Meter
          label="Provider cost this month"
          used={usage.provider_cost}
          limit={usage.provider_cost_limit}
          format={(n) => `$${n.toFixed(4)}`}
        />
        <p className="text-xs text-muted-foreground">
          {usage.image_count} image · {usage.text_count} text · {usage.reports_count} report
          {usage.reports_count === 1 ? "" : "s"} · {usage.provider_calls_count} provider call
          {usage.provider_calls_count === 1 ? "" : "s"}. Counters reset on the 1st (UTC); storage
          held reflects what is currently stored after retention and deletion.
        </p>
      </CardContent>
    </Card>
  );
}
