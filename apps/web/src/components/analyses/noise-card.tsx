import type { ImageForensicsResponse } from "@verixa/shared-types";
import Image from "next/image";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function Verdict({ anomaly, comparable }: { anomaly: boolean; comparable: boolean }) {
  if (!comparable) {
    return (
      <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
        UNKNOWN · could not be compared
      </Badge>
    );
  }
  return anomaly ? (
    <Badge
      variant="outline"
      className="border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
    >
      POSSIBLE · localised noise-level difference
    </Badge>
  ) : (
    <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
      UNKNOWN · noise consistent where comparable
    </Badge>
  );
}

export function NoiseCard({ data }: { data: ImageForensicsResponse | null }) {
  const n = data?.noise ?? null;
  const skipped = data?.skipped.find((s) => s.method === "noise") ?? null;
  const artifact = data?.artifacts.find((a) => a.method === "noise") ?? null;
  const comparable = !!n && n.measured && n.blocks_smooth > 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Noise consistency</CardTitle>
        <CardDescription>
          Sensor noise is roughly uniform across one capture. Smooth areas are compared block by
          block; a compact region with a different noise level can come from a pasted or locally
          processed area, and just as well from depth of field or in-camera denoising.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!data ? (
          <p className="text-sm text-muted-foreground">
            Forensic analysis has not been run for this analysis.
          </p>
        ) : skipped ? (
          <p className="text-sm text-muted-foreground">Not applicable: {skipped.reason}</p>
        ) : !n ? (
          <p className="text-sm text-muted-foreground">
            Noise analysis did not produce a result (the step failed or was not run).
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Verdict anomaly={n.anomaly} comparable={comparable} />
              <span className="text-xs text-muted-foreground">
                method confidence: {n.confidence} · {n.method} {n.version}
              </span>
            </div>
            <p className="text-sm">{n.observation}</p>

            {artifact ? (
              <figure className="space-y-1">
                <div className="overflow-hidden rounded border bg-black">
                  <Image
                    src={artifact.url}
                    alt="Block-level noise map: brighter blocks have a higher estimated noise level"
                    width={artifact.width}
                    height={artifact.height}
                    unoptimized
                    className="mx-auto h-auto max-h-[60vh] w-auto max-w-full"
                  />
                </div>
                <figcaption className="text-xs text-muted-foreground">
                  Block-level noise map ({n.block_size} px blocks, brighter = noisier, all blocks
                  shown including textured ones). Link expires in{" "}
                  {Math.round(artifact.expires_in_seconds / 60)} min; reload for a fresh one.
                </figcaption>
              </figure>
            ) : null}

            {n.measured ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr_auto_1fr]">
                <dt className="text-muted-foreground">Baseline noise</dt>
                <dd className="font-mono">{n.baseline_sigma} grey levels (median)</dd>
                <dt className="text-muted-foreground">Spread (IQR)</dt>
                <dd className="font-mono">{n.spread_sigma}</dd>
                <dt className="text-muted-foreground">Blocks compared</dt>
                <dd className="font-mono">
                  {n.blocks_smooth} smooth of {n.blocks_total}
                </dd>
                <dt className="text-muted-foreground">Outlier blocks</dt>
                <dd className="font-mono">{(n.outlier_fraction * 100).toFixed(2)}% of smooth</dd>
              </dl>
            ) : null}

            {n.regions.length > 0 ? (
              <div className="space-y-1">
                <h3 className="text-sm font-medium">
                  Regions with a different noise level
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    original pixel coordinates, largest first
                  </span>
                </h3>
                <ul className="divide-y text-xs">
                  {n.regions.map((r, i) => (
                    <li key={i} className="flex flex-wrap gap-x-4 py-1 font-mono">
                      <span>
                        x {r.x} y {r.y}
                      </span>
                      <span>
                        {r.width} × {r.height} px
                      </span>
                      <span className="text-muted-foreground">
                        {r.blocks} blocks · noise {r.sigma} (
                        {r.sigma > n.baseline_sigma ? "noisier" : "smoother"})
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              {n.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
