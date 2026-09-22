/** Mirrors `app/schemas/matches.py`. A match is a discovery signal, never proof of origin. */

export type SourceKind = "web_page" | "image" | "document" | "social" | "unknown";

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

export interface SourceMatchesResponse {
  modality: "image" | "text";
  provider: string;
  provider_version: string;
  searched_at: string;
  queried_phrases: string[];
  matches: SourceMatch[];
  limitations: string[];
}
