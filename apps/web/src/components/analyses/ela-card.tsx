import type { ImageForensicsResponse } from "@verixa/shared-types";
import Image from "next/image";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function Verdict({ anomaly }: { anomaly: boolean }) {
  return anomaly ? (
    <Badge
      variant="outline"
      className="border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
    >
      POSSIBLE · localised error-level pattern
    </Badge>
  ) : (
    <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
      UNKNOWN · no localised pattern found
    </Badge>
  );
}

export function ELACard({ data }: { data: ImageForensicsResponse | null }) {
  const ela = data?.ela ?? null;
  const skipped = data?.skipped.find((s) => s.method === "ela") ?? null;
  const artifact = data?.artifacts.find((a) => a.method === "ela") ?? null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Error Level Analysis (ELA)</CardTitle>
        <CardDescription>
          Re-saves the JPEG at a known quality and maps how much each area changes. Areas with a
          different compression history <em>can</em> stand out. A heuristic: bright regions also
          come from edges, text and saturated colour.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!data ? (
          <p className="text-sm text-muted-foreground">
            Forensic analysis has not been run for this analysis.
          </p>
        ) : skipped ? (
          <p className="text-sm text-muted-foreground">Not applicable: {skipped.reason}</p>
        ) : !ela ? (
          <p className="text-sm text-muted-foreground">
            ELA did not produce a result for this analysis (the step failed or was not run).
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Verdict anomaly={ela.anomaly} />
              <span className="text-xs text-muted-foreground">
                method confidence: {ela.confidence} · {ela.method} {ela.version}
              </span>
            </div>
            <p className="text-sm">{ela.observation}</p>

            {artifact ? (
              <figure className="space-y-1">
                <div className="overflow-hidden rounded border bg-black">
                  <Image
                    src={artifact.url}
                    alt="Amplified error-level map: brighter areas changed more on re-compression"
                    width={artifact.width}
                    height={artifact.height}
                    unoptimized
                    className="mx-auto h-auto max-h-[70vh] w-auto max-w-full"
                  />
                </div>
                <figcaption className="text-xs text-muted-foreground">
                  Amplified difference map, {artifact.width} × {artifact.height} px
                  {ela.downscaled ? " (downscaled working copy)" : ""}. Link expires in{" "}
                  {Math.round(artifact.expires_in_seconds / 60)} min; reload for a fresh one.
                </figcaption>
              </figure>
            ) : null}

            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr_auto_1fr]">
              <dt className="text-muted-foreground">Resave quality</dt>
              <dd className="font-mono">{ela.quality}</dd>
              <dt className="text-muted-foreground">Mean / p95 / max error</dt>
              <dd className="font-mono">
                {ela.mean_error} / {ela.p95_error} / {ela.max_error}
              </dd>
              <dt className="text-muted-foreground">Outlier blocks</dt>
              <dd className="font-mono">
                {(ela.outlier_block_fraction * 100).toFixed(2)}% (&gt; {ela.outlier_sigma}σ,{" "}
                {ela.block_size}px blocks)
              </dd>
              <dt className="text-muted-foreground">Analysed size</dt>
              <dd className="font-mono">
                {ela.working_width} × {ela.working_height}
                {ela.downscaled ? ` of ${ela.original_width} × ${ela.original_height}` : ""}
              </dd>
            </dl>

            {ela.regions.length > 0 ? (
              <div className="space-y-1">
                <h3 className="text-sm font-medium">
                  Regions with elevated error
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    original pixel coordinates, largest first
                  </span>
                </h3>
                <ul className="divide-y text-xs">
                  {ela.regions.map((r, i) => (
                    <li key={i} className="flex flex-wrap gap-x-4 py-1 font-mono">
                      <span>
                        x {r.x} y {r.y}
                      </span>
                      <span>
                        {r.width} × {r.height} px
                      </span>
                      <span className="text-muted-foreground">
                        {r.blocks} blocks · mean {r.mean_error}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              {ela.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
