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
  fingerprints: Fingerprints;
  near_threshold: number;
  similar: SimilarAnalysis[];
  limitations: string[];
}
