import type { ImageForensicsResponse } from "@verixa/shared-types";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function Verdict({ detected, measured }: { detected: boolean; measured: boolean }) {
  if (!measured) {
    return (
      <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
        UNKNOWN · image too small to measure
      </Badge>
    );
  }
  return detected ? (
    <Badge
      variant="outline"
      className="border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
    >
      POSSIBLE · resampling trace (rescaled or rotated at some point)
    </Badge>
  ) : (
    <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
      UNKNOWN · no resampling trace found
    </Badge>
  );
}

export function ResamplingCard({ data }: { data: ImageForensicsResponse | null }) {
  const r = data?.resampling ?? null;
  const skipped = data?.skipped.find((s) => s.method === "resampling") ?? null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Resampling</CardTitle>
        <CardDescription>
          Rescaling or rotating interpolates pixels, which leaves periodic correlations visible as
          isolated peaks in the spectrum of a prediction residual. Routine resizing leaves the same
          trace; this describes processing history, not editing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!data ? (
          <p className="text-sm text-muted-foreground">
            Forensic analysis has not been run for this analysis.
          </p>
        ) : skipped ? (
          <p className="text-sm text-muted-foreground">Not applicable: {skipped.reason}</p>
        ) : !r ? (
          <p className="text-sm text-muted-foreground">
            Resampling analysis did not produce a result (the step failed or was not run).
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Verdict detected={r.detected} measured={r.measured} />
              <span className="text-xs text-muted-foreground">
                method confidence: {r.confidence} · {r.method} {r.version}
              </span>
            </div>
            <p className="text-sm">{r.observation}</p>

            {r.measured ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr_auto_1fr]">
                <dt className="text-muted-foreground">Strongest peak</dt>
                <dd className="font-mono">{r.peak_ratio}× local background</dd>
                <dt className="text-muted-foreground">Tiles averaged</dt>
                <dd className="font-mono">
                  {r.tiles} × {r.tile_size} px
                </dd>
                <dt className="text-muted-foreground">Image</dt>
                <dd className="font-mono">
                  {r.width} × {r.height} px (never resized before analysis)
                </dd>
              </dl>
            ) : null}

            {r.peaks.length > 0 ? (
              <div className="space-y-1">
                <h3 className="text-sm font-medium">
                  Spectral peaks
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    normalised frequency in cycles per pixel, strongest first
                  </span>
                </h3>
                <ul className="divide-y text-xs">
                  {r.peaks.map((p, i) => (
                    <li key={i} className="flex flex-wrap gap-x-4 py-1 font-mono">
                      <span>
                        fx {p.fx} · fy {p.fy}
                      </span>
                      <span className="text-muted-foreground">{p.ratio}× surroundings</span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              {r.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
