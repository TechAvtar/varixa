"use client";

import type { SourceMatch, SourceMatchesResponse } from "@verixa/shared-types";
import { useId, useMemo, useState } from "react";
import { EvidenceLevelBadge } from "@/components/evidence/evidence-level-badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDateTime } from "@/lib/format";

type SortKey = "rank" | "similarity" | "published";

function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

function sortMatches(list: SourceMatch[], key: SortKey): SourceMatch[] {
  const copy = [...list];
  if (key === "similarity") {
    copy.sort((a, b) => (b.similarity ?? -1) - (a.similarity ?? -1) || a.rank - b.rank);
  } else if (key === "published") {
    copy.sort((a, b) => {
      if (!a.published_at && !b.published_at) return a.rank - b.rank;
      if (!a.published_at) return 1;
      if (!b.published_at) return -1;
      return a.published_at.localeCompare(b.published_at) || a.rank - b.rank;
    });
  } else {
    copy.sort((a, b) => a.rank - b.rank);
  }
  return copy;
}

/**
 * Matches view (docs/05 §7, docs/06): URL, title, similarity, provider, discovery time and
 * limitations for every match. Every match is a POSSIBLE signal (docs/07) unless corroborated;
 * nothing here says where the content came from or which copy came first.
 */
export function SourceMatchesCard({ data }: { data: SourceMatchesResponse | null }) {
  const id = useId();
  const [sort, setSort] = useState<SortKey>("rank");
  const [kind, setKind] = useState<string>("all");
  const [domain, setDomain] = useState<string>("");

  const matches = useMemo(() => data?.matches ?? [], [data]);
  const visible = useMemo(() => {
    const filtered = matches.filter(
      (m) =>
        (kind === "all" || m.source_kind === kind) &&
        (domain === "" || hostOf(m.url).includes(domain.trim().toLowerCase())),
    );
    return sortMatches(filtered, sort);
  }, [matches, sort, kind, domain]);

  if (!data) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>External source matches</CardTitle>
          <CardDescription>
            No source search was performed for this analysis (no provider configured). Its status is
            unknown; this is not evidence of originality.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const s = data.summary;
  const kinds = Object.keys(s.kinds);
  return (
    <Card>
      <CardHeader>
        <CardTitle>External source matches</CardTitle>
        <CardDescription>
          Where the search provider found similar content. A match shows discovery, not origin or
          which copy came first; each one is a POSSIBLE signal unless corroborated by stronger
          evidence.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs sm:grid-cols-[auto_1fr_auto_1fr]">
          <dt className="text-muted-foreground">Provider</dt>
          <dd className="font-mono">
            {data.provider}@{data.provider_version}
          </dd>
          <dt className="text-muted-foreground">Searched</dt>
          <dd className="font-mono">{formatDateTime(data.searched_at)}</dd>
          <dt className="text-muted-foreground">Matches</dt>
          <dd className="font-mono">
            {s.match_count} across {s.domain_count} domain{s.domain_count === 1 ? "" : "s"}
          </dd>
          <dt className="text-muted-foreground">Similarity range</dt>
          <dd className="font-mono">
            {s.similarity_min != null && s.similarity_max != null
              ? `${s.similarity_min.toFixed(2)} – ${s.similarity_max.toFixed(2)}`
              : "not reported"}
          </dd>
          <dt className="text-muted-foreground">Earliest reported date</dt>
          <dd className="font-mono">
            {s.earliest_published_at ? (
              <>
                {s.earliest_published_at}
                <span className="ml-1 font-sans text-muted-foreground">
                  as reported by the source; not when the content was created
                </span>
              </>
            ) : (
              `none reported (${s.dated_count} of ${s.match_count} dated)`
            )}
          </dd>
          {data.modality === "text" ? (
            <>
              <dt className="text-muted-foreground">Phrases queried</dt>
              <dd className="font-mono">{data.queried_phrases.length}</dd>
            </>
          ) : null}
        </dl>

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

        {matches.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            The provider returned no matches. This does not mean the content is original; the
            provider&apos;s index is not the whole web.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs">
              <label htmlFor={`${id}-sort`} className="inline-flex items-center gap-1.5">
                Sort
                <select
                  id={`${id}-sort`}
                  value={sort}
                  onChange={(e) => setSort(e.target.value as SortKey)}
                  className="rounded border bg-background px-1.5 py-0.5"
                >
                  <option value="rank">provider rank</option>
                  <option value="similarity">similarity</option>
                  <option value="published">reported date</option>
                </select>
              </label>
              <label htmlFor={`${id}-kind`} className="inline-flex items-center gap-1.5">
                Kind
                <select
                  id={`${id}-kind`}
                  value={kind}
                  onChange={(e) => setKind(e.target.value)}
                  className="rounded border bg-background px-1.5 py-0.5"
                >
                  <option value="all">all</option>
                  {kinds.map((k) => (
                    <option key={k} value={k}>
                      {k} ({s.kinds[k]})
                    </option>
                  ))}
                </select>
              </label>
              <label htmlFor={`${id}-domain`} className="inline-flex items-center gap-1.5">
                Domain
                <input
                  id={`${id}-domain`}
                  type="search"
                  value={domain}
                  onChange={(e) => setDomain(e.target.value)}
                  placeholder="filter by host"
                  className="w-40 rounded border bg-background px-1.5 py-0.5"
                />
              </label>
              <span className="text-muted-foreground" aria-live="polite">
                {visible.length} of {matches.length} shown
              </span>
            </div>

            <ol className="divide-y text-sm" aria-label="Source matches">
              {visible.map((m) => (
                <li key={`${m.rank}-${m.url}`} className="space-y-1.5 py-3">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="font-mono text-xs text-muted-foreground">#{m.rank}</span>
                    <EvidenceLevelBadge level="POSSIBLE" />
                    <a
                      href={m.url}
                      target="_blank"
                      rel="noopener noreferrer nofollow"
                      className="font-medium underline-offset-4 hover:underline"
                    >
                      {m.title ?? hostOf(m.url)}
                    </a>
                    <span className="text-xs text-muted-foreground">{hostOf(m.url)}</span>
                  </div>
                  <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-0.5 text-xs sm:grid-cols-[auto_1fr_auto_1fr]">
                    <dt className="text-muted-foreground">Provider</dt>
                    <dd className="font-mono">{m.provider}</dd>
                    <dt className="text-muted-foreground">Kind</dt>
                    <dd className="font-mono">{m.source_kind}</dd>
                    <dt className="text-muted-foreground">Similarity</dt>
                    <dd>
                      {m.similarity != null ? (
                        <span className="inline-flex items-center gap-2">
                          <span
                            aria-hidden
                            className="inline-block h-1.5 w-24 overflow-hidden rounded bg-muted"
                          >
                            <span
                              className="block h-full bg-foreground/60"
                              style={{ width: `${Math.round(Math.min(1, m.similarity) * 100)}%` }}
                            />
                          </span>
                          <span className="font-mono">{m.similarity.toFixed(2)}</span>
                          <span className="text-muted-foreground">provider scale</span>
                        </span>
                      ) : (
                        <span className="text-muted-foreground">not reported</span>
                      )}
                    </dd>
                    <dt className="text-muted-foreground">Reported date</dt>
                    <dd className="font-mono">{m.published_at ?? "—"}</dd>
                    <dt className="text-muted-foreground">Discovered</dt>
                    <dd className="font-mono">{formatDateTime(m.discovered_at)}</dd>
                    <dt className="text-muted-foreground">URL</dt>
                    <dd className="break-all font-mono">{m.url}</dd>
                  </dl>
                  {m.matched_phrase ? (
                    <p className="font-mono text-xs text-muted-foreground">
                      matched: “{m.matched_phrase}”
                    </p>
                  ) : null}
                  {m.snippet ? <p className="text-xs">{m.snippet}</p> : null}
                  {Object.keys(m.raw).length > 0 ? (
                    <details className="text-xs">
                      <summary className="cursor-pointer text-muted-foreground">
                        Raw provider record
                      </summary>
                      <pre className="mt-1 max-h-48 overflow-auto rounded border bg-muted/40 p-2 font-mono text-[11px]">
                        {JSON.stringify(m.raw, null, 2)}
                      </pre>
                    </details>
                  ) : null}
                </li>
              ))}
            </ol>
          </>
        )}

        <ul className="space-y-1 border-t pt-3 text-xs text-muted-foreground">
          {data.limitations.map((l) => (
            <li key={l}>{l}</li>
          ))}
          <li>
            Similarity values are on the provider&apos;s own scale and are not comparable across
            providers.
          </li>
          <li>Links open the third-party page directly; Verixa does not fetch or store it.</li>
        </ul>
      </CardContent>
    </Card>
  );
}
