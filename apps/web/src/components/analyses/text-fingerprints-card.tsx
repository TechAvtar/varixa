import type { TextFingerprintsResponse } from "@verixa/shared-types";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime } from "@/lib/format";

const RELATION: Record<string, { label: string; className: string }> = {
  exact: {
    label: "Identical bytes",
    className: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  },
  normalized: {
    label: "Identical after normalisation",
    className: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  },
  canonical: {
    label: "Same words (case/punctuation differ)",
    className: "bg-teal-100 text-teal-900 dark:bg-teal-950 dark:text-teal-200",
  },
  near: {
    label: "Near duplicate",
    className: "bg-blue-100 text-blue-900 dark:bg-blue-950 dark:text-blue-200",
  },
};

export function TextFingerprintsCard({ data }: { data: TextFingerprintsResponse | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Text fingerprints</CardTitle>
        <CardDescription>
          Exact, normalised and canonical hashes identify this text; a MinHash signature over 5-word
          shingles finds near duplicates among your analyses. Similarity is a signal, not proof of
          copying.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!data ? (
          <p className="text-sm text-muted-foreground">Fingerprints have not been computed.</p>
        ) : (
          <>
            <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-1 text-xs">
              {(["sha256", "normalized_sha256", "canonical_sha256"] as const).map((k) => (
                <div key={k} className="contents">
                  <dt className="text-muted-foreground">{k}</dt>
                  <dd className="break-all font-mono">{data.fingerprints[k]}</dd>
                </div>
              ))}
              <dt className="text-muted-foreground">shingles</dt>
              <dd className="font-mono">
                {data.fingerprints.shingle_count.toLocaleString()} ·{" "}
                {data.fingerprints.algorithm_version}
              </dd>
            </dl>

            <div className="space-y-2 border-t pt-3">
              <h3 className="text-sm font-medium">
                Similar texts in your account
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  near = estimated Jaccard ≥ {data.near_threshold.toFixed(2)}
                </span>
              </h3>
              {data.similar.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No exact, canonical or near duplicates among your other text analyses.
                </p>
              ) : (
                <ul className="divide-y text-sm">
                  {data.similar.map((s) => {
                    const r = RELATION[s.relation] ?? RELATION.near;
                    return (
                      <li
                        key={s.analysis_id}
                        className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2"
                      >
                        <Badge variant="outline" className={`border-transparent ${r.className}`}>
                          {r.label}
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
                          J≈{s.estimated_jaccard.toFixed(2)}
                        </span>
                      </li>
                    );
                  })}
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
