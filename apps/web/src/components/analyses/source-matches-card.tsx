import type { SourceMatchesResponse } from "@verixa/shared-types";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime } from "@/lib/format";

function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function SourceMatchesCard({ data }: { data: SourceMatchesResponse | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>External source matches</CardTitle>
        <CardDescription>
          Where a search provider found similar content. A match shows discovery, not origin or
          which copy came first.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!data ? (
          <p className="text-sm text-muted-foreground">
            No source search was performed for this analysis (no provider configured). Its status is
            unknown.
          </p>
        ) : (
          <>
            <p className="text-xs text-muted-foreground">
              {data.provider} v{data.provider_version} · searched {formatDateTime(data.searched_at)}
              {data.modality === "text" && data.queried_phrases.length
                ? ` · ${data.queried_phrases.length} phrase${data.queried_phrases.length === 1 ? "" : "s"} queried`
                : ""}
            </p>

            {data.modality === "text" && data.queried_phrases.length ? (
              <details className="text-xs">
                <summary className="cursor-pointer text-muted-foreground">Queried phrases</summary>
                <ul className="mt-1 list-disc space-y-0.5 pl-5">
                  {data.queried_phrases.map((p) => (
                    <li key={p} className="font-mono">
                      “{p}”
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}

            {data.matches.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                The provider returned no matches. This does not mean the content is original; the
                provider&apos;s index is not the whole web.
              </p>
            ) : (
              <ol className="divide-y text-sm">
                {data.matches.map((m) => (
                  <li key={`${m.rank}-${m.url}`} className="space-y-1 py-2">
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                      <span className="font-mono text-xs text-muted-foreground">#{m.rank}</span>
                      <a
                        href={m.url}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        className="font-medium underline-offset-4 hover:underline"
                      >
                        {m.title ?? hostOf(m.url)}
                      </a>
                      <span className="text-xs text-muted-foreground">{hostOf(m.url)}</span>
                      {m.similarity != null ? (
                        <span className="font-mono text-xs text-muted-foreground">
                          sim {m.similarity.toFixed(2)}
                        </span>
                      ) : null}
                      <span className="text-xs text-muted-foreground">{m.source_kind}</span>
                      {m.published_at ? (
                        <span className="text-xs text-muted-foreground">
                          published {m.published_at}
                        </span>
                      ) : null}
                    </div>
                    {m.matched_phrase ? (
                      <p className="font-mono text-xs text-muted-foreground">
                        matched: “{m.matched_phrase}”
                      </p>
                    ) : null}
                    {m.snippet ? <p className="text-xs">{m.snippet}</p> : null}
                  </li>
                ))}
              </ol>
            )}

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
