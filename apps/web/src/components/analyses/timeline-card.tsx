import type { TimelineResponse } from "@verixa/shared-types";
import { EvidenceLevelBadge } from "@/components/evidence/evidence-level-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime } from "@/lib/format";

const TYPE_LABEL: Record<string, string> = {
  "provenance.signed": "Manifest signed",
  "metadata.captured": "Capture time",
  "metadata.modified": "Modification time",
  "source.published": "Published (as reported)",
  "source.discovered": "Found by source search",
  "analysis.submitted": "Submitted to Verixa",
};

function label(type: string): string {
  if (type.startsWith("provenance.action:")) return `Manifest action: ${type.split(":")[1]}`;
  return TYPE_LABEL[type] ?? type;
}

/** Vertical timeline (docs/08 §6): event, date/time, evidence level, source. Recorded times only. */
export function TimelineCard({ data }: { data: TimelineResponse }) {
  const dated = data.events.filter((e) => e.event_time);
  const undated = data.events.filter((e) => !e.event_time);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Timeline</CardTitle>
        <CardDescription>
          Times that some system recorded, in order. Each carries the evidence level of the record
          it came from; nothing on this line is inferred. Generated{" "}
          {formatDateTime(data.generated_at)}, timeline {data.version}.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {dated.length === 0 ? (
          <p className="text-sm text-muted-foreground">No dated events could be placed.</p>
        ) : (
          <ol className="relative ml-3 space-y-5 border-l pl-6" aria-label="Dated events">
            {dated.map((e) => (
              <li key={e.id} className="relative">
                <span
                  aria-hidden
                  className="absolute -left-[31px] top-1.5 h-2.5 w-2.5 rounded-full border-2 border-foreground bg-background"
                />
                <div className="flex flex-wrap items-center gap-2">
                  <time dateTime={e.event_time ?? undefined} className="font-mono text-xs">
                    {formatDateTime(e.event_time as string)}
                  </time>
                  {!e.tz_known ? (
                    <span className="text-[11px] text-muted-foreground">
                      timezone not recorded · placed as UTC
                    </span>
                  ) : null}
                  <EvidenceLevelBadge level={e.certainty} />
                  <span className="ml-auto font-mono text-[11px] text-muted-foreground">
                    {e.source}
                  </span>
                </div>
                <p className="mt-1 text-sm font-medium">{label(e.event_type)}</p>
                <p className="text-sm text-muted-foreground">{e.description}</p>
                {e.raw_time ? (
                  <p className="font-mono text-[11px] text-muted-foreground">
                    recorded as {e.raw_time}
                  </p>
                ) : null}
              </li>
            ))}
          </ol>
        )}

        {undated.length > 0 ? (
          <div className="space-y-2">
            <h3 className="text-sm font-medium">
              Recorded but not placeable
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                the recorded value could not be parsed as a time
              </span>
            </h3>
            <ul className="divide-y text-sm">
              {undated.map((e) => (
                <li key={e.id} className="flex flex-wrap items-center gap-2 py-2">
                  <EvidenceLevelBadge level={e.certainty} />
                  <span className="font-medium">{label(e.event_type)}</span>
                  <span className="text-muted-foreground">{e.description}</span>
                  <span className="font-mono text-[11px] text-muted-foreground">
                    {e.raw_time ?? "—"} · {e.source}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
          {data.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}
