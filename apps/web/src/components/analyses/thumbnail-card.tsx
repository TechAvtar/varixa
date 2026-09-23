import type { ImageForensicsResponse } from "@verixa/shared-types";
import Image from "next/image";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function Verdict({ data }: { data: NonNullable<ImageForensicsResponse["thumbnail"]> }) {
  const amber =
    "border-transparent bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200";
  if (data.mismatch_global) {
    return (
      <Badge variant="outline" className={amber}>
        POSSIBLE · thumbnail shows different content
      </Badge>
    );
  }
  if (data.anomaly) {
    return (
      <Badge variant="outline" className={amber}>
        POSSIBLE · region differs from thumbnail
      </Badge>
    );
  }
  if (data.orientation_mismatch || data.aspect_mismatch) {
    return (
      <Badge variant="outline" className={amber}>
        POSSIBLE · {data.orientation_mismatch ? "flipped or rotated" : "cropped"} after thumbnail
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="border-transparent bg-muted text-muted-foreground">
      UNKNOWN · thumbnail matches the image
    </Badge>
  );
}

export function ThumbnailCard({ data }: { data: ImageForensicsResponse | null }) {
  const t = data?.thumbnail ?? null;
  const skipped = data?.skipped.find((s) => s.method === "thumbnail") ?? null;
  const diffMap = data?.artifacts.find((a) => a.method === "thumbnail") ?? null;
  const embedded = data?.artifacts.find((a) => a.method === "thumbnail_embedded") ?? null;
  return (
    <Card id="forensic-thumbnail">
      <CardHeader>
        <CardTitle>Embedded thumbnail</CardTitle>
        <CardDescription>
          Compares the picture with the small preview stored in its own EXIF block. Editors that
          change pixels without regenerating the preview leave a thumbnail of the earlier image. Any
          full resave replaces it, so a match proves nothing.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!data ? (
          <p className="text-sm text-muted-foreground">
            Forensic analysis has not been run for this analysis.
          </p>
        ) : skipped ? (
          <p className="text-sm text-muted-foreground">Not applicable: {skipped.reason}</p>
        ) : !t ? (
          <p className="text-sm text-muted-foreground">
            The thumbnail comparison did not produce a result (the step failed or was not run).
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              <Verdict data={t} />
              <span className="text-xs text-muted-foreground">
                method confidence: {t.confidence} · {t.method} {t.version}
              </span>
            </div>
            <p className="text-sm">{t.observation}</p>

            <div className="grid gap-4 sm:grid-cols-2">
              {embedded ? (
                <figure className="space-y-1">
                  <div className="overflow-hidden rounded border bg-black">
                    <Image
                      src={embedded.url}
                      alt="Embedded EXIF thumbnail as stored in the file"
                      width={embedded.width}
                      height={embedded.height}
                      unoptimized
                      className="mx-auto h-auto max-h-64 w-auto"
                    />
                  </div>
                  <figcaption className="text-xs text-muted-foreground">
                    Embedded thumbnail, {t.thumbnail_width} × {t.thumbnail_height} px, as stored.
                  </figcaption>
                </figure>
              ) : null}
              {diffMap ? (
                <figure className="space-y-1">
                  <div className="overflow-hidden rounded border bg-black">
                    <Image
                      src={diffMap.url}
                      alt="Difference between the image and its embedded thumbnail; brighter means larger difference"
                      width={diffMap.width}
                      height={diffMap.height}
                      unoptimized
                      className="mx-auto h-auto max-h-64 w-auto"
                    />
                  </div>
                  <figcaption className="text-xs text-muted-foreground">
                    Difference map at thumbnail scale; brighter is a larger difference.
                  </figcaption>
                </figure>
              ) : null}
            </div>

            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-sm sm:grid-cols-[auto_1fr_auto_1fr]">
              <dt className="text-muted-foreground">Correlation</dt>
              <dd className="font-mono">{t.correlation.toFixed(3)}</dd>
              <dt className="text-muted-foreground">Best transform</dt>
              <dd className="font-mono">
                {t.best_transform}
                {t.best_transform !== "none" ? ` (${t.best_transform_correlation.toFixed(3)})` : ""}
              </dd>
              <dt className="text-muted-foreground">Aspect ratio</dt>
              <dd className="font-mono">
                image {t.aspect_ratio_image.toFixed(3)} · thumbnail{" "}
                {t.aspect_ratio_thumbnail.toFixed(3)}
              </dd>
              <dt className="text-muted-foreground">Outlier blocks</dt>
              <dd className="font-mono">
                {(t.outlier_block_fraction * 100).toFixed(1)}% · {t.regions.length} region
                {t.regions.length === 1 ? "" : "s"}
              </dd>
            </dl>

            {t.regions.length > 0 ? (
              <ol className="space-y-1 text-xs" aria-label="Regions differing from the thumbnail">
                {t.regions.map((r, i) => (
                  <li key={`${r.x}-${r.y}-${i}`} className="font-mono">
                    ({r.x}, {r.y}) {r.width} × {r.height} px · {r.blocks} blocks · mean diff{" "}
                    {r.mean_diff.toFixed(2)}
                  </li>
                ))}
              </ol>
            ) : null}

            <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              {t.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
