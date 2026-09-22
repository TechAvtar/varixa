/** Mirrors `app/schemas/text.py`. */

export interface TextAnalysisCreate {
  text: string;
  title?: string | null;
}

export interface LanguageGuess {
  language: string | null;
  /** Detector probability, 0–1. Not calibrated; a signal, not a fact. */
  confidence: number | null;
  candidates: Array<{ lang: string; prob: number }>;
  engine: string;
  reason: string | null;
}

export interface TextAnalysisResponse {
  original_excerpt: string;
  normalized_excerpt: string;
  excerpt_chars: number;
  truncated: boolean;
  original_sha256: string | null;
  normalized_sha256: string;
  normalization: Record<string, unknown>;
  language: LanguageGuess | null;
  statistics: Record<string, unknown>;
  structure: Record<string, unknown>;
  limitations: string[];
}

/** Input constraints enforced by the API (client checks are a courtesy only). */
export const TEXT_INPUT = { maxChars: 200_000 } as const;
