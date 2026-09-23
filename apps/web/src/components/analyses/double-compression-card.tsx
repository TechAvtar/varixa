import type { ImageForensicsResponse } from "@verixa/shared-types";
import Image from "next/image";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function Verdict({ anomaly, detected }: { anomaly: boolean; detected: boolean }) {
  const amber =
    "border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200";
  if (anomaly) {
    return (
      <Badge variant="outline" className={amber}>
        POSSIBLE · localised ghost (region with a different JPEG history)
      </Badge>
    );
  }
  if (detected) {
    return (
      <Badge variant="outline" className={amber}>
        POSSIBLE · compressed at least twice (whole image)
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
      UNKNOWN · no ghost found
    </Badge>
  );
}

/** The error-versus-quality curve as bars; the dips are what the method reads. */
function Curve({
  qualities,
  curve,
  primary,
  secondary,
}: {
  qualities: number[];
  curve: number[];
  primary: number;
  secondary: number | null;
}) {
  return (
    <div className="space-y-1">
      <p className="text-xs text-muted-foreground">
        Normalised re-save error by quality (lower is a smaller change)
      </p>
      <ol className="flex items-end gap-px" aria-label="Error by re-save quality">
        {qualities.map((q, i) => {
          const v = curve[i] ?? 0;
          const mark =
            q === secondary
              ? "bg-amber-500"
              : q === primary
                ? "bg-foreground/80"
                : "bg-foreground/30";
          return (
            <li key={q} className="flex flex-col items-center" title={`q${q}: ${v.toFixed(3)}`}>
              <span
                className={`w-2 rounded-sm ${mark}`}
                style={{ height: `${Math.max(2, v * 48)}px` }}
              />
              {q % 10 === 0 ? (
                <span className="font-mono text-[9px] text-muted-foreground">{q}</span>
              ) : (
                <span className="h-[11px]" />
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

export function DoubleCompressionCard({ data }: { data: ImageForensicsResponse | null }) {
  const d = data?.double_compression ?? null;
  const skipped = data?.skipped.find((s) => s.method === "double_compression") ?? null;
  const artifact = data?.artifacts.find((a) => a.method === "double_compression") ?? null;
  return (
    <Card id="forensic-double_compression">
      <CardHeader>
        <CardTitle>Double compression (JPEG ghosts)</CardTitle>
        <CardDescription>
          Re-saves the image across qualities and looks for a second dip in the error curve: a trace
          of an earlier, lower-quality JPEG save. Measured per block, a dip in only part of the
          picture points at a region with a different history. Re-saving is routine; the whole-image
          case is history, not evidence of editing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!data ? (
          <p className="text-sm text-muted-foreground">
            Forensic analysis has not been run for this analysis.
          </p>
        ) : skipped ? (
          <p className="text-sm text-muted-foreground">Not applicable: {skipped.reason}</p>
        ) : !d ? (
          <p className="text-sm text-muted-foreground">
            Double-compression analysis did not produce a result (the step failed or was not run).
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Verdict anomaly={d.anomaly} detected={d.detected} />
              <span className="text-xs text-muted-foreground">
                method confidence: {d.confidence} · {d.method} {d.version}
              </span>
            </div>
            <p className="text-sm">{d.observation}</p>

            <Curve
              qualities={d.qualities}
              curve={d.curve}
              primary={d.primary_quality}
              secondary={d.secondary_quality}
            />

            {artifact ? (
              <figure className="space-y-1">
                <div className="overflow-hidden rounded border bg-black">
                  <Image
                    src={artifact.url}
                    alt="Ghost map: brighter blocks carry a stronger trace of an earlier JPEG compression"
                    width={artifact.width}
                    height={artifact.height}
                    unoptimized
                    className="mx-auto h-auto max-h-96 w-auto"
                  />
                </div>
                <figcaption className="text-xs text-muted-foreground">
                  Ghost map at working size; brighter blocks carry a stronger earlier-compression
                  trace.
                </figcaption>
              </figure>
            ) : null}

            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr_auto_1fr]">
              <dt className="text-muted-foreground">Last save</dt>
              <dd className="font-mono">
                {d.last_quality != null ? `q${d.last_quality}` : `about q${d.primary_quality}`}
                {d.standard_tables === false ? " (custom tables)" : ""}
              </dd>
              <dt className="text-muted-foreground">Earlier save</dt>
              <dd className="font-mono">
                {d.secondary_quality != null
                  ? `about q${d.secondary_quality} (depth ${d.secondary_depth.toFixed(2)})`
                  : "none found"}
              </dd>
              <dt className="text-muted-foreground">Ghost blocks</dt>
              <dd className="font-mono">
                {(d.ghost_block_fraction * 100).toFixed(1)}%
                {d.ghost_quality_local != null ? ` · about q${d.ghost_quality_local}` : ""}
              </dd>
              <dt className="text-muted-foreground">DC histogram</dt>
              <dd className="font-mono">
                {d.periodic ? "periodic" : "not periodic"} (ratio {d.dc_periodicity.toFixed(1)}
                {d.dc_period != null ? `, period ${d.dc_period.toFixed(1)}` : ""})
              </dd>
            </dl>

            {d.regions.length > 0 ? (
              <ol className="space-y-1 text-xs" aria-label="Regions with a localised ghost">
                {d.regions.map((r, i) => (
                  <li key={`${r.x}-${r.y}-${i}`} className="font-mono">
                    ({r.x}, {r.y}) {r.width} × {r.height} px · {r.blocks} blocks · depth{" "}
                    {r.depth.toFixed(2)}
                  </li>
                ))}
              </ol>
            ) : null}

            <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              {d.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
