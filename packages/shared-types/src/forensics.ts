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

/** Facts read from the JPEG headers (last save only). */
export interface CompressionEncoding {
  progressive: boolean;
  subsampling: string | null;
  table_count: number;
  estimated_quality: number | null;
  standard_tables: boolean;
  luma_table_error: number | null;
  chroma_estimated_quality: number | null;
  has_jfif: boolean;
  has_adobe: boolean;
}

export interface BlockGrid {
  measured: boolean;
  aligned_strength: number;
  offset_x: number;
  offset_y: number;
  offset_strength: number;
  detected_aligned: boolean;
  detected_offset: boolean;
  profile_x: number[];
  profile_y: number[];
}

export interface CompressionFinding {
  method: "compression";
  version: string;
  observation: string;
  confidence: ForensicConfidence;
  format: string;
  lossless_container: boolean;
  encoding: CompressionEncoding | null;
  grid: BlockGrid;
  /** JPEG with a second, offset block grid (crop/shift then re-save). */
  anomaly: boolean;
  /** Non-JPEG file carrying a JPEG block grid (was probably a JPEG once). */
  prior_jpeg_grid: boolean;
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
  compression: CompressionFinding | null;
  skipped: ForensicSkipped[];
  artifacts: ForensicArtifact[];
  limitations: string[];
}
