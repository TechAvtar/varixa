import type { AIDetectionResponse } from "@verixa/shared-types";
import { RawJson } from "@/components/analyses/raw-json";
import { EvidenceLevelBadge } from "@/components/evidence/evidence-level-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime } from "@/lib/format";

const LABELS: Record<AIDetectionResponse["label"], string> = {
  likely_ai: "Provider reports a strong AI-generation signal",
  uncertain: "Provider reports a medium, inconclusive signal",
  likely_human: "Provider reports a weak or no AI-generation signal",
  unavailable: "Provider returned no score",
};

export function AICard({ data }: { data: AIDetectionResponse }) {
  const pct = data.score == null ? null : Math.round(data.score * 100);
  return (
    <Card>
      <CardHeader>
        <CardTitle>AI-generation signal</CardTitle>
        <CardDescription>
          One provider&apos;s statistical estimate. It is a signal to weigh, not a finding about who
          or what made this content.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-3">
          <EvidenceLevelBadge level={data.evidence_level} />
          <span className="text-sm font-medium">{LABELS[data.label]}</span>
        </div>

        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span>score as reported</span>
            <span className="tabular-nums">{pct == null ? "—" : `${pct} / 100`}</span>
          </div>
          <div
            role="meter"
            aria-label="Provider score"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={pct ?? undefined}
            className="relative h-2 w-full overflow-hidden rounded bg-muted"
          >
            {pct != null ? (
              <div className="h-full bg-foreground/60" style={{ width: `${pct}%` }} />
            ) : null}
            <div
              className="absolute top-0 h-full w-px bg-foreground/40"
              style={{ left: `${Math.round(data.thresholds.medium * 100)}%` }}
              title="medium threshold"
            />
            <div
              className="absolute top-0 h-full w-px bg-foreground/40"
              style={{ left: `${Math.round(data.thresholds.high * 100)}%` }}
              title="high threshold"
            />
          </div>
          <p className="text-xs text-muted-foreground">
            Thresholds: medium {data.thresholds.medium}, high {data.thresholds.high} (configurable;
            not calibrated across providers).
          </p>
        </div>

        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Provider / model</dt>
          <dd className="font-mono text-xs">
            {data.provider} · {data.model} · v{data.provider_version}
          </dd>
          <dt className="text-muted-foreground">Calibrated</dt>
          <dd>{data.calibrated ? "yes" : "no"}</dd>
          <dt className="text-muted-foreground">Evaluated</dt>
          <dd>
            {formatDateTime(data.evaluated_at)}
            {data.cached ? " · served from cache" : ""}
            {data.latency_ms != null && !data.cached ? ` · ${data.latency_ms} ms` : ""}
          </dd>
        </dl>

        <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
          {data.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>

        <RawJson title="Raw provider response" data={data.raw} />
      </CardContent>
    </Card>
  );
}
