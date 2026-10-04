import type { ImageForensicsResponse } from "@verixa/shared-types";
import Image from "next/image";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

type Finding = NonNullable<
  ImageForensicsResponse["thumbnail"] | ImageForensicsResponse["c2pa_thumbnail"]
>;

function Verdict({ data }: { data: Finding }) {
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

const VARIANTS = {
  exif: {
    method: "thumbnail",
    title: "Embedded thumbnail",
    description:
      "Compares the picture with the small preview stored in its own EXIF block. Editors that " +
      "change pixels without regenerating the preview leave a thumbnail of the earlier image. " +
      "Any full resave replaces it, so a match proves nothing.",
    stored: "Embedded thumbnail",
    alt: "Embedded EXIF thumbnail as stored in the file",
  },
  c2pa: {
    method: "c2pa_thumbnail",
    title: "Signed thumbnail (C2PA)",
    description:
      "Compares the picture with the thumbnail signed into its Content Credentials manifest: " +
      "what the signer recorded at signing time. When the manifest validates, the pixels are " +
      "unchanged since signing and a difference reflects how the signer made the thumbnail.",
    stored: "Signed claim thumbnail",
    alt: "Thumbnail signed into the C2PA manifest",
  },
} as const;

export function ThumbnailCard({
  data,
  variant = "exif",
}: {
  data: ImageForensicsResponse | null;
  variant?: keyof typeof VARIANTS;
}) {
  const v = VARIANTS[variant];
  const t = (variant === "c2pa" ? data?.c2pa_thumbnail : data?.thumbnail) ?? null;
  const skipped = data?.skipped.find((s) => s.method === v.method) ?? null;
  const diffMap = data?.artifacts.find((a) => a.method === v.method) ?? null;
  const embedded = data?.artifacts.find((a) => a.method === `${v.method}_embedded`) ?? null;
  const hashValid = variant === "c2pa" ? (data?.c2pa_thumbnail?.data_hash_valid ?? null) : null;
  return (
    <Card id={`forensic-${v.method}`}>
      <CardHeader>
        <CardTitle>{v.title}</CardTitle>
        <CardDescription>{v.description}</CardDescription>
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
            {variant === "c2pa" ? (
              <p className="text-xs text-muted-foreground">
                {hashValid === true
                  ? "The manifest validates: the pixels are unchanged since signing."
                  : hashValid === false
                    ? "The manifest does not validate: the thumbnail shows what the signer saw."
                    : "The manifest's validation state is unknown."}
              </p>
            ) : null}

            <div className="grid gap-4 sm:grid-cols-2">
              {embedded ? (
                <figure className="space-y-1">
                  <div className="overflow-hidden rounded border bg-black">
                    <Image
                      src={embedded.url}
                      alt={v.alt}
                      width={embedded.width}
                      height={embedded.height}
                      unoptimized
                      className="mx-auto h-auto max-h-64 w-auto"
                    />
                  </div>
                  <figcaption className="text-xs text-muted-foreground">
                    {v.stored}, {t.thumbnail_width} × {t.thumbnail_height} px, as stored.
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
