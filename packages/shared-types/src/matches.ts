/** Mirrors `app/schemas/matches.py`. A match is a discovery signal, never proof of origin. */

export type SourceKind =
  "web_page" | "image" | "document" | "social" | "unknown";

export interface SourceMatch {
  rank: number;
  provider: string;
  url: string;
  title: string | null;
  snippet: string | null;
  /** Provider relevance 0–1 when available; not comparable across providers. */
  similarity: number | null;
  source_kind: SourceKind | string;
  matched_phrase: string | null;
  published_at: string | null;
  discovered_at: string;
  raw: Record<string, unknown>;
}

/** Deterministic roll-up of the run. Dates are as reported by sources, never inferred. */
export interface SourceMatchesSummary {
  match_count: number;
  domains: string[];
  domain_count: number;
  kinds: Record<string, number>;
  similarity_min: number | null;
  similarity_max: number | null;
  dated_count: number;
  earliest_published_at: string | null;
  earliest_published_url: string | null;
}

export interface SourceMatchesResponse {
  modality: "image" | "text";
  provider: string;
  provider_version: string;
  searched_at: string;
  queried_phrases: string[];
  matches: SourceMatch[];
  summary: SourceMatchesSummary;
  limitations: string[];
}
