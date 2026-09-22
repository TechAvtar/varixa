/** Mirrors `app/schemas/forensics.py`. */

export type ForensicConfidence = "low" | "medium" | "high";

/** Bounding box in original image pixels. */
export interface ForensicRegion {
  x: number;
  y: number;
  width: number;
  height: number;
  blocks: number;
  mean_error: number;
}

export interface ELAFinding {
  method: "ela";
  version: string;
  observation: string;
  confidence: ForensicConfidence;
  /** Localised outlier regions were found within the configured band. Never proof on its own. */
  anomaly: boolean;
  quality: number;
  original_width: number;
  original_height: number;
  working_width: number;
  working_height: number;
  downscaled: boolean;
  mean_error: number;
  std_error: number;
  p95_error: number;
  max_error: number;
  block_size: number;
  outlier_sigma: number;
  outlier_block_fraction: number;
  regions: ForensicRegion[];
  limitations: string[];
}

export interface ForensicSkipped {
  method: string;
  reason: string;
}

export interface ForensicArtifact {
  name: string;
  method: string;
  content_type: string;
  width: number;
  height: number;
  /** Short-lived signed URL. */
  url: string;
  expires_in_seconds: number;
}

export interface ImageForensicsResponse {
  ela: ELAFinding | null;
  skipped: ForensicSkipped[];
  artifacts: ForensicArtifact[];
  limitations: string[];
}
