/** Mirrors `app/schemas/fingerprints.py`. */

export interface Fingerprints {
  sha256: string;
  md5: string;
  phash: string;
  dhash: string;
  ahash: string;
  algorithm_version: string;
}

export interface SimilarAnalysis {
  analysis_id: string;
  title: string | null;
  created_at: string;
  /** "exact" = identical bytes; "near" = perceptually similar within the threshold. */
  relation: "exact" | "near";
  sha256_match: boolean;
  phash_distance: number;
  dhash_distance: number;
  ahash_distance: number;
}

export interface ImageFingerprintsResponse {
  kind: "image";
  fingerprints: Fingerprints;
  near_threshold: number;
  similar: SimilarAnalysis[];
  limitations: string[];
}

export interface TextFingerprints {
  sha256: string;
  normalized_sha256: string;
  canonical_sha256: string;
  shingle_count: number;
  algorithm_version: string;
}

export interface SimilarText {
  analysis_id: string;
  title: string | null;
  created_at: string;
  /** exact = same bytes; normalized = same after normalisation; canonical = same words; near = shingle overlap. */
  relation: "exact" | "normalized" | "canonical" | "near";
  estimated_jaccard: number;
}

export interface TextFingerprintsResponse {
  kind: "text";
  fingerprints: TextFingerprints;
  near_threshold: number;
  similar: SimilarText[];
  limitations: string[];
}
