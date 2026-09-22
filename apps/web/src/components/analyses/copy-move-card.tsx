import type { ImageForensicsResponse } from "@verixa/shared-types";
import Image from "next/image";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function Verdict({ detected, measured }: { detected: boolean; measured: boolean }) {
  if (!measured) {
    return (
      <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
        UNKNOWN · image too small to match
      </Badge>
    );
  }
  return detected ? (
    <Badge
      variant="outline"
      className="border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200"
    >
      POSSIBLE · duplicated region (clone or repeated content)
    </Badge>
  ) : (
    <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
      UNKNOWN · no translated duplicate found
    </Badge>
  );
}

export function CopyMoveCard({ data }: { data: ImageForensicsResponse | null }) {
  const c = data?.copy_move ?? null;
  const skipped = data?.skipped.find((s) => s.method === "copy_move") ?? null;
  const artifact = data?.artifacts.find((a) => a.method === "copy_move") ?? null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Copy-move</CardTitle>
        <CardDescription>
          Looks for a patch of the picture that reappears elsewhere in the same picture at a
          constant offset. Cloning does this; so do tiles, brickwork, text and identical products.
          Only translated copies are found.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!data ? (
          <p className="text-sm text-muted-foreground">
            Forensic analysis has not been run for this analysis.
          </p>
        ) : skipped ? (
          <p className="text-sm text-muted-foreground">Not applicable: {skipped.reason}</p>
        ) : !c ? (
          <p className="text-sm text-muted-foreground">
            Copy-move analysis did not produce a result (the step failed or was not run).
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Verdict detected={c.detected} measured={c.measured} />
              <span className="text-xs text-muted-foreground">
                method confidence: {c.confidence} · {c.method} {c.version}
              </span>
            </div>
            <p className="text-sm">{c.observation}</p>

            {artifact && c.detected ? (
              <figure className="space-y-1">
                <div className="overflow-hidden rounded border bg-black">
                  <Image
                    src={artifact.url}
                    alt="Matched blocks: grey marks the source region, white the region it reappears in"
                    width={artifact.width}
                    height={artifact.height}
                    unoptimized
                    className="mx-auto h-auto max-h-[60vh] w-auto max-w-full"
                  />
                </div>
                <figcaption className="text-xs text-muted-foreground">
                  Matched blocks at the working size ({c.working_width} × {c.working_height} px):
                  grey = source, white = where it reappears. Link expires in{" "}
                  {Math.round(artifact.expires_in_seconds / 60)} min; reload for a fresh one.
                </figcaption>
              </figure>
            ) : null}

            {c.measured ? (
              <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-xs sm:grid-cols-[auto_1fr_auto_1fr]">
                <dt className="text-muted-foreground">Blocks compared</dt>
                <dd className="font-mono">
                  {c.blocks_textured.toLocaleString()} textured of {c.blocks_total.toLocaleString()}
                </dd>
                <dt className="text-muted-foreground">Candidate pairs</dt>
                <dd className="font-mono">{c.candidate_pairs.toLocaleString()}</dd>
                <dt className="text-muted-foreground">Working size</dt>
                <dd className="font-mono">
                  {c.working_width} × {c.working_height}
                  {c.downscaled ? ` of ${c.width} × ${c.height}` : ""}
                </dd>
              </dl>
            ) : null}

            {c.matches.length > 0 ? (
              <div className="space-y-1">
                <h3 className="text-sm font-medium">
                  Duplicated regions
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    original pixel coordinates, most block pairs first
                  </span>
                </h3>
                <ul className="divide-y text-xs">
                  {c.matches.map((m, i) => (
                    <li key={i} className="flex flex-wrap gap-x-4 py-1 font-mono">
                      <span>
                        {m.width} × {m.height} px
                      </span>
                      <span>
                        ({m.source_x}, {m.source_y}) → ({m.target_x}, {m.target_y})
                      </span>
                      <span className="text-muted-foreground">
                        shift ({m.shift_x}, {m.shift_y}) · {m.pairs} pairs · density {m.density}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              {c.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
