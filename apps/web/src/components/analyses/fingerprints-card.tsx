import type { ImageFingerprintsResponse } from "@verixa/shared-types";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime } from "@/lib/format";

export function FingerprintsCard({ data }: { data: ImageFingerprintsResponse | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Fingerprints</CardTitle>
        <CardDescription>
          Exact-content hashes identify these bytes; perceptual hashes let visually similar images
          be found. Similarity is a signal, not proof of origin.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!data ? (
          <p className="text-sm text-muted-foreground">
            Fingerprints have not been computed for this analysis.
          </p>
        ) : (
          <>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-xs">
              {(["sha256", "md5", "phash", "dhash", "ahash"] as const).map((k) => (
                <div key={k} className="contents">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="break-all font-mono">{data.fingerprints[k]}</dd>
                </div>
              ))}
              <dt className="text-muted-foreground">algorithm</dt>
              <dd className="font-mono">{data.fingerprints.algorithm_version}</dd>
            </dl>

            <div className="space-y-2 border-t pt-3">
              <h3 className="text-sm font-medium">
                Similar analyses in your account
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  near = ≤ {data.near_threshold} bits on pHash or dHash
                </span>
              </h3>
              {data.similar.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No exact or near duplicates among your other analyses.
                </p>
              ) : (
                <ul className="divide-y text-sm">
                  {data.similar.map((s) => (
                    <li
                      key={s.analysis_id}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2"
                    >
                      <Badge
                        variant="outline"
                        className={
                          s.relation === "exact"
                            ? "border-transparent bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
                            : "border-transparent bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200"
                        }
                      >
                        {s.relation === "exact" ? "Identical bytes" : "Near duplicate"}
                      </Badge>
                      <Link
                        href={`/analyses/${s.analysis_id}`}
                        className="font-medium underline-offset-4 hover:underline"
                      >
                        {s.title ?? "Untitled"}
                      </Link>
                      <span className="text-xs text-muted-foreground">
                        {formatDateTime(s.created_at)}
                      </span>
                      <span className="font-mono text-xs text-muted-foreground">
                        p{s.phash_distance} · d{s.dhash_distance} · a{s.ahash_distance}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
              {data.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
